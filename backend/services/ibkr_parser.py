"""Interactive Brokers (IBKR) Flex Query CSV parser.

Handles UTF-8 encoding, comma delimiters, partial execution aggregation,
exchange-based symbol mapping, and asset class filtering.
"""

import csv
import io
import logging
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from services.import_service import ImportPreview, ParsedTransaction, enrich_transactions

logger = logging.getLogger(__name__)

# IBKR ListingExchange → yfinance suffix
EXCHANGE_SUFFIX_MAP: dict[str, str] = {
    # US Exchanges — no suffix
    "NYSE": "",
    "NASDAQ": "",
    "ARCA": "",
    "AMEX": "",
    "BATS": "",
    "IEX": "",
    "PINK": "",
    # Europe
    "SWX": ".SW",
    "EBS": ".SW",
    "VIRTX": ".SW",
    "LSE": ".L",
    "AEB": ".AS",
    "SBF": ".PA",
    "IBIS": ".DE",
    "FWB": ".F",
    "VSE": ".VI",
    "BM": ".MC",
    "MIL": ".MI",
    # Americas
    "TSE": ".TO",
    # Asia-Pacific
    "TSEJ": ".T",
    "ASX": ".AX",
    "SEHK": ".HK",
    "SGX": ".SI",
}

# ISIN prefix → yfinance suffix (fallback when ListingExchange is missing)
ISIN_SUFFIX_MAP: dict[str, str] = {
    "CH": ".SW",
    "IE": ".L",
    "LU": ".L",
    "GB": ".L",
    "US": "",
    "CA": ".TO",
    "DE": ".DE",
    "FR": ".PA",
    "NL": ".AS",
    "AT": ".VI",
    "ES": ".MC",
    "IT": ".MI",
    "JP": ".T",
    "AU": ".AX",
    "HK": ".HK",
    "SG": ".SI",
}

# Asset classes to import
IMPORTABLE_ASSET_CLASSES = {"STK", "ETF"}

# Asset classes to skip (with user-visible category names)
SKIP_ASSET_CLASSES: dict[str, str] = {
    "CASH": "forex",
    "OPT": "options",
    "FUT": "futures",
    "BOND": "bonds",
    "WAR": "warrants",
    "CFD": "cfd",
}

# Transaction types to import
IMPORTABLE_TXN_TYPES = {"ExchTrade", "FracShare"}


def detect_ibkr(fieldnames: list[str]) -> bool:
    """Detect if CSV headers match an IBKR Flex Query export format.

    Recognises two formats:
    - Trades section (Buy/Sell, IBCommission, TradePrice/TradeMoney)
    - Cash Transactions section (Dividends, Withholding Tax) — distinguished
      by the combination ClientAccountID + FXRateToBase + Amount + Type
    """
    if not fieldnames:
        return False
    headers = {f.strip() for f in fieldnames}

    trade_checks = [
        # 1. Core IBKR trade columns
        {"Symbol", "AssetClass", "Buy/Sell"}.issubset(headers),
        # 2. IBKR-specific commission columns
        "IBCommission" in headers or "IBCommissionCurrency" in headers,
        # 3. Trade price/money columns
        {"TradePrice", "TradeMoney"}.issubset(headers),
    ]
    if sum(trade_checks) >= 2:
        return True

    # Cash Transactions / Dividends Flex Query
    cash_format = {
        "ClientAccountID",
        "FXRateToBase",
        "CurrencyPrimary",
        "Amount",
        "Type",
    }.issubset(headers)
    return cash_format


def _parse_date(val: str) -> datetime | None:
    """Parse IBKR date formats: YYYYMMDD or YYYY-MM-DD."""
    val = val.strip()
    for fmt in ["%Y%m%d", "%Y-%m-%d"]:
        try:
            return datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def _parse_num(val: str) -> float:
    """Parse a numeric value from IBKR CSV."""
    val = val.strip()
    if not val:
        return 0.0
    try:
        return float(val)
    except ValueError:
        logger.debug(f"Could not parse numeric value: {val!r}, returning 0.0")
        return 0.0


def _map_ticker(symbol: str, isin: str, listing_exchange: str) -> str:
    """Map IBKR symbol to yfinance ticker using exchange and ISIN fallback.

    Priority:
    1. ListingExchange → EXCHANGE_SUFFIX_MAP
    2. ISIN prefix → ISIN_SUFFIX_MAP
    3. Symbol unchanged (assumed US)
    """
    if not symbol:
        return ""
    symbol = symbol.strip()

    # 1. Exchange-based mapping
    exchange = listing_exchange.strip().upper() if listing_exchange else ""
    if exchange and exchange in EXCHANGE_SUFFIX_MAP:
        suffix = EXCHANGE_SUFFIX_MAP[exchange]
        if suffix and not symbol.endswith(suffix):
            return symbol + suffix
        return symbol

    # 2. ISIN-based fallback
    if isin and len(isin) >= 2:
        prefix = isin[:2].upper()
        suffix = ISIN_SUFFIX_MAP.get(prefix, "")
        if suffix and not symbol.endswith(suffix):
            return symbol + suffix
        return symbol

    # 3. No mapping — assume US
    return symbol


def _is_section_header(first_val: str, trade_header: str) -> bool:
    """Detect if a CSV line is a section header (not trade data).

    IBKR Flex Queries can have multiple sections. The trade section comes first,
    then a new section (e.g. FX rates) starts with its own header row.
    Section headers are identified by having non-numeric, non-date first values
    that look like column names.
    """
    if not first_val:
        return False
    # Trade data rows start with a currency code (3 uppercase letters) in CurrencyPrimary,
    # or a date (digits). Section headers contain words like "Date/Time", "Header", etc.
    val = first_val.strip().strip('"')
    # Known section header indicators
    section_indicators = {"Date/Time", "Header", "DataDiscriminator", "ClientAccountID"}
    if val in section_indicators:
        return True
    # If value contains "/" and is not a number, likely a header like "Date/Time"
    if "/" in val and not val.replace("/", "").replace("-", "").isdigit():
        return True
    return False


def _is_forex_symbol(symbol: str) -> bool:
    """Check if symbol looks like a forex pair (e.g. EUR.USD)."""
    if not symbol:
        return False
    parts = symbol.strip().split(".")
    return len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3 and parts[0].isalpha() and parts[1].isalpha()


def _aggregate_partials(rows: list[dict]) -> list[dict]:
    """Aggregate partial executions: same TradeDate + Symbol + Buy/Sell.

    Weighted average price, summed quantities/fees/taxes.
    """
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = (row["_date_str"], row["_symbol"], row["_direction"])
        groups[key].append(row)

    result = []
    for key, group in groups.items():
        if len(group) == 1:
            result.append(group[0])
            continue

        total_qty = sum(r["_quantity"] for r in group)
        total_value = sum(r["_quantity"] * r["_price"] for r in group)
        weighted_price = total_value / total_qty if total_qty != 0 else 0
        total_fees = sum(r["_fees"] for r in group)
        total_taxes = sum(r["_taxes"] for r in group)

        merged = dict(group[0])
        merged["_quantity"] = total_qty
        merged["_price"] = weighted_price
        merged["_fees"] = total_fees
        merged["_taxes"] = total_taxes
        merged["_is_aggregated"] = True
        merged["_aggregated_count"] = len(group)
        result.append(merged)

    return result


async def parse_ibkr_csv(
    text: str, filename: str, db: AsyncSession, user_id: uuid.UUID | None = None
) -> ImportPreview:
    """Parse an IBKR Flex Query CSV export into ImportPreview.

    Dispatches based on the header row:
    - Trades Flex Query → ``_parse_ibkr_trades``
    - Cash Transactions / Dividends Flex Query → ``_parse_ibkr_cash``
    """
    stripped_text = text.strip()
    if not stripped_text:
        raise ValueError("CSV enthält keine Daten")

    first_line = stripped_text.splitlines()[0]
    try:
        first_fields = next(csv.reader(io.StringIO(first_line)))
    except (StopIteration, csv.Error) as e:
        raise ValueError("CSV enthält keine Spaltenüberschriften") from e

    headers_set = {f.strip() for f in first_fields}

    if "Buy/Sell" in headers_set:
        return await _parse_ibkr_trades(text, filename, db, user_id)
    if {"ClientAccountID", "Amount", "Type", "FXRateToBase"}.issubset(headers_set):
        return await _parse_ibkr_cash(text, filename, db, user_id)

    raise ValueError(
        "Unbekanntes IBKR Flex Query Format — weder Trades noch Cash Transactions erkannt"
    )


async def _parse_ibkr_trades(
    text: str, filename: str, db: AsyncSession, user_id: uuid.UUID | None = None
) -> ImportPreview:
    """Parse an IBKR Trades Flex Query CSV export into ImportPreview."""
    warnings: list[str] = []
    skipped: dict[str, int] = defaultdict(int)
    batch_id = str(uuid.uuid4())

    # IBKR Flex Queries can contain multiple sections in one CSV.
    # The trade header comes first, then a second header row starts
    # a new section (e.g. FX rates: "Date/Time","FromCurrency","ToCurrency","Rate").
    # We must skip all rows after a section break (non-trade data).
    # Strategy: read raw lines, split on section headers, only parse the trade section.
    lines = text.strip().splitlines()
    if not lines:
        raise ValueError("CSV enthält keine Daten")

    trade_header = lines[0]
    trade_lines = [trade_header]
    fx_section_rows = 0

    for line in lines[1:]:
        stripped = line.strip().strip('"')
        # Detect section break: a line whose first few values look like column headers
        # (e.g. "Date/Time","FromCurrency",...) rather than data values.
        # Heuristic: if the line doesn't start with a date (digit) or a known asset class,
        # and contains alphabetical header-like values, it's a section header.
        first_val = ""
        try:
            first_val = next(csv.reader(io.StringIO(line)))[0].strip()
        except (StopIteration, csv.Error):
            pass

        if _is_section_header(first_val, trade_header):
            fx_section_rows += 1  # count the header itself
            continue

        # If we've seen a section header, all subsequent rows belong to that section
        if fx_section_rows > 0:
            fx_section_rows += 1
            continue

        trade_lines.append(line)

    if fx_section_rows > 0:
        logger.info(f"IBKR multi-section CSV: skipped {fx_section_rows} rows from non-trade section")

    reader = csv.DictReader(io.StringIO("\n".join(trade_lines)), delimiter=",")
    if not reader.fieldnames:
        raise ValueError("CSV enthält keine Spaltenüberschriften")

    # First pass: parse and filter rows
    raw_rows: list[dict] = []
    all_dates: list[datetime] = []

    for i, row in enumerate(reader):
        asset_class = (row.get("AssetClass") or "").strip().upper()
        symbol = (row.get("Symbol") or "").strip()
        txn_type = (row.get("TransactionType") or "").strip()

        # Filter: skip non-importable asset classes
        if asset_class in SKIP_ASSET_CLASSES:
            skipped[SKIP_ASSET_CLASSES[asset_class]] += 1
            continue

        # Filter: skip forex symbols even if asset class is missing
        if _is_forex_symbol(symbol):
            skipped["forex"] += 1
            continue

        # Filter: only import STK/ETF
        if asset_class not in IMPORTABLE_ASSET_CLASSES:
            if asset_class:
                skipped[asset_class.lower()] += 1
            continue

        # Filter: only ExchTrade and FracShare transaction types
        if txn_type and txn_type not in IMPORTABLE_TXN_TYPES:
            continue

        # Parse date
        date_raw = (row.get("TradeDate") or "").strip()
        parsed_date = _parse_date(date_raw)
        if not parsed_date:
            warnings.append(f"Zeile {i + 2}: Ungültiges Datum '{date_raw}'")
            continue

        all_dates.append(parsed_date)

        direction = (row.get("Buy/Sell") or "").strip().upper()
        if direction not in ("BUY", "SELL"):
            warnings.append(f"Zeile {i + 2}: Unbekannte Richtung '{direction}'")
            continue

        quantity = abs(_parse_num(row.get("Quantity") or ""))
        price = abs(_parse_num(row.get("TradePrice") or ""))
        fees = abs(_parse_num(row.get("IBCommission") or ""))
        taxes = abs(_parse_num(row.get("Taxes") or ""))

        raw_rows.append({
            "_row": i + 2,
            "_date": parsed_date,
            "_date_str": date_raw,
            "_direction": direction,
            "_symbol": symbol,
            "_isin": (row.get("ISIN") or "").strip(),
            "_currency": (row.get("CurrencyPrimary") or "").strip(),
            "_asset_class": asset_class,
            "_quantity": quantity,
            "_price": price,
            "_fees": fees,
            "_taxes": taxes,
            "_exchange": (row.get("ListingExchange") or "").strip(),
            "_fx_rate": _parse_num(row.get("FXRateToBase") or ""),
            "_name": (row.get("Description") or "").strip(),
            "_notes": (row.get("Notes/Codes") or "").strip(),
            "_is_aggregated": False,
            "_aggregated_count": 1,
        })

    if not raw_rows:
        if fx_section_rows > 0 and sum(skipped.values()) == 0:
            raise ValueError(
                f"Die CSV enthält nur Wechselkursdaten ({fx_section_rows} Zeilen), keine Trades. "
                "Bitte exportiere eine Flex Query die den Abschnitt 'Trades' enthält."
            )
        if sum(skipped.values()) > 0:
            skip_summary = ", ".join(f"{v} {k}" for k, v in skipped.items() if v > 0)
            raise ValueError(f"Keine importierbaren Transaktionen gefunden ({skip_summary} übersprungen)")
        raise ValueError("CSV enthält keine importierbaren Transaktionen")

    # Aggregate partial executions
    aggregated_rows = _aggregate_partials(raw_rows)

    # Sort by date
    aggregated_rows.sort(key=lambda r: r["_date"])

    # Build date range
    date_range = ""
    if all_dates:
        min_date = min(all_dates)
        max_date = max(all_dates)
        date_range = f"{min_date.strftime('%d.%m.%Y')} – {max_date.strftime('%d.%m.%Y')}"

    # Convert to ParsedTransaction
    parsed: list[ParsedTransaction] = []
    for row in aggregated_rows:
        symbol = row["_symbol"]
        isin = row["_isin"]
        exchange = row["_exchange"]
        mapped_ticker = _map_ticker(symbol, isin, exchange)

        txn_type = "buy" if row["_direction"] == "BUY" else "sell"
        currency = row["_currency"] or "CHF"
        fees = row["_fees"] + row["_taxes"]
        fx_rate = row["_fx_rate"] if row["_fx_rate"] > 0 else 1.0

        # total_chf: quantity * price * fx_rate + fees
        total_foreign = row["_quantity"] * row["_price"]
        total_chf = total_foreign * fx_rate + fees * fx_rate

        txn = ParsedTransaction(
            row_index=row["_row"],
            type=txn_type,
            date=row["_date"].date().isoformat(),
            ticker=mapped_ticker,
            isin=isin or None,
            name=row["_name"] or None,
            shares=row["_quantity"],
            price_per_share=row["_price"],
            currency=currency,
            fx_rate_to_chf=round(fx_rate, 6),
            fees_chf=round(fees * fx_rate, 2),
            taxes_chf=round(row["_taxes"] * fx_rate, 2),
            total_chf=round(total_chf, 2),
            notes=row["_notes"] or None,
            confidence=1.0,
            raw_symbol=symbol or None,
            import_source="ibkr_csv",
            import_batch_id=batch_id,
            is_aggregated=row["_is_aggregated"],
            aggregated_count=row["_aggregated_count"],
        )
        parsed.append(txn)

    # Enrich: match to existing positions, detect duplicates, fetch FX rates
    parsed, new_positions = await enrich_transactions(parsed, db, user_id=user_id)

    # Count aggregated
    agg_count = sum(1 for t in parsed if getattr(t, "is_aggregated", False))

    # Build broker metadata (generic format)
    broker_meta = {
        "broker": "interactive_brokers",
        "aggregated_count": agg_count,
        "skipped": dict(skipped),
        "date_range": date_range,
        "batch_id": batch_id,
        "fx_pairs_count": 0,
    }

    # Skipped summary warning
    total_skipped = sum(skipped.values())
    if total_skipped > 0:
        parts = [f"{v} {k.capitalize()}" for k, v in skipped.items() if v > 0]
        warnings.insert(0, f"{total_skipped} Zeilen übersprungen ({', '.join(parts)})")

    return ImportPreview(
        source_type="ibkr_csv",
        filename=filename,
        total_rows=len(parsed),
        transactions=parsed,
        new_positions=new_positions,
        warnings=warnings,
        broker_meta=broker_meta,
    )


def _split_ibkr_datetime(value: str) -> str:
    """Extract the date portion from an IBKR Date/Time field.

    Accepts formats like ``YYYYMMDD;HHMMSS``, ``YYYYMMDD HHMMSS``,
    ``YYYY-MM-DD HH:MM:SS`` or just ``YYYYMMDD``.
    """
    val = (value or "").strip()
    for sep in (";", " ", "T"):
        if sep in val:
            return val.split(sep, 1)[0]
    return val


# Cash transaction types we care about
_DIVIDEND_TYPES = {"Dividends", "Payment In Lieu Of Dividends"}
_WITHHOLDING_TYPES = {"Withholding Tax"}
# Types we deliberately ignore (with user-visible category)
_CASH_SKIP_TYPES: dict[str, str] = {
    "Broker Interest Received": "interest",
    "Broker Interest Paid": "interest",
    "Deposits/Withdrawals": "cash_movement",
    "Other Fees": "fees",
    "Commission Adjustments": "fees",
}


async def _parse_ibkr_cash(
    text: str, filename: str, db: AsyncSession, user_id: uuid.UUID | None = None
) -> ImportPreview:
    """Parse an IBKR Cash Transactions / Dividends Flex Query CSV.

    Pairs ``Dividends`` rows with their matching ``Withholding Tax`` rows
    (same Symbol + Date) and emits one ``dividend`` ParsedTransaction per pair.
    Other cash transaction types (interest, deposits, fees) are skipped.
    """
    warnings: list[str] = []
    skipped: dict[str, int] = defaultdict(int)
    batch_id = str(uuid.uuid4())

    reader = csv.DictReader(io.StringIO(text), delimiter=",")
    if not reader.fieldnames:
        raise ValueError("CSV enthält keine Spaltenüberschriften")

    # Group dividend / withholding tax rows by (symbol, date)
    groups: dict[tuple[str, str], dict] = defaultdict(dict)
    all_dates: list[datetime] = []

    for i, row in enumerate(reader):
        type_val = (row.get("Type") or "").strip()
        if not type_val:
            continue

        if type_val in _CASH_SKIP_TYPES:
            skipped[_CASH_SKIP_TYPES[type_val]] += 1
            continue

        is_dividend = type_val in _DIVIDEND_TYPES
        is_withholding = type_val in _WITHHOLDING_TYPES
        if not (is_dividend or is_withholding):
            skipped[type_val.lower() or "unknown"] += 1
            continue

        symbol = (row.get("Symbol") or "").strip()
        if not symbol:
            warnings.append(f"Zeile {i + 2}: {type_val} ohne Symbol")
            continue

        date_part = _split_ibkr_datetime(row.get("Date/Time") or "")
        if not date_part:
            date_part = (row.get("SettleDate") or "").strip()

        parsed_date = _parse_date(date_part)
        if not parsed_date:
            warnings.append(f"Zeile {i + 2}: Ungültiges Datum '{date_part}'")
            continue

        all_dates.append(parsed_date)

        entry = {
            "_row": i + 2,
            "_date": parsed_date,
            "_symbol": symbol,
            "_isin": (row.get("ISIN") or "").strip(),
            "_currency": (row.get("CurrencyPrimary") or "").strip(),
            "_fx_rate": _parse_num(row.get("FXRateToBase") or ""),
            "_amount": _parse_num(row.get("Amount") or ""),
            "_description": (row.get("Description") or "").strip(),
            "_exchange": (row.get("ListingExchange") or "").strip(),
        }

        key = (symbol, parsed_date.date().isoformat())
        bucket = groups[key]
        bucket["dividend" if is_dividend else "tax"] = entry

    if not groups:
        if sum(skipped.values()) > 0:
            skip_summary = ", ".join(f"{v} {k}" for k, v in skipped.items() if v > 0)
            raise ValueError(
                f"Keine Dividenden gefunden ({skip_summary} übersprungen)"
            )
        raise ValueError("CSV enthält keine Dividenden")

    parsed: list[ParsedTransaction] = []
    orphan_tax = 0

    for (symbol, _date_str), bucket in groups.items():
        dividend = bucket.get("dividend")
        tax = bucket.get("tax")

        if not dividend:
            orphan_tax += 1
            continue

        gross = abs(dividend["_amount"])
        tax_amount = abs(tax["_amount"]) if tax else 0.0
        net_foreign = gross - tax_amount
        currency = dividend["_currency"] or "CHF"
        fx_rate = dividend["_fx_rate"] if dividend["_fx_rate"] > 0 else 1.0

        mapped_ticker = _map_ticker(symbol, dividend["_isin"], dividend["_exchange"])

        txn = ParsedTransaction(
            row_index=dividend["_row"],
            type="dividend",
            date=dividend["_date"].date().isoformat(),
            ticker=mapped_ticker,
            isin=dividend["_isin"] or None,
            name=dividend["_description"] or None,
            shares=0,
            price_per_share=0,
            currency=currency,
            fx_rate_to_chf=round(fx_rate, 6),
            fees_chf=0.0,
            taxes_chf=round(tax_amount * fx_rate, 2),
            total_chf=round(net_foreign * fx_rate, 2),
            notes=dividend["_description"] or None,
            confidence=1.0,
            raw_symbol=symbol or None,
            gross_amount=round(gross, 2),
            tax_amount=round(tax_amount, 2),
            import_source="ibkr_csv",
            import_batch_id=batch_id,
        )
        parsed.append(txn)

    if orphan_tax > 0:
        warnings.append(
            f"{orphan_tax} Quellensteuer-Zeilen ohne passende Dividende übersprungen"
        )

    parsed.sort(key=lambda t: t.date)

    parsed, new_positions = await enrich_transactions(parsed, db, user_id=user_id)

    date_range = ""
    if all_dates:
        min_date = min(all_dates)
        max_date = max(all_dates)
        date_range = f"{min_date.strftime('%d.%m.%Y')} – {max_date.strftime('%d.%m.%Y')}"

    broker_meta = {
        "broker": "interactive_brokers",
        "format": "cash_transactions",
        "dividends_count": len(parsed),
        "skipped": dict(skipped),
        "date_range": date_range,
        "batch_id": batch_id,
    }

    total_skipped = sum(skipped.values())
    if total_skipped > 0:
        parts = [f"{v} {k.capitalize()}" for k, v in skipped.items() if v > 0]
        warnings.insert(0, f"{total_skipped} Zeilen übersprungen ({', '.join(parts)})")

    return ImportPreview(
        source_type="ibkr_csv",
        filename=filename,
        total_rows=len(parsed),
        transactions=parsed,
        new_positions=new_positions,
        warnings=warnings,
        broker_meta=broker_meta,
    )
