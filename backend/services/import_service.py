import csv
import io
import logging
import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.position import AssetType, Position, PriceSource
from models.transaction import Transaction, TransactionType

logger = logging.getLogger(__name__)


# --- Data structures ---

class ParsedTransaction(BaseModel):
    row_index: int = 0
    type: str = "buy"
    date: str = ""  # ISO date string
    ticker: Optional[str] = None
    isin: Optional[str] = None
    name: Optional[str] = None
    shares: float = 0
    price_per_share: float = 0
    currency: str = "CHF"
    fx_rate_to_chf: float = 1.0
    fees_chf: float = 0
    taxes_chf: float = 0
    total_chf: float = 0
    notes: Optional[str] = None
    position_id: Optional[str] = None
    is_new_position: bool = False
    suggested_asset_type: Optional[str] = None
    suggested_yfinance_ticker: Optional[str] = None
    confidence: float = 1.0
    warnings: list[str] = []
    is_duplicate: bool = False
    # Swissquote import fields
    order_id: Optional[str] = None
    raw_symbol: Optional[str] = None
    gross_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    import_source: Optional[str] = None
    import_batch_id: Optional[str] = None
    is_aggregated: bool = False
    aggregated_count: int = 1
    fx_source: Optional[str] = None  # "swissquote_forex", "yfinance_historical", "csv_derived", None


class ImportPreview(BaseModel):
    source_type: str
    filename: str
    total_rows: int
    transactions: list[ParsedTransaction]
    new_positions: list[dict] = []
    warnings: list[str] = []
    csv_mapping: Optional[dict] = None
    broker_meta: Optional[dict] = None


# --- Column aliases for CSV ---

COLUMN_ALIASES = {
    "date": ["date", "datum", "trade date", "valuta", "buchungsdatum", "trade_date"],
    "type": ["type", "typ", "art", "aktion", "transaction type"],
    "ticker": ["ticker", "symbol", "instrument", "wertpapier"],
    "isin": ["isin"],
    "name": ["name", "bezeichnung", "description", "security", "title"],
    "shares": ["shares", "quantity", "stück", "stueck", "anzahl", "menge", "units"],
    "price_per_share": ["price", "preis", "kurs", "unit price", "price_per_share", "unit_price"],
    "currency": ["currency", "währung", "waehrung", "ccy"],
    "fees_chf": ["fees", "gebühren", "gebuehren", "commission", "courtage", "fees_chf"],
    "taxes_chf": ["taxes", "steuern", "tax", "stamp duty", "taxes_chf"],
    "total_chf": ["total", "amount", "betrag", "nettobetrag", "total_chf", "net amount"],
    "fx_rate_to_chf": ["fx", "exchange rate", "wechselkurs", "fx_rate", "fx_rate_to_chf"],
    "notes": ["notes", "notizen", "bemerkung", "comment", "remarks"],
}

TYPE_ALIASES = {
    "buy": ["buy", "kauf", "purchase", "bought"],
    "sell": ["sell", "verkauf", "sale", "sold"],
    "dividend": ["dividend", "dividende", "ausschüttung", "distribution"],
    "fee": ["fee", "gebühr", "gebuehr", "depotgebühr", "custody fee"],
    "tax": ["tax", "steuer", "verrechnungssteuer", "withholding tax"],
    "tax_refund": ["tax refund", "steuerrückerstattung", "tax_refund"],
    "delivery_in": ["delivery in", "einlieferung", "delivery_in", "transfer in"],
    "delivery_out": ["delivery out", "auslieferung", "delivery_out", "transfer out"],
    "deposit": ["deposit", "einzahlung"],
    "withdrawal": ["withdrawal", "auszahlung"],
    "capital_gain": ["capital_gain", "kapitalgewinn", "capital gain"],
    "interest": ["interest", "zins", "zinsen"],
    "fx_credit": ["fx_credit", "forex-gutschrift", "fx-gutschrift"],
    "fx_debit": ["fx_debit", "forex-belastung", "fx-belastung"],
    "fee_correction": ["fee_correction", "gebührenkorrektur", "berichtigung"],
}


# --- CSV Parsing ---

async def parse_csv(file_bytes: bytes, filename: str, db: AsyncSession, user_mapping: dict | None = None, user_id: uuid.UUID | None = None, type_mapping: dict | None = None, broker_defaults: dict | None = None, total_chf_formula: str = "standard") -> ImportPreview:
    """Parse CSV file with auto-detection of encoding, delimiter, and columns."""
    warnings = []

    # Detect encoding
    text = None
    for encoding in ["utf-8", "latin-1", "cp1252"]:
        try:
            text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            logger.debug(f"CSV encoding {encoding} failed, trying next")
            continue

    if text is None:
        raise ValueError("Konnte Datei-Encoding nicht erkennen")

    # Detect delimiter
    try:
        dialect = csv.Sniffer().sniff(text[:4000])
        delimiter = dialect.delimiter
    except csv.Error as e:
        logger.debug(f"CSV sniffer failed, falling back to delimiter heuristic: {e}")
        delimiter = "," if text.count(",") > text.count(";") else ";"

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise ValueError("CSV enthält keine Spaltenüberschriften")

    # Auto-detect native broker formats (order: Swissquote → IBKR → generic)
    from services.swissquote_parser import is_swissquote_csv
    if is_swissquote_csv(reader.fieldnames) and not user_mapping:
        from services.swissquote_parser import parse_swissquote_csv
        return await parse_swissquote_csv(text, filename, db, user_id=user_id)

    from services.ibkr_parser import detect_ibkr
    if detect_ibkr(reader.fieldnames) and not user_mapping:
        from services.ibkr_parser import parse_ibkr_csv
        return await parse_ibkr_csv(text, filename, db, user_id=user_id)

    from services.pocket_parser import detect_pocket
    if detect_pocket(reader.fieldnames) and not user_mapping:
        from services.pocket_parser import parse_pocket_csv
        return await parse_pocket_csv(text, filename, db, user_id=user_id)

    # Map columns
    if user_mapping:
        mapping = user_mapping
    else:
        mapping = _auto_detect_mapping(reader.fieldnames)

    rows = list(reader)
    if not rows:
        raise ValueError("CSV enthält keine Datenzeilen")

    parsed = []
    for i, row in enumerate(rows):
        try:
            txn = _parse_csv_row(i, row, mapping, type_mapping=type_mapping, broker_defaults=broker_defaults, total_chf_formula=total_chf_formula)
            if txn:
                parsed.append(txn)
        except Exception as e:
            warnings.append(f"Zeile {i + 2}: {e}")

    parsed, new_positions = await enrich_transactions(parsed, db, user_id=user_id)

    return ImportPreview(
        source_type="csv",
        filename=filename,
        total_rows=len(parsed),
        transactions=parsed,
        new_positions=new_positions,
        warnings=warnings,
        csv_mapping=mapping,
    )


def _auto_detect_mapping(fieldnames: list[str]) -> dict:
    """Map CSV column names to our fields using fuzzy alias matching."""
    mapping = {}
    normalized = {name: name.strip().lower() for name in fieldnames}

    for field, aliases in COLUMN_ALIASES.items():
        for col_name, norm_name in normalized.items():
            if norm_name in aliases:
                mapping[field] = col_name
                break

    return mapping


def _normalize_type(raw_type: str) -> str:
    """Map raw type string to TransactionType value."""
    raw = raw_type.strip().lower()
    for canonical, aliases in TYPE_ALIASES.items():
        if raw in aliases:
            return canonical
    return raw


def _parse_csv_row(index: int, row: dict, mapping: dict, type_mapping: dict | None = None, broker_defaults: dict | None = None, total_chf_formula: str = "standard") -> ParsedTransaction | None:
    """Parse a single CSV row into a ParsedTransaction."""
    def get(field: str, default=""):
        col = mapping.get(field)
        if col and col in row:
            return row[col].strip() if row[col] else default
        return default

    date_str = get("date")
    if not date_str:
        return None

    # Try common date formats
    parsed_date = None
    for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"]:
        try:
            parsed_date = datetime.strptime(date_str, fmt).date()
            break
        except ValueError:
            continue  # Expected: trying multiple date formats

    if not parsed_date:
        raise ValueError(f"Unbekanntes Datumsformat: {date_str}")

    # Type mapping: check custom mapping first, then fall back to aliases
    raw_type = get("type", "buy")
    if type_mapping and raw_type in type_mapping:
        txn_type = type_mapping[raw_type]
    elif raw_type:
        txn_type = _normalize_type(raw_type)
    else:
        txn_type = "buy"

    # Skip transactions mapped to "skip"
    if txn_type == "skip":
        return None

    def parse_num(field: str, default=0) -> float:
        val = get(field, "")
        if not val:
            return default
        # Handle Swiss number format (apostrophe as thousands separator)
        val = val.replace("'", "").replace("'", "").replace(",", ".")
        try:
            return float(val)
        except ValueError:
            logger.debug(f"Could not parse numeric value: {val!r}, using default {default}")
            return default

    # Apply broker defaults
    ticker = get("ticker") or (broker_defaults or {}).get("ticker") or None

    # Calculate total_chf based on formula
    if total_chf_formula == "net_amount_plus_fees":
        total_chf = parse_num("total_chf") + parse_num("fees_chf")
    else:
        total_chf = parse_num("total_chf")

    # Set suggested_asset_type from defaults
    suggested_type = (broker_defaults or {}).get("asset_class")

    return ParsedTransaction(
        row_index=index,
        type=txn_type,
        date=parsed_date.isoformat(),
        ticker=ticker,
        isin=get("isin") or None,
        name=get("name") or None,
        shares=parse_num("shares"),
        price_per_share=parse_num("price_per_share"),
        currency=get("currency", "CHF") or "CHF",
        fx_rate_to_chf=(broker_defaults or {}).get("fx_rate") or parse_num("fx_rate_to_chf", 1.0),
        fees_chf=parse_num("fees_chf"),
        taxes_chf=parse_num("taxes_chf"),
        total_chf=total_chf,
        notes=get("notes") or None,
        suggested_asset_type=suggested_type,
        confidence=1.0,
        order_id=get("order_id") or None,
    )


# --- Enrichment ---

async def enrich_transactions(
    txns: list[ParsedTransaction], db: AsyncSession, user_id: uuid.UUID | None = None
) -> tuple[list[ParsedTransaction], list[dict]]:
    """Match transactions to existing positions, resolve ISINs, flag new positions."""

    # Load positions (scoped to user if provided)
    query = select(Position)
    if user_id is not None:
        query = query.where(Position.user_id == user_id)
    result = await db.execute(query)
    positions = result.scalars().all()

    # SQL EXISTS-based duplicate detection (avoids loading all transactions)
    from sqlalchemy import exists, and_, func

    def _to_date(d: str | date) -> date:
        return date.fromisoformat(d) if isinstance(d, str) else d

    async def _check_exact_dup(pos_id: str, txn_date: str, txn_type: str, total: float) -> bool:
        d = _to_date(txn_date)
        t = TransactionType(txn_type)
        conditions = [
            Transaction.position_id == pos_id,
            Transaction.date == d,
            Transaction.type == t,
            func.round(Transaction.total_chf, 2) == round(total, 2),
        ]
        if user_id is not None:
            conditions.insert(0, Transaction.user_id == user_id)
        stmt = select(exists().where(and_(*conditions)))
        result = await db.execute(stmt)
        return result.scalar()

    async def _check_partial_dup(pos_id: str, txn_date: str, txn_type: str) -> bool:
        d = _to_date(txn_date)
        t = TransactionType(txn_type)
        conditions = [
            Transaction.position_id == pos_id,
            Transaction.date == d,
            Transaction.type == t,
        ]
        if user_id is not None:
            conditions.insert(0, Transaction.user_id == user_id)
        stmt = select(exists().where(and_(*conditions)))
        result = await db.execute(stmt)
        return result.scalar()

    async def _check_order_id_dup(order_id: str, txn_type: str) -> bool:
        t = TransactionType(txn_type)
        conditions = [
            Transaction.order_id == order_id,
            Transaction.type == t,
        ]
        if user_id is not None:
            conditions.insert(0, Transaction.user_id == user_id)
        stmt = select(exists().where(and_(*conditions)))
        result = await db.execute(stmt)
        return result.scalar()

    ticker_map = {p.ticker.upper(): p for p in positions}
    isin_map = {p.isin.upper(): p for p in positions if p.isin}

    new_positions_map: dict[str, dict] = {}  # key -> position info

    for txn in txns:
        # Skip non-security types
        if txn.type in ("deposit", "withdrawal", "fee") and not txn.ticker and not txn.isin:
            continue

        matched_pos = None

        # Try matching by ISIN
        if txn.isin:
            matched_pos = isin_map.get(txn.isin.upper())

        # Try matching by ticker
        if not matched_pos and txn.ticker:
            ticker_upper = txn.ticker.upper()
            matched_pos = ticker_map.get(ticker_upper)
            # Try with exchange suffixes
            if not matched_pos:
                for suffix in [".SW", ".L", ".TO"]:
                    if not ticker_upper.endswith(suffix):
                        matched_pos = ticker_map.get(ticker_upper + suffix)
                        if matched_pos:
                            txn.ticker = ticker_upper + suffix
                            break

        if matched_pos:
            txn.position_id = str(matched_pos.id)
            txn.is_new_position = False
            if not txn.ticker:
                txn.ticker = matched_pos.ticker
            # Copy asset type from existing position
            if not txn.suggested_asset_type:
                txn.suggested_asset_type = matched_pos.type.value

            # Duplicate detection — order_id based (Swissquote) or SQL EXISTS fallback
            order_id = getattr(txn, "order_id", None)
            if order_id and order_id != "00000000" and await _check_order_id_dup(order_id, txn.type):
                txn.is_duplicate = True
            else:
                if await _check_exact_dup(str(matched_pos.id), txn.date, txn.type, txn.total_chf):
                    txn.is_duplicate = True
                elif await _check_partial_dup(str(matched_pos.id), txn.date, txn.type):
                    txn.warnings = [*txn.warnings, "Ähnliche Transaktion existiert bereits (anderer Betrag)"]

        elif txn.ticker or txn.isin:
            # New position needed
            key = txn.isin or txn.ticker or ""
            txn.is_new_position = True

            if key and key not in new_positions_map:
                suggested_type = _guess_asset_type(txn)
                yf_ticker = txn.ticker
                if txn.isin and not txn.ticker:
                    # Try to resolve ISIN via yfinance (best effort)
                    yf_ticker = txn.isin

                # Map known crypto tickers to CoinGecko IDs
                CRYPTO_COINGECKO = {"BTC-USD": "bitcoin", "ETH-USD": "ethereum", "SOL-USD": "solana"}
                cg_id = CRYPTO_COINGECKO.get(txn.ticker)

                new_positions_map[key] = {
                    "key": key,
                    "ticker": txn.ticker or txn.isin or "",
                    "name": txn.name or txn.ticker or txn.isin or "",
                    "isin": txn.isin,
                    "suggested_type": suggested_type,
                    "currency": txn.currency,
                    "yfinance_ticker": yf_ticker,
                    **({"coingecko_id": cg_id, "price_source": "coingecko"} if cg_id else {}),
                }

            if not txn.suggested_asset_type:
                txn.suggested_asset_type = _guess_asset_type(txn)
            txn.suggested_yfinance_ticker = txn.ticker

    # Batch-fetch historical FX rates for non-CHF transactions with default rate 1.0
    await _enrich_fx_rates(txns)

    return txns, list(new_positions_map.values())


async def _enrich_fx_rates(txns: list[ParsedTransaction]) -> None:
    """Batch-fetch historical FX rates for foreign currency transactions missing a real rate."""
    import asyncio
    from datetime import timedelta
    from yf_patch import yf_download
    import pandas as pd

    # Collect currencies that need FX lookup (non-CHF with default rate 1.0)
    currencies_needed: set[str] = set()
    for txn in txns:
        if txn.currency and txn.currency != "CHF" and txn.fx_rate_to_chf == 1.0:
            currencies_needed.add(txn.currency)

    if not currencies_needed:
        return

    # Find date range across all transactions
    dates = []
    for txn in txns:
        if txn.date and txn.currency in currencies_needed:
            try:
                dates.append(date.fromisoformat(txn.date) if isinstance(txn.date, str) else txn.date)
            except ValueError:
                pass
    if not dates:
        return

    min_date = min(dates) - timedelta(days=5)
    max_date = max(dates) + timedelta(days=5)

    # Batch download all needed FX pairs (with cross-rate fallback via USD)
    fx_data: dict[str, pd.Series] = {}
    start_str = min_date.isoformat()
    end_str = max_date.isoformat()

    async def _download_fx(pair: str) -> pd.Series | None:
        try:
            data = await asyncio.to_thread(
                yf_download, pair,
                start=start_str, end=end_str,
                progress=False, threads=False,
            )
            if data is not None and not data.empty:
                close = data["Close"]
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                series = close.dropna()
                if len(series) > 0:
                    return series
        except Exception as e:
            logger.warning(f"FX batch download failed for {pair}: {e}")
        return None

    # Cache USDCHF for cross-rate calculations
    usd_chf_series: pd.Series | None = None

    for currency in currencies_needed:
        # 1. Try direct pair (e.g. JPYCHF=X)
        series = await _download_fx(f"{currency}CHF=X")
        if series is not None:
            fx_data[currency] = series
            logger.info(f"FX batch: {currency}CHF=X loaded {len(series)} data points")
            continue

        # 2. Cross-rate via USD: CCY/USD × USD/CHF
        logger.info(f"Direct FX pair {currency}CHF=X unavailable, trying cross-rate via USD")
        ccy_usd = await _download_fx(f"{currency}USD=X")
        if ccy_usd is None:
            # Try inverse: 1 / USD/CCY
            usd_ccy = await _download_fx(f"USD{currency}=X")
            if usd_ccy is not None:
                ccy_usd = (1.0 / usd_ccy).dropna()

        if ccy_usd is not None:
            if usd_chf_series is None:
                usd_chf_series = await _download_fx("USDCHF=X")
            if usd_chf_series is not None:
                # Align on common dates and multiply
                combined = pd.DataFrame({"ccy_usd": ccy_usd, "usd_chf": usd_chf_series}).dropna()
                if len(combined) > 0:
                    cross = (combined["ccy_usd"] * combined["usd_chf"]).round(6)
                    fx_data[currency] = cross
                    logger.info(f"FX batch: {currency}→CHF via USD cross-rate, {len(cross)} data points")
                    continue

        logger.warning(f"All FX lookups failed for {currency}")

    # Apply rates to transactions
    for txn in txns:
        if txn.currency not in fx_data or txn.fx_rate_to_chf != 1.0:
            continue
        try:
            d = date.fromisoformat(txn.date) if isinstance(txn.date, str) else txn.date
            series = fx_data[txn.currency]
            ts = pd.Timestamp(d)
            available = series.loc[:ts].dropna()
            if len(available) > 0:
                rate = round(float(available.iloc[-1]), 6)
                txn.fx_rate_to_chf = rate
                # Recalculate total_chf if it was based on the default rate
                if txn.shares > 0 and txn.price_per_share > 0:
                    txn.total_chf = round(abs(txn.shares * txn.price_per_share) * rate + txn.fees_chf, 2)
        except Exception as e:
            logger.debug(f"FX lookup failed for {txn.currency} on {txn.date}: {e}")


def _guess_asset_type(txn: ParsedTransaction) -> str:
    """Guess asset type from ticker/name patterns."""
    # 1. Already set by broker defaults
    if txn.suggested_asset_type:
        return txn.suggested_asset_type

    # 2. Transaction type based
    if txn.type in ("deposit", "withdrawal"):
        return "cash"
    if txn.type in ("fx_credit", "fx_debit"):
        return "cash"

    name = (txn.name or "").lower()
    ticker = (txn.ticker or "").upper()

    # 3. Crypto detection
    crypto_tickers = {"BTC", "ETH", "SOL", "ADA", "DOT", "AVAX", "MATIC", "LINK", "UNI", "DOGE", "XRP", "LTC"}
    if any(ticker.startswith(ct + "-") or ticker == ct for ct in crypto_tickers):
        return "crypto"
    if any(kw in name for kw in ["bitcoin", "ethereum", "crypto"]):
        return "crypto"

    # 4. Commodity detection
    commodity_tickers = {"GC=F", "SI=F", "XAUCHF=X", "XAGCHF=X"}
    if ticker in commodity_tickers:
        return "commodity"
    commodity_keywords = ["gold", "silber", "silver", "palladium", "platinum"]
    stock_indicators = [
        "mining", "minen", "corp", "inc", "ag", "ltd", "plc", "group",
        "resources", "holdings", "capital", "partners",
    ]
    if any(kw in name for kw in commodity_keywords):
        if not any(ind in name for ind in stock_indicators):
            return "commodity"

    # 5. ETF detection
    etf_keywords = ["etf", "ishares", "vanguard", "spdr", "xtrackers", "wisdomtree", "amundi", "lyxor"]
    if any(kw in name for kw in etf_keywords):
        return "etf"

    return "stock"


# --- Confirm Import ---

async def confirm_import(
    transactions: list[dict],
    new_positions: list[dict],
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    fx_transactions: list[dict] | None = None,
) -> dict:
    """Create new positions and bulk-insert transactions."""

    created_positions = 0
    created_transactions = 0
    position_id_map: dict[str, uuid.UUID] = {}  # key -> new position UUID

    # 1. Create new positions
    for np in new_positions:
        try:
            asset_type = AssetType(np.get("suggested_type", "stock"))
        except ValueError:
            logger.debug(f"Unknown asset type {np.get('suggested_type')!r}, defaulting to stock")
            asset_type = AssetType.stock

        try:
            ps = PriceSource(np.get("price_source", "yahoo"))
        except ValueError:
            logger.debug(f"Unknown price source {np.get('price_source')!r}, defaulting to yahoo")
            ps = PriceSource.yahoo

        pos_kwargs = dict(
            ticker=np["ticker"],
            name=np["name"],
            type=asset_type,
            currency=np.get("currency", "CHF"),
            isin=np.get("isin"),
            yfinance_ticker=np.get("yfinance_ticker") or np["ticker"],
            coingecko_id=np.get("coingecko_id"),
            price_source=ps,
            shares=0,
            cost_basis_chf=0,
        )
        if user_id is not None:
            pos_kwargs["user_id"] = user_id
        pos = Position(**pos_kwargs)
        db.add(pos)
        await db.flush()  # Get the ID

        key = np.get("key", np["ticker"])
        position_id_map[key] = pos.id
        created_positions += 1

    # Reload positions for matching (scoped to user)
    pos_query = select(Position)
    if user_id is not None:
        pos_query = pos_query.where(Position.user_id == user_id)
    result = await db.execute(pos_query)
    all_positions = {str(p.id): p for p in result.scalars().all()}

    # 2. Insert transactions (skip duplicates unless overridden)
    for txn_data in transactions:
        if txn_data.get("is_duplicate") and not txn_data.get("force_import"):
            continue

        pos_id = txn_data.get("position_id")

        # Resolve new positions
        if not pos_id and txn_data.get("is_new_position"):
            key = txn_data.get("isin") or txn_data.get("ticker") or ""
            new_id = position_id_map.get(key)
            if new_id:
                pos_id = str(new_id)

        if not pos_id:
            continue

        try:
            txn_type = TransactionType(txn_data["type"])
        except (ValueError, KeyError) as e:
            logger.debug(f"Skipping transaction with invalid type {txn_data.get('type')!r}: {e}")
            continue

        try:
            txn_date = date.fromisoformat(txn_data["date"])
        except (ValueError, KeyError) as e:
            logger.debug(f"Skipping transaction with invalid date {txn_data.get('date')!r}: {e}")
            continue

        # Resolve user_id from the position
        pos = all_positions.get(pos_id)
        txn_user_id = pos.user_id if pos else user_id

        # Ensure total_chf is derived from fx_rate_to_chf (not an independent FX lookup)
        shares = float(txn_data.get("shares", 0))
        price_per_share = float(txn_data.get("price_per_share", 0))
        currency = txn_data.get("currency", "CHF")
        fx_rate = float(txn_data.get("fx_rate_to_chf", 1.0))
        fees_chf = float(txn_data.get("fees_chf", 0))
        taxes_chf = float(txn_data.get("taxes_chf", 0))
        total_chf = float(txn_data.get("total_chf", 0))

        if currency != "CHF" and fx_rate > 0 and fx_rate != 1.0 and shares > 0 and price_per_share > 0:
            total_chf = round(abs(shares * price_per_share) * fx_rate + fees_chf, 2)
        elif currency != "CHF" and fx_rate > 0 and fx_rate != 1.0 and txn_type in (TransactionType.dividend, TransactionType.capital_gain):
            # For dividends: shares=0, use gross_amount/tax_amount for CHF conversion
            gross = float(txn_data.get("gross_amount", 0))
            tax = float(txn_data.get("tax_amount", 0))
            if gross > 0:
                total_chf = round((gross - tax) * fx_rate, 2) if tax else round(gross * fx_rate, 2)
            elif total_chf > 0:
                # total_chf might still be in foreign currency — convert it
                total_chf = round(total_chf * fx_rate, 2)

        txn = Transaction(
            position_id=uuid.UUID(pos_id),
            user_id=txn_user_id,
            type=txn_type,
            date=txn_date,
            shares=shares,
            price_per_share=price_per_share,
            currency=currency,
            fx_rate_to_chf=fx_rate,
            fees_chf=fees_chf,
            taxes_chf=taxes_chf,
            total_chf=total_chf,
            notes=txn_data.get("notes"),
            order_id=txn_data.get("order_id"),
            isin=txn_data.get("isin"),
            import_source=txn_data.get("import_source"),
            import_batch_id=txn_data.get("import_batch_id"),
            raw_symbol=txn_data.get("raw_symbol"),
            gross_amount=txn_data.get("gross_amount"),
            tax_amount=txn_data.get("tax_amount"),
        )
        db.add(txn)

        # Update position shares/cost_basis
        pos = all_positions.get(pos_id)
        if pos:
            if txn_type in (TransactionType.buy, TransactionType.delivery_in):
                pos.shares = float(pos.shares) + float(txn.shares)
                pos.cost_basis_chf = float(pos.cost_basis_chf) + float(txn.total_chf)
            elif txn_type in (TransactionType.sell, TransactionType.delivery_out):
                old_shares = float(pos.shares)
                pos.shares = max(0, old_shares - float(txn.shares))
                if old_shares > 0:
                    sell_ratio = float(txn.shares) / old_shares
                    pos.cost_basis_chf = float(pos.cost_basis_chf) * (1 - sell_ratio)

        created_transactions += 1

    # 3. Persist FX transactions if provided
    created_fx = 0
    if fx_transactions and user_id:
        from models.fx_transaction import FxTransaction
        for fx in fx_transactions:
            try:
                fx_date = date.fromisoformat(fx["date"]) if isinstance(fx.get("date"), str) else fx.get("date")
                if not fx_date:
                    continue
                fx_txn = FxTransaction(
                    user_id=user_id,
                    date=fx_date,
                    order_id=fx.get("order_id"),
                    currency_from=fx["currency_from"],
                    currency_to=fx["currency_to"],
                    amount_from=float(fx["amount_from"]),
                    amount_to=float(fx["amount_to"]),
                    derived_rate=float(fx["rate"]),
                    import_batch_id=fx.get("import_batch_id"),
                )
                db.add(fx_txn)
                created_fx += 1
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"Skipping FX transaction: {e}")
                continue

    await db.commit()

    # 4. Auto-assign industry/sector for new positions (best-effort, non-blocking)
    if created_positions > 0:
        positions_to_enrich = [all_positions[str(pid)] for pid in position_id_map.values() if str(pid) in all_positions]
        await _auto_assign_industries(db, positions_to_enrich)

    return {
        "created_transactions": created_transactions,
        "created_positions": created_positions,
        "created_fx_transactions": created_fx,
    }


async def _auto_assign_industries(db: AsyncSession, positions: list[Position]) -> None:
    """Auto-assign industry and sector for positions via yfinance (best-effort)."""
    import asyncio
    import yfinance as yf
    from services.sector_mapping import INDUSTRY_TO_SECTOR

    # Fixed mappings for non-stock types
    TYPE_DEFAULTS = {
        AssetType.crypto: ("Cryptocurrency", "Crypto"),
        AssetType.commodity: ("Precious Metals", "Commodities"),
    }

    needs_lookup = []
    for pos in positions:
        if pos.industry:
            continue
        defaults = TYPE_DEFAULTS.get(pos.type)
        if defaults:
            pos.industry, pos.sector = defaults
            continue
        if pos.type in (AssetType.cash, AssetType.pension, AssetType.real_estate):
            continue
        needs_lookup.append(pos)

    # Lookup via yfinance (sequential with delay to avoid rate limiting)
    for i, pos in enumerate(needs_lookup):
        if i > 0:
            await asyncio.sleep(0.5)
        try:
            ticker_str = pos.yfinance_ticker or pos.ticker
            info = await asyncio.to_thread(lambda t=ticker_str: yf.Ticker(t).info)
            industry = info.get("industry", "")
            sector = info.get("sector", "")

            if industry:
                pos.industry = industry
                # Use FINVIZ mapping if available, otherwise yfinance sector
                pos.sector = INDUSTRY_TO_SECTOR.get(industry, sector or None)
            elif pos.type == AssetType.etf or pos.is_etf:
                pos.industry = "Exchange Traded Fund"
                pos.sector = "Multi-Sector"

            logger.info(f"Auto-assigned {pos.ticker}: industry={pos.industry}, sector={pos.sector}")
        except Exception as e:
            logger.warning(f"Auto-assign industry failed for {pos.ticker}: {e}")

    if needs_lookup:
        await db.commit()
