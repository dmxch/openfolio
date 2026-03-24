"""Swissquote CSV transaction export parser.

Handles Latin-1 encoding, semicolon delimiters, partial execution aggregation,
forex pair matching, bond detection, and ISIN-based symbol mapping.
"""

import asyncio
import csv
import io
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from services.import_service import ImportPreview, ParsedTransaction, enrich_transactions
from services.utils import get_fx_rates_batch
from yf_patch import yf_download

logger = logging.getLogger(__name__)

# Swissquote CSV column names (German)
SQ_COLS = {
    "date": "Datum",
    "order_id": "Auftrag #",
    "type": "Transaktionen",
    "symbol": "Symbol",
    "name": "Name",
    "isin": "ISIN",
    "quantity": "Anzahl",
    "unit_price": "Stückpreis",
    "fees": "Kosten",
    "accrued_interest": "Aufgelaufene Zinsen",
    "net_amount": "Nettobetrag",
    "currency": "Währung Nettobetrag",
    "net_amount_account": "Nettobetrag in Kontowährung",
    "balance": "Saldo",
    "account_currency": "Währung",
}

# ISIN prefix to yfinance suffix
ISIN_SUFFIX = {
    "CH": ".SW",
    "IE": ".L",
    "LU": ".L",
    "GB": ".L",
    "US": "",
    "CA": ".TO",  # Default to TSX; overridden to "" for USD-traded CA stocks
}


def is_swissquote_csv(fieldnames: list[str]) -> bool:
    """Detect if CSV headers match Swissquote export format."""
    if not fieldnames:
        return False
    normalized = {f.strip() for f in fieldnames}
    # Check for key Swissquote-specific columns
    return "Transaktionen" in normalized and ("Stückpreis" in normalized or "St\xfcckpreis" in normalized)


def _map_type(raw: str) -> str:
    """Map Swissquote transaction type to internal type. Encoding-safe."""
    t = raw.strip().lower()

    if t.startswith("kauf"):
        return "buy"
    if t.startswith("verkauf"):
        return "sell"
    if t.startswith("dividende"):
        return "dividend"
    if "capital gain" in t:
        return "capital_gain"
    if t.startswith("zahlung"):
        return "deposit"
    if t.startswith("auszahlung"):
        return "withdrawal"
    if "depotgeb" in t:
        return "fee"
    if "spesen" in t:
        return "fee"
    if "zinsen" in t:
        return "interest"
    if "berichtigung" in t:
        return "fee_correction"
    if "forex-gutschrift" in t or "fx-gutschrift" in t:
        return "fx_credit"
    if "forex-belastung" in t or "fx-belastung" in t:
        return "fx_debit"
    return "unknown"


def _parse_date(val: str) -> datetime | None:
    """Parse Swissquote date format DD-MM-YYYY HH:MM:SS."""
    val = val.strip()
    for fmt in ["%d-%m-%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d-%m-%Y", "%d.%m.%Y"]:
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue  # Expected: trying multiple date formats
    return None


def _parse_num(val: str) -> float:
    """Parse a numeric value, handling Swiss formatting."""
    val = val.strip().replace("'", "").replace("\u2019", "")
    if not val:
        return 0.0
    try:
        return float(val)
    except ValueError:
        logger.debug(f"Could not parse numeric value: {val!r}, returning 0.0")
        return 0.0


def _get_col(row: dict, key: str) -> str:
    """Get column value with fallback for encoding variants."""
    col_name = SQ_COLS.get(key, key)
    val = row.get(col_name, "")
    if not val:
        # Try encoding variants (Latin-1 decoded differently)
        variants = {
            "unit_price": ["St\xfcckpreis", "Stueckpreis"],
            "currency": ["W\xe4hrung Nettobetrag", "Waehrung Nettobetrag"],
            "account_currency": ["W\xe4hrung", "Waehrung"],
            "fees": ["Kosten"],
            "accrued_interest": ["Aufgelaufene Zinsen"],
            "order_id": ["Auftrag #", "Auftrag"],
        }
        for variant in variants.get(key, []):
            val = row.get(variant, "")
            if val:
                break
    return val.strip().strip('"') if val else ""


def _is_bond(row: dict) -> bool:
    """Bonds have % in the unit price field."""
    return "%" in _get_col(row, "unit_price")


def _isin_to_suffix(isin: str) -> str:
    """Map ISIN country prefix to yfinance exchange suffix."""
    if not isin or len(isin) < 2:
        return ""
    return ISIN_SUFFIX.get(isin[:2].upper(), "")


def _map_ticker(symbol: str, isin: str, currency: str = "") -> str:
    """Map Swissquote symbol to yfinance ticker using ISIN and currency.

    For Canadian ISINs (CA*): currency CAD → .TO (TSX), currency USD → no suffix (NYSE).
    """
    if not symbol:
        return ""
    symbol = symbol.strip()
    # Canadian stocks: suffix depends on trading currency
    if isin and isin[:2].upper() == "CA" and currency.upper() == "USD":
        return symbol  # NYSE listing, no suffix
    suffix = _isin_to_suffix(isin)
    if suffix and not symbol.endswith(suffix):
        return symbol + suffix
    return symbol


def _aggregate_partials(rows: list[dict]) -> list[dict]:
    """Aggregate partial executions with the same order_id + symbol.

    order_id == '00000000' are system transactions and should NOT be aggregated.
    """
    groups = defaultdict(list)
    non_aggregatable = []

    for row in rows:
        order_id = row.get("_order_id", "")
        symbol = row.get("_symbol", "")
        if order_id and order_id != "00000000" and symbol:
            groups[(order_id, symbol)].append(row)
        else:
            non_aggregatable.append(row)

    result = list(non_aggregatable)

    for (order_id, symbol), group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue

        # Aggregate: sum quantities, weighted-average price, sum fees
        total_qty = sum(r["_quantity"] for r in group)
        total_value = sum(r["_quantity"] * r["_unit_price"] for r in group)
        weighted_price = total_value / total_qty if total_qty != 0 else 0
        total_fees = sum(r["_fees"] for r in group)
        total_accrued = sum(r["_accrued_interest"] for r in group)
        total_net = sum(r["_net_amount"] for r in group)
        total_net_account = sum(r["_net_amount_account"] for r in group)

        # Use earliest date
        dates = [r["_date"] for r in group if r["_date"]]
        earliest = min(dates) if dates else group[0]["_date"]

        merged = dict(group[0])
        merged["_date"] = earliest
        merged["_quantity"] = total_qty
        merged["_unit_price"] = weighted_price
        merged["_fees"] = total_fees
        merged["_accrued_interest"] = total_accrued
        merged["_net_amount"] = total_net
        merged["_net_amount_account"] = total_net_account
        merged["_is_aggregated"] = True
        merged["_aggregated_count"] = len(group)
        result.append(merged)

    return result


def _pair_forex(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Pair forex credit/debit transactions by order_id. Return (fx_pairs, remaining_rows)."""
    fx_rows = defaultdict(list)
    non_fx = []
    fx_pairs = []

    for row in rows:
        txn_type = row.get("_type", "")
        order_id = row.get("_order_id", "")
        if txn_type in ("fx_credit", "fx_debit") and order_id and order_id != "00000000":
            fx_rows[order_id].append(row)
        else:
            non_fx.append(row)

    for order_id, group in fx_rows.items():
        credits = [r for r in group if r["_type"] == "fx_credit"]
        debits = [r for r in group if r["_type"] == "fx_debit"]

        if credits and debits:
            credit = credits[0]
            debit = debits[0]
            credit_amount = abs(credit["_net_amount"])
            debit_amount = abs(debit["_net_amount"])
            credit_currency = credit["_currency"]
            debit_currency = debit["_currency"]

            if credit_amount > 0:
                rate = round(debit_amount / credit_amount, 6)
            else:
                rate = 0

            fx_date = credit["_date"] or debit["_date"]
            fx_pairs.append({
                "date": fx_date.date().isoformat() if fx_date else "",
                "order_id": order_id,
                "currency_from": debit_currency,
                "currency_to": credit_currency,
                "amount_from": debit_amount,
                "amount_to": credit_amount,
                "rate": rate,
                "pair": f"{credit_currency}{debit_currency}",
            })

        # Keep all FX rows as transactions too
        non_fx.extend(group)

    return fx_pairs, non_fx


def _build_forex_rate_lookup(fx_pairs: list[dict]) -> dict[str, dict[str, float]]:
    """Build a date+currency → FX rate lookup from parsed forex pairs.

    Returns:
        Dict[date_str, Dict[foreign_currency, chf_per_unit]]
        e.g. {"2026-02-25": {"USD": 0.780164, "EUR": 0.9038}}

    For multiple forex pairs on the same day+currency, computes weighted average:
        fx_rate = sum(all_chf_amounts) / sum(all_foreign_amounts)
    """
    # Accumulate raw amounts per date+currency for weighted average
    # key: (date_str, foreign_currency) → {"chf": float, "foreign": float}
    accum: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: {"chf": 0.0, "foreign": 0.0})

    for fx in fx_pairs:
        date_str = fx.get("date", "")
        if not date_str:
            continue

        currency_from = fx.get("currency_from", "")  # debit side (what was paid)
        currency_to = fx.get("currency_to", "")  # credit side (what was received)
        amount_from = abs(float(fx.get("amount_from", 0)))
        amount_to = abs(float(fx.get("amount_to", 0)))

        if amount_from == 0 or amount_to == 0:
            continue

        # Identify which side is CHF and which is foreign
        if currency_from == "CHF":
            # Bought foreign currency: paid CHF, received foreign
            foreign = currency_to
            chf_amount = amount_from
            foreign_amount = amount_to
        elif currency_to == "CHF":
            # Sold foreign currency: paid foreign, received CHF
            foreign = currency_from
            chf_amount = amount_to
            foreign_amount = amount_from
        else:
            # Non-CHF pair (e.g. USD→EUR) — skip, not relevant for CHF conversion
            continue

        key = (date_str, foreign)
        accum[key]["chf"] += chf_amount
        accum[key]["foreign"] += foreign_amount

    # Build final lookup: weighted average
    result: dict[str, dict[str, float]] = {}
    for (date_str, foreign), amounts in accum.items():
        if amounts["foreign"] > 0:
            rate = round(amounts["chf"] / amounts["foreign"], 6)
            if date_str not in result:
                result[date_str] = {}
            result[date_str][foreign] = rate

    return result


async def _get_historical_fx_rate(currency: str, txn_date: str) -> float | None:
    """Fetch historical FX rate from yfinance for a specific date.

    Uses thread-safe yf_download wrapper via asyncio.to_thread.
    """
    try:
        from datetime import date as date_type
        d = date_type.fromisoformat(txn_date) if isinstance(txn_date, str) else txn_date
        ticker = f"{currency}CHF=X"
        # Fetch 5 days to handle weekends/holidays
        start = d
        end = d + timedelta(days=5)
        data = await asyncio.to_thread(
            yf_download, ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            progress=False,
            threads=False,
        )
        if data is not None and not data.empty:
            close = data["Close"]
            if hasattr(close, "iloc"):
                import pandas as pd
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                close = close.dropna()
                if len(close) > 0:
                    return round(float(close.iloc[0]), 6)
    except Exception as e:
        logger.warning(f"yfinance FX fallback failed for {currency} on {txn_date}: {e}")
    return None


async def parse_swissquote_csv(
    text: str, filename: str, db: AsyncSession, user_id: uuid.UUID | None = None
) -> ImportPreview:
    """Parse a Swissquote CSV export into ImportPreview."""
    warnings = []
    skipped_bonds = []
    batch_id = str(uuid.uuid4())

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames:
        raise ValueError("CSV enthält keine Spaltenüberschriften")

    # First pass: parse all rows into internal dicts
    raw_rows = []
    for i, row in enumerate(reader):
        type_raw = _get_col(row, "type")
        txn_type = _map_type(type_raw)

        if txn_type == "unknown":
            warnings.append(f"Zeile {i + 2}: Unbekannter Typ '{type_raw}' — übersprungen")
            continue

        # Bond detection
        if _is_bond(row):
            skipped_bonds.append({
                "date": _get_col(row, "date"),
                "symbol": _get_col(row, "symbol"),
                "name": _get_col(row, "name"),
                "reason": "Anleihe (Bond) — wird derzeit nicht unterstützt",
            })
            continue

        parsed_date = _parse_date(_get_col(row, "date"))
        if not parsed_date:
            warnings.append(f"Zeile {i + 2}: Ungültiges Datum '{_get_col(row, 'date')}'")
            continue

        symbol = _get_col(row, "symbol")
        isin = _get_col(row, "isin")
        name = _get_col(row, "name")
        order_id = _get_col(row, "order_id")

        raw_rows.append({
            "_row": i + 2,
            "_date": parsed_date,
            "_order_id": order_id,
            "_type": txn_type,
            "_type_raw": type_raw,
            "_symbol": symbol,
            "_name": name,
            "_isin": isin,
            "_quantity": _parse_num(_get_col(row, "quantity")),
            "_unit_price": _parse_num(_get_col(row, "unit_price")),
            "_fees": _parse_num(_get_col(row, "fees")),
            "_accrued_interest": _parse_num(_get_col(row, "accrued_interest")),
            "_net_amount": _parse_num(_get_col(row, "net_amount")),
            "_currency": _get_col(row, "currency") or _get_col(row, "account_currency"),
            "_net_amount_account": _parse_num(_get_col(row, "net_amount_account")),
            "_is_aggregated": False,
            "_aggregated_count": 1,
        })

    # Pair forex transactions
    fx_pairs, raw_rows = _pair_forex(raw_rows)

    # Aggregate partial executions (only buy/sell)
    buy_sell_rows = [r for r in raw_rows if r["_type"] in ("buy", "sell")]
    other_rows = [r for r in raw_rows if r["_type"] not in ("buy", "sell")]
    aggregated_rows = _aggregate_partials(buy_sell_rows)
    all_rows = aggregated_rows + other_rows

    # Sort by date
    all_rows.sort(key=lambda r: r["_date"])

    # Build FX rate lookup from forex pairs (date + currency → CHF rate)
    forex_rate_lookup = _build_forex_rate_lookup(fx_pairs)

    # Pre-fetch FX rates for fallback when CSV lacks account-currency amounts
    _fx_cache = get_fx_rates_batch()

    # Track currencies needing yfinance fallback (date, currency) → row indices
    _yf_fallback_needed: list[tuple[int, str, str]] = []  # (list_index, date_str, currency)

    # Convert to ParsedTransaction
    parsed = []
    for row in all_rows:
        txn_type = row["_type"]
        symbol = row["_symbol"]
        isin = row["_isin"]
        currency = row["_currency"]
        mapped_ticker = _map_ticker(symbol, isin, currency) if symbol else None

        # For dividends/capital_gain: shares=1 from CSV, actual amount is in net_amount
        # The unit_price field contains the gross amount for dividends
        shares = row["_quantity"]
        price = row["_unit_price"]
        fees = row["_fees"]
        taxes = 0.0
        gross_amount = None
        tax_amount = None

        if txn_type in ("dividend", "capital_gain"):
            # Swissquote: quantity=1, unit_price=gross, fees=withholding tax, net=after tax
            gross_amount = abs(price) if shares == 1.0 else abs(shares * price)
            tax_amount = abs(fees)
            taxes = abs(fees)
            fees = 0.0
            shares = 0
            price = 0

        # Net amount in account currency (CHF) is the total_chf
        net_account = row["_net_amount_account"]
        net_original = row["_net_amount"]

        # Derive FX rate — priority: forex pairs > CSV columns > yfinance > current market
        fx_rate = 1.0
        fx_source = None
        if currency and currency != "CHF":
            date_str = row["_date"].date().isoformat()

            # 1. Try forex pair lookup (exact settlement rate from Swissquote)
            day_rates = forex_rate_lookup.get(date_str)
            if day_rates and currency in day_rates:
                fx_rate = day_rates[currency]
                fx_source = "broker_forex"
            elif net_account and net_original and net_original != 0:
                # 2. Derive from CSV account-currency columns
                fx_rate = abs(net_account / net_original)
                fx_source = "csv_derived"
            else:
                # 3. Mark for yfinance historical fallback (batch later)
                fx_source = "yfinance_pending"
                # Temporary: use current market rate, will be overwritten
                fx_fallback = _fx_cache.get(currency)
                if fx_fallback:
                    fx_rate = fx_fallback
                else:
                    warnings.append(f"Zeile {row['_row']}: Kein FX-Kurs für {currency} — verwende 1.0")

        # total_chf is always the account-currency amount (CHF)
        if fx_source == "swissquote_forex":
            # Use the forex-derived rate for total_chf calculation
            total_chf = abs(net_original) * fx_rate if net_original else abs(net_account) if net_account else 0
        elif net_account:
            total_chf = abs(net_account)
        elif currency and currency != "CHF" and fx_rate and fx_rate != 1.0:
            total_chf = abs(net_original) * fx_rate
        else:
            total_chf = abs(net_original)

        # Safety net: for dividends/capital_gains in foreign currency, ensure total_chf is converted
        if txn_type in ("dividend", "capital_gain") and currency and currency != "CHF" and fx_rate and fx_rate != 1.0:
            # If total_chf matches the foreign-currency gross amount, it wasn't converted
            if gross_amount and abs(total_chf - gross_amount) < 1.0:
                total_chf = round(gross_amount * fx_rate, 2)
                if tax_amount:
                    total_chf = round((gross_amount - tax_amount) * fx_rate, 2)

        # For deposits/withdrawals, fees etc without ticker — use a special handling
        ticker_for_import = mapped_ticker
        needs_review = False
        if txn_type in ("buy", "sell") and not ticker_for_import:
            warnings.append(f"Zeile {row['_row']}: Kein Symbol für {txn_type}")
            continue
        if ticker_for_import and ticker_for_import != symbol and symbol:
            # Mapped ticker differs from raw — flag for review if needed
            pass

        txn = ParsedTransaction(
            row_index=row["_row"],
            type=txn_type,
            date=row["_date"].date().isoformat(),
            ticker=ticker_for_import,
            isin=isin or None,
            name=row["_name"] or None,
            shares=abs(shares),
            price_per_share=abs(price),
            currency=currency or "CHF",
            fx_rate_to_chf=round(fx_rate, 6),
            fees_chf=abs(fees) * (fx_rate if currency != "CHF" else 1.0),
            taxes_chf=taxes * (fx_rate if currency != "CHF" else 1.0),
            total_chf=total_chf,
            notes=row.get("_type_raw"),
            confidence=1.0,
            order_id=row["_order_id"] or None,
            raw_symbol=symbol or None,
            gross_amount=gross_amount,
            tax_amount=tax_amount,
            import_source="swissquote_csv",
            import_batch_id=batch_id,
            is_aggregated=row["_is_aggregated"],
            aggregated_count=row["_aggregated_count"],
            fx_source=fx_source,
        )
        parsed.append(txn)

        # Track transactions needing yfinance historical fallback
        if fx_source == "yfinance_pending":
            _yf_fallback_needed.append((len(parsed) - 1, row["_date"].date().isoformat(), currency))

    # Resolve yfinance historical FX rates for transactions without forex pairs
    if _yf_fallback_needed:
        # Deduplicate by (date, currency) to minimize API calls
        unique_lookups: dict[tuple[str, str], float | None] = {}
        for _, date_str, currency in _yf_fallback_needed:
            key = (date_str, currency)
            if key not in unique_lookups:
                rate = await _get_historical_fx_rate(currency, date_str)
                unique_lookups[key] = rate

        for idx, date_str, currency in _yf_fallback_needed:
            rate = unique_lookups.get((date_str, currency))
            if rate and rate > 0:
                txn = parsed[idx]
                txn.fx_rate_to_chf = rate
                txn.fx_source = "yfinance_historical"
                # Recalculate total_chf and fees with correct rate
                net_original = abs(float(txn.total_chf / txn.fx_rate_to_chf)) if txn.fx_rate_to_chf != 0 else 0
                # We stored total_chf with the old rate; recalc from original amount
                # Find the original row data — use the net_amount we stored
                # Actually total_chf was already set with the fallback rate.
                # We need the original foreign amount. We can derive it:
                # total_chf_old = net_original * old_fx_rate, so net_original = total_chf_old / old_fx_rate
                # But old_fx_rate may have been the market rate. Safer: just recompute.
                # For buy/sell: total = shares * price + fees (in foreign), then * fx_rate
                if txn.type in ("buy", "sell") and txn.shares > 0 and txn.price_per_share > 0:
                    gross_foreign = txn.shares * txn.price_per_share
                    # fees were already converted with old rate; revert and reconvert
                    old_fx = _fx_cache.get(currency, 1.0)
                    if old_fx > 0:
                        fees_foreign = txn.fees_chf / old_fx
                    else:
                        fees_foreign = 0
                    txn.fees_chf = round(fees_foreign * rate, 2)
                    txn.total_chf = round((gross_foreign + fees_foreign) * rate, 2)
            else:
                # Keep current market rate but mark source
                parsed[idx].fx_source = "market_fallback"

    # Enrich: match to existing positions, detect duplicates
    parsed, new_positions = await enrich_transactions(parsed, db, user_id=user_id)

    # Count aggregated
    agg_count = sum(1 for t in parsed if getattr(t, "is_aggregated", False))

    # Build broker metadata (generic format)
    broker_meta = {
        "broker": "swissquote",
        "aggregated_count": agg_count,
        "skipped": {
            "bonds": len(skipped_bonds),
        },
        "skipped_bonds": skipped_bonds,
        "fx_pairs": fx_pairs,
        "fx_pairs_count": len(fx_pairs),
        "batch_id": batch_id,
    }

    # Add bond warning
    if skipped_bonds:
        warnings.insert(0, f"{len(skipped_bonds)} Anleihen-Transaktionen übersprungen (Bonds werden nicht unterstützt)")

    # Check for unmapped symbols
    for t in parsed:
        if t.type in ("buy", "sell") and t.ticker and not t.is_new_position and not t.position_id:
            warnings.append(f"Symbol {t.raw_symbol or t.ticker} konnte nicht zugeordnet werden — bitte manuell zuweisen")

    return ImportPreview(
        source_type="swissquote_csv",
        filename=filename,
        total_rows=len(parsed),
        transactions=parsed,
        new_positions=new_positions,
        warnings=warnings,
        broker_meta=broker_meta,
    )
