import asyncio
import csv
import io
import itertools
import logging
import os
import re
import time
import uuid
from collections.abc import Iterable
from datetime import date, datetime
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from api.validation import check_booking_date, is_iso_currency, is_market_ticker
from constants.limits import (
    MAX_IMPORT_FX_CURRENCIES,
    MAX_IMPORT_ROWS,
    MAX_POSITIONS_PER_USER,
    MAX_TRANSACTIONS_PER_USER,
)
from models.position import AssetType, Position, PriceSource, PricingMode
from models.transaction import Transaction, TransactionType
from services import cache
from services.encryption_helpers import encrypt_field
from services.recalculate_service import LEDGER_TYPES, recalculate_position
from services.transaction_service import _sync_active_state

logger = logging.getLogger(__name__)

# Nur bei diesen Typen ist total_chf = |Stück × Kurs| × FX + Gebühren. Bei allen
# anderen (Dividende, Zins, Gebühr …) ist total_chf der gebuchte Betrag selbst.
TRADE_TYPES = frozenset({"buy", "sell", "delivery_in", "delivery_out"})

# Typen, deren Kurs von Yahoo kommt: ihr Ticker ist Teil der Abfrage.
MARKET_PRICED_TYPES = frozenset({"stock", "etf", "bond", "crypto"})

# Klassen-Aktie in Broker-Schreibweise: Symbol, ein Leerzeichen, ein Buchstabe,
# optional das Börsen-Suffix aus dem Mapping (IBKR «BRK B», «NOVO B.CO»). Yahoo
# schreibt dieselbe Aktie mit Bindestrich («BRK-B», «NOVO-B.CO»).
_CLASS_SHARE_TICKER_RE = re.compile(r"^[A-Za-z0-9]{1,6} [A-Za-z](\.[A-Za-z]{1,4})?$")


def yahoo_symbol_for(ticker: str | None) -> str | None:
    """Yahoo-Symbol zu einem Anzeige-Ticker aus einer Broker-Datei, sonst None.

    Ein gültiger Markt-Ticker gilt unverändert. Die Schreibweise einer
    Klassen-Aktie mit Leerzeichen wird übersetzt. Alles andere ist nicht
    eindeutig: die Position bekommt dann kein Yahoo-Symbol, der Nutzer setzt
    es nach dem Import.
    """
    if not ticker:
        return None
    ticker = ticker.strip()
    if is_market_ticker(ticker):
        return ticker
    if _CLASS_SHARE_TICKER_RE.fullmatch(ticker):
        return ticker.replace(" ", "-")
    return None


def ticker_warning(ticker: str) -> str:
    """Vorschau-Warnung zu einem Ticker, der kein gültiges Yahoo-Symbol ist."""
    symbol = yahoo_symbol_for(ticker)
    if symbol:
        return (
            f"Ticker «{ticker}» enthält Leer- oder Sonderzeichen; als Yahoo-Ticker wird "
            f"«{symbol}» gesetzt. Bitte nach dem Import prüfen."
        )
    return (
        f"Ticker «{ticker}» enthält Leer- oder Sonderzeichen; bitte nach dem Import "
        "den Yahoo-Ticker setzen."
    )


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
    # Betrag der BEREITS erfassten Zeile, wenn er vom Datei-Betrag abweicht —
    # macht sichtbar, dass ein Duplikat aus einem fehlerhaften Import stammt.
    duplicate_stored_total_chf: Optional[float] = None
    fx_source: Optional[str] = None  # "broker_forex", "yfinance_historical", "csv_derived", None
    # Der Betrag stammt aus einer Spalte, die ihn als CHF ausweist (eigener
    # Export: «Total CHF»). confirm_import rechnet ihn nicht nochmals um.
    total_in_chf: bool = False


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
    "total_chf": ["total", "amount", "betrag", "nettobetrag", "total_chf", "total chf", "net amount"],
    "fx_rate_to_chf": ["fx", "exchange rate", "wechselkurs", "fx_rate", "fx_rate_to_chf"],
    "notes": ["notes", "notizen", "bemerkung", "comment", "remarks"],
}

# Betragsspalten, deren Name den Betrag als CHF ausweist (eigener Export:
# «Total CHF»). Bei jeder anderen Spalte kann der Betrag in Fremdwährung stehen.
CHF_TOTAL_COLUMNS = frozenset({"total chf", "total_chf"})

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


def flag_rows_without_total(preview: "ImportPreview") -> "ImportPreview":
    """Vorschau-Warnung, wenn Handelszeilen ohne Betrag ankommen.

    Menge und Kurs da, Betrag 0 — typisch fuer eine umbenannte Betragsspalte im
    Broker-Export. ``confirm_import`` leitet den Betrag inzwischen aus Menge x
    Kurs ab; diese Warnung macht sichtbar, DASS das passiert, statt es
    stillschweigend zu tun (Feedback 30.7.2026: Bitcoin-Kaeufe ohne Betrag).
    """
    affected = sum(
        1
        for t in preview.transactions
        if t.type in ("buy", "sell")
        and t.shares > 0
        and t.price_per_share > 0
        and not t.total_chf
    )
    if affected:
        preview.warnings.insert(
            0,
            f"{affected} Zeile(n) ohne Betrag in der Datei — der Betrag wird aus "
            "Menge × Kurs berechnet. Bitte in der Vorschau gegen die Abrechnung prüfen.",
        )
    return preview


def flag_duplicates_with_other_amount(preview: "ImportPreview") -> "ImportPreview":
    """Vorschau-Warnung fuer Duplikate, deren erfasster Betrag abweicht.

    Ein erneuter Import repariert bestehende Zeilen NICHT — er ueberspringt sie
    als Duplikat. Wer nach einem fehlerhaften Import (Betrag 0) die Datei noch
    einmal einliest, sieht sonst nur "6 Duplikate" und rätselt, warum sich
    nichts aendert (Feedback 30.7.2026). Der Ausweg steht in der Meldung.
    """
    affected = [t for t in preview.transactions if t.duplicate_stored_total_chf is not None]
    if affected:
        first = affected[0]
        preview.warnings.insert(
            0,
            f"{len(affected)} Zeile(n) sind bereits erfasst, dort aber mit einem anderen "
            f"Betrag (z.B. CHF {first.duplicate_stored_total_chf:.2f} statt "
            f"CHF {first.total_chf:.2f}) — vermutlich aus einem fehlerhaften Import. "
            "Sie werden übersprungen. Zum Korrigieren die alten Zeilen in der "
            "Transaktionsliste löschen und danach neu importieren.",
        )
    return preview


_MAX_TICKER_WARNINGS = 20


def flag_tickers_without_yahoo_symbol(preview: "ImportPreview") -> "ImportPreview":
    """Vorschau-Warnung je neuer Position, deren Ticker kein Yahoo-Symbol ist.

    Der Import nimmt den Ticker an (der Nutzer kann ihn im Wizard nicht ändern),
    die Position bekommt aber erst mit einem gültigen Yahoo-Ticker einen Kurs.
    """
    affected = [
        np["ticker"]
        for np in preview.new_positions
        if np.get("suggested_type") in MARKET_PRICED_TYPES
        and np.get("ticker")
        and not is_market_ticker(np["ticker"])
    ]
    preview.warnings.extend(ticker_warning(t) for t in affected[:_MAX_TICKER_WARNINGS])
    if len(affected) > _MAX_TICKER_WARNINGS:
        preview.warnings.append(
            f"… und {len(affected) - _MAX_TICKER_WARNINGS} weitere Ticker mit Leer- oder Sonderzeichen."
        )
    return preview


def add_preview_warnings(preview: "ImportPreview") -> "ImportPreview":
    """Alle Vorschau-Pruefungen, die nach dem Parsen greifen — eine Stelle fuer
    alle Endpoints, die eine Vorschau zurueckgeben."""
    flag_rows_without_total(preview)
    flag_duplicates_with_other_amount(preview)
    flag_tickers_without_yahoo_symbol(preview)
    return preview


# --- CSV Analysis ---

UPLOAD_DIR = "/app/data/imports"

DATE_FORMATS = [
    ("%Y-%m-%dT%H:%M:%SZ", "YYYY-MM-DDTHH:MM:SSZ"),
    ("%Y-%m-%dT%H:%M:%S", "YYYY-MM-DDTHH:MM:SS"),
    ("%d-%m-%Y %H:%M:%S", "DD-MM-YYYY HH:MM:SS"),
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%d.%m.%Y", "DD.MM.YYYY"),
    ("%d/%m/%Y", "DD/MM/YYYY"),
    ("%m/%d/%Y", "MM/DD/YYYY"),
    ("%d-%m-%Y", "DD-MM-YYYY"),
    ("%Y-%m-%d %H:%M:%S", "YYYY-MM-DD HH:MM:SS"),
]


def _is_relai_csv(headers: list[str]) -> bool:
    """Detect Relai CSV by checking for key columns."""
    required = {"Date", "Transaction Type", "BTC Amount", "BTC Price", "Currency Pair", "Operation ID"}
    return required.issubset(set(headers))


# utf-8-sig zuerst: es entfernt ein BOM, das sonst am ersten Spaltennamen hängt.
# cp1252 vor latin-1: latin-1 dekodiert jede Bytefolge und käme cp1252 immer zuvor.
CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def decode_csv_bytes(content: bytes) -> tuple[str | None, str]:
    """Decode CSV bytes with the shared encoding order. Returns (text, encoding) or (None, '')."""
    for enc in CSV_ENCODINGS:
        try:
            decoded = content.decode(enc)
        except UnicodeDecodeError:
            logger.debug(f"Encoding {enc} failed for CSV detection, trying next")
            continue
        # Das BOM ist ein Detail der Datei, kein eigenes Encoding für die Anzeige.
        return decoded, "utf-8" if enc == "utf-8-sig" else enc
    return None, ""


ROW_LIMIT_ERROR = (
    f"Datei enthält mehr als {MAX_IMPORT_ROWS} Zeilen. Bitte in mehrere Dateien aufteilen."
)


def check_row_count(count: int) -> None:
    """Raise ValueError (route: 422) when count exceeds MAX_IMPORT_ROWS."""
    if count > MAX_IMPORT_ROWS:
        raise ValueError(ROW_LIMIT_ERROR)


def read_rows_limited(reader: Iterable, header_rows: int = 0) -> list:
    """Read at most MAX_IMPORT_ROWS data rows from a csv reader, else ValueError.

    islice statt list(reader): eine 10-MB-Datei mit Millionen kurzer Zeilen wird
    nach MAX_IMPORT_ROWS + 1 Zeilen abgewiesen und landet nicht ganz im Speicher.
    """
    rows = list(itertools.islice(reader, MAX_IMPORT_ROWS + header_rows + 1))
    check_row_count(len(rows) - header_rows)
    return rows


MAX_PREVIEW_WARNINGS = 200


def cap_warnings(warnings: list[str]) -> list[str]:
    """Limit the preview warnings to MAX_PREVIEW_WARNINGS entries plus a summary line."""
    if len(warnings) <= MAX_PREVIEW_WARNINGS:
        return warnings
    hidden = len(warnings) - MAX_PREVIEW_WARNINGS
    return [
        *warnings[:MAX_PREVIEW_WARNINGS],
        f"… und {hidden} weitere Warnungen (nicht angezeigt)",
    ]


def booking_date_error(d: date) -> str | None:
    """Return the error text when d is no valid booking date, else None."""
    try:
        check_booking_date(d)
    except ValueError as e:
        return str(e)
    return None


def _detect_delimiter(text: str) -> str:
    """Detect CSV delimiter via sniffer with fallback heuristic."""
    try:
        dialect = csv.Sniffer().sniff(text[:4000])
        return dialect.delimiter
    except csv.Error as e:
        logger.debug(f"CSV sniffer failed, falling back to delimiter heuristic: {e}")
        return "," if text.count(",") > text.count(";") else ";"


def _detect_broker(headers: list[str]) -> str | None:
    """Auto-detect broker from CSV headers. Returns broker name or None."""
    from services.swissquote_parser import is_swissquote_csv
    from services.ibkr_parser import detect_ibkr
    from services.pocket_parser import detect_pocket

    if is_swissquote_csv(headers):
        return "swissquote"
    if detect_ibkr(headers):
        return "interactive_brokers"
    if detect_pocket(headers):
        return "pocket"
    if _is_relai_csv(headers):
        return "relai"
    return None


def _get_broker_column_mapping(detected_broker: str | None, headers: list[str]) -> dict[str, str]:
    """Return suggested column mapping based on detected broker or auto-detection."""
    if detected_broker == "swissquote":
        return {
            "date": "Datum",
            "type": "Transaktionen",
            "ticker": "Symbol",
            "name": "Name",
            "isin": "ISIN",
            "shares": "Anzahl",
            "price_per_share": "Stückpreis",
            "fees_chf": "Kosten",
            "total_chf": "Nettobetrag",
            "currency": "Währung Nettobetrag",
            "order_id": "Auftrag #",
        }
    if detected_broker == "interactive_brokers":
        return {
            "date": "TradeDate",
            "type": "Buy/Sell",
            "ticker": "Symbol",
            "name": "Description",
            "isin": "ISIN",
            "shares": "Quantity",
            "price_per_share": "TradePrice",
            "fees_chf": "IBCommission",
            "total_chf": "TradeMoney",
            "currency": "CurrencyPrimary",
        }
    if detected_broker == "pocket":
        return {
            "date": "date",
            "type": "type",
            "shares": "value.amount",
            "price_per_share": "price.amount",
            "currency": "price.currency",
            "fees_chf": "fee.amount",
            "total_chf": "cost.amount",
            "order_id": "reference",
        }
    if detected_broker == "relai":
        return {
            "date": "Date",
            "type": "Transaction Type",
            "shares": "BTC Amount",
            "price_per_share": "BTC Price",
            "currency": "Fiat Currency",
            "fees_chf": "Fee",
            "total_chf": "Fiat Amount (excl. fees)",
            "order_id": "Operation ID",
        }
    return _auto_detect_mapping(headers)


def _get_broker_type_mapping(detected_broker: str | None, unique_types: dict[str, int]) -> dict[str, str]:
    """Return suggested type mapping based on detected broker or TYPE_ALIASES fallback."""
    if detected_broker == "swissquote":
        return {
            "Kauf": "buy", "Verkauf": "sell", "Dividende": "dividend",
            "Capital Gain": "capital_gain", "Forex-Gutschrift": "fx_credit",
            "Forex-Belastung": "fx_debit", "Fx-Gutschrift Comp.": "fx_credit",
            "Fx-Belastung Comp.": "fx_debit", "Berichtigung Börsengeb.": "fee_correction",
            "Depotgebühren": "fee", "Spesen Steuerauszug": "fee",
            "Zahlung": "deposit", "Auszahlung": "withdrawal",
            "Zinsen auf Einlagen": "interest", "Zinsen auf Belastungen": "interest",
        }
    if detected_broker == "interactive_brokers":
        return {"BUY": "buy", "SELL": "sell"}
    if detected_broker == "pocket":
        return {"exchange": "buy", "deposit": "skip", "withdrawal": "skip"}
    if detected_broker == "relai":
        return {"Buy": "buy", "Sell": "sell"}

    # Generic fallback: match unique_types against TYPE_ALIASES
    mapping: dict[str, str] = {}
    for val in unique_types:
        val_lower = val.strip().lower()
        matched = None
        for canonical, aliases in TYPE_ALIASES.items():
            if val_lower in aliases:
                matched = canonical
                break
        mapping[val] = matched or "skip"
    return mapping


def _extract_unique_types(rows_raw: list[list[str]], headers: list[str], type_col: str | None) -> dict[str, int]:
    """Extract unique values and counts from the type column."""
    unique_types: dict[str, int] = {}
    if not type_col or type_col not in headers:
        return unique_types
    type_col_idx = headers.index(type_col)
    for row in rows_raw[1:]:
        if type_col_idx < len(row):
            val = row[type_col_idx].strip()
            if val:
                unique_types[val] = unique_types.get(val, 0) + 1
    return unique_types


def _detect_date_format(sample_rows: list[list[str]], headers: list[str], date_col: str | None) -> str | None:
    """Auto-detect date format from sample data rows."""
    if not date_col or date_col not in headers:
        return None
    date_idx = headers.index(date_col)
    for row in sample_rows[:3]:
        if date_idx < len(row) and row[date_idx].strip():
            for fmt, label in DATE_FORMATS:
                try:
                    datetime.strptime(row[date_idx].strip(), fmt)
                    return label
                except ValueError:
                    continue  # Expected: trying multiple date formats
    return None


def _cleanup_old_files(dir_path: str, max_age_seconds: int = 1800) -> int:
    """Delete files in dir_path older than max_age_seconds. Returns count deleted."""
    deleted = 0
    now = time.time()
    try:
        entries = os.listdir(dir_path)
    except OSError as e:
        logger.warning(f"Upload cleanup: cannot list {dir_path}: {e}")
        return 0
    for f in entries:
        fp = os.path.join(dir_path, f)
        try:
            if os.path.isfile(fp) and now - os.path.getmtime(fp) > max_age_seconds:
                os.remove(fp)
                deleted += 1
        except OSError as e:
            logger.warning(f"Upload cleanup: failed to remove {fp}: {e}")
    return deleted


def cleanup_stale_uploads(max_age_seconds: int = 1800) -> int:
    """Delete stale raw upload CSVs across ALL user directories. Returns count deleted."""
    if not os.path.isdir(UPLOAD_DIR):
        return 0
    deleted = 0
    for entry in os.listdir(UPLOAD_DIR):
        user_dir = os.path.join(UPLOAD_DIR, entry)
        if os.path.isdir(user_dir):
            deleted += _cleanup_old_files(user_dir, max_age_seconds)
    return deleted


def _persist_upload(content: bytes, user_id: uuid.UUID) -> str:
    """Save CSV to temp storage, clean old files, return upload_id."""
    upload_id = str(uuid.uuid4())
    user_dir = os.path.join(UPLOAD_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)

    # Clean up old files (>30 min)
    _cleanup_old_files(user_dir)

    with open(os.path.join(user_dir, f"{upload_id}.csv"), "wb") as f:
        f.write(content)

    return upload_id


async def analyze_csv_structure(
    content: bytes,
    filename: str,
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict:
    """Analyze CSV structure: encoding, delimiter, headers, broker detection, column/type mapping.

    Returns a dict with all analysis results ready for the frontend wizard.
    """
    # Detect encoding
    text, detected_encoding = decode_csv_bytes(content)
    if text is None:
        raise ValueError("Encoding nicht erkennbar")

    # Detect delimiter
    delimiter = _detect_delimiter(text)

    # Read headers and sample rows
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header_row = next(reader, None)
    if header_row is None:
        raise ValueError("CSV enthält keine Daten")
    headers = [h.strip() for h in header_row]

    # Auto-detect broker
    detected_broker = _detect_broker(headers)

    data_rows: Iterable = reader
    if detected_broker == "interactive_brokers" and "Buy/Sell" in headers:
        # Trades-Datei: wie der Parser nur den ersten Abschnitt lesen und zählen.
        # Ein langer FX-Abschnitt dahinter ist legitim (ibkr_parser._read_ibkr_trades).
        from services.ibkr_parser import _is_section_header

        trade_header = delimiter.join(header_row)
        data_rows = itertools.takewhile(
            lambda row: not _is_section_header(row[0].strip() if row else "", trade_header),
            reader,
        )

    rows_raw = [header_row, *read_rows_limited(data_rows)]
    sample_rows = rows_raw[1:6]  # first 5 data rows
    row_count = len(rows_raw) - 1  # exclude header

    # Build suggested column mapping
    suggested_mapping = _get_broker_column_mapping(detected_broker, headers)

    # Extract unique type values
    type_col = suggested_mapping.get("type")
    unique_types = _extract_unique_types(rows_raw, headers, type_col)

    # Build suggested type mapping
    suggested_type_mapping = _get_broker_type_mapping(detected_broker, unique_types)

    # Auto-detect date format from sample data
    date_col = suggested_mapping.get("date")
    detected_date_format = _detect_date_format(sample_rows, headers, date_col)

    # Save file temporarily
    upload_id = _persist_upload(content, user_id)

    # Load user's saved profiles
    from models.import_profile import ImportProfile
    # Nur id und name: die Mappings der Profile braucht die Analyse nicht.
    result = await db.execute(
        select(ImportProfile.id, ImportProfile.name)
        .where(ImportProfile.user_id == user_id)
        .order_by(ImportProfile.name)
    )
    saved_profiles = [
        {"id": str(profile_id), "name": name}
        for profile_id, name in result.all()
    ]

    # Broker defaults
    broker_defaults = None
    if detected_broker in ("relai", "pocket"):
        broker_defaults = {
            "ticker": "BTC-USD",
            "asset_class": "crypto",
            "fx_rate": 1.0,
            "coingecko_id": "bitcoin",
            "price_source": "coingecko",
        }

    return {
        "upload_id": upload_id,
        "filename": filename,
        "encoding": detected_encoding,
        "delimiter": delimiter,
        "headers": headers,
        "sample_rows": sample_rows,
        "row_count": row_count,
        "detected_broker": detected_broker,
        "suggested_mapping": suggested_mapping,
        "unique_types": [{"value": k, "count": v} for k, v in unique_types.items()],
        "suggested_type_mapping": suggested_type_mapping,
        "detected_date_format": detected_date_format,
        "saved_profiles": saved_profiles,
        "broker_defaults": broker_defaults,
        "total_chf_formula": "net_amount_plus_fees" if detected_broker in ("relai", "pocket") else "standard",
    }


# --- CSV Parsing ---

def _resolve_date_format(date_format: str | None) -> str | None:
    """Resolve a user-facing date format label (e.g. "DD.MM.YYYY") to a strptime format."""
    if not date_format:
        return None
    for fmt, label in DATE_FORMATS:
        if date_format == label:
            return fmt
    if "%" in date_format:
        return date_format  # already a strptime format
    return None


async def parse_csv(file_bytes: bytes, filename: str, db: AsyncSession, user_mapping: dict | None = None, user_id: uuid.UUID | None = None, type_mapping: dict | None = None, broker_defaults: dict | None = None, total_chf_formula: str = "standard", date_format: str | None = None) -> ImportPreview:
    """Parse CSV file with auto-detection of encoding, delimiter, and columns."""
    warnings = []

    # Detect encoding
    text, _encoding = decode_csv_bytes(file_bytes)
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

    rows = read_rows_limited(reader)
    if not rows:
        raise ValueError("CSV enthält keine Datenzeilen")

    preferred_date_fmt = _resolve_date_format(date_format)

    # Im Thread: die Schleife hat kein await und hielte sonst bei MAX_IMPORT_ROWS
    # Zeilen den Event-Loop für alle anderen Requests an.
    parsed, row_warnings = await asyncio.to_thread(
        _parse_csv_rows, rows, mapping, type_mapping, broker_defaults, total_chf_formula, preferred_date_fmt
    )
    warnings.extend(row_warnings)

    parsed, new_positions = await enrich_transactions(parsed, db, user_id=user_id)

    return ImportPreview(
        source_type="csv",
        filename=filename,
        total_rows=len(parsed),
        transactions=parsed,
        new_positions=new_positions,
        warnings=cap_warnings(warnings),
        csv_mapping=mapping,
    )


def _parse_csv_rows(
    rows: list[dict],
    mapping: dict,
    type_mapping: dict | None,
    broker_defaults: dict | None,
    total_chf_formula: str,
    preferred_date_fmt: str | None,
) -> tuple[list[ParsedTransaction], list[str]]:
    """Parse all rows of a generic CSV. Returns (transactions, warnings)."""
    parsed: list[ParsedTransaction] = []
    warnings: list[str] = []
    for i, row in enumerate(rows):
        try:
            txn = _parse_csv_row(i, row, mapping, type_mapping=type_mapping, broker_defaults=broker_defaults, total_chf_formula=total_chf_formula, preferred_date_fmt=preferred_date_fmt)
            if txn:
                parsed.append(txn)
                for w in txn.warnings:
                    warnings.append(f"Zeile {i + 2}: {w}")
        except Exception as e:
            warnings.append(f"Zeile {i + 2}: {e}")
    return parsed, warnings


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


def _parse_csv_row(index: int, row: dict, mapping: dict, type_mapping: dict | None = None, broker_defaults: dict | None = None, total_chf_formula: str = "standard", preferred_date_fmt: str | None = None) -> ParsedTransaction | None:
    """Parse a single CSV row into a ParsedTransaction."""
    def get(field: str, default=""):
        col = mapping.get(field)
        if col and col in row:
            return row[col].strip() if row[col] else default
        return default

    date_str = get("date")
    if not date_str:
        return None

    # Try date formats — user/profile-selected format first, then fallback list
    formats = [fmt for fmt, _label in DATE_FORMATS]
    if preferred_date_fmt:
        formats = [preferred_date_fmt] + [f for f in formats if f != preferred_date_fmt]
    parsed_date = None
    for fmt in formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt).date()
            break
        except ValueError:
            continue  # Expected: trying multiple date formats

    if not parsed_date:
        raise ValueError(f"Unbekanntes Datumsformat: {date_str}")
    # ValueError ausserhalb des Buchungszeitraums: die Zeile fällt mit Warnung weg.
    check_booking_date(parsed_date)

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

    row_warnings: list[str] = []

    def parse_num(field: str, default=0, warn_label: str | None = None) -> float:
        raw = get(field, "")
        if not raw:
            return default
        # Handle Swiss number format (ASCII + typographic apostrophe as thousands separator)
        val = raw.replace("'", "").replace("’", "")
        if "," in val and "." in val:
            # Comma is a thousands separator (e.g. "1,234.56") — strip it
            val = val.replace(",", "")
        else:
            # Comma is the decimal separator (e.g. "12,34")
            val = val.replace(",", ".")
        try:
            return float(val)
        except ValueError:
            logger.debug(f"Could not parse numeric value: {raw!r}, using default {default}")
            if warn_label:
                row_warnings.append(f"{warn_label} '{raw}' konnte nicht gelesen werden — auf {default} gesetzt")
            return default

    # Apply broker defaults
    ticker = get("ticker") or (broker_defaults or {}).get("ticker") or None

    # Beträge je Feld einmal lesen: ein unlesbarer Wert meldet sich so genau
    # einmal und wird nicht still zu 0.
    fees_chf = parse_num("fees_chf", warn_label="Gebühren")
    total_chf = parse_num("total_chf", warn_label="Betrag")
    # Calculate total_chf based on formula
    if total_chf_formula == "net_amount_plus_fees":
        total_chf += fees_chf

    # Set suggested_asset_type from defaults
    suggested_type = (broker_defaults or {}).get("asset_class")

    total_column = str(mapping.get("total_chf") or "").strip().lower()

    return ParsedTransaction(
        row_index=index,
        type=txn_type,
        date=parsed_date.isoformat(),
        ticker=ticker,
        isin=get("isin") or None,
        name=get("name") or None,
        shares=parse_num("shares", warn_label="Stückzahl"),
        price_per_share=parse_num("price_per_share", warn_label="Kurs"),
        currency=get("currency", "CHF") or "CHF",
        fx_rate_to_chf=(broker_defaults or {}).get("fx_rate") or parse_num("fx_rate_to_chf", 1.0),
        fees_chf=fees_chf,
        taxes_chf=parse_num("taxes_chf", warn_label="Steuern"),
        total_chf=total_chf,
        notes=get("notes") or None,
        suggested_asset_type=suggested_type,
        confidence=1.0,
        order_id=get("order_id") or None,
        warnings=row_warnings,
        total_in_chf=total_column in CHF_TOTAL_COLUMNS,
    )


# --- Duplicate detection (shared by preview enrichment and confirm) ---

def _to_date(d: str | date) -> date:
    return date.fromisoformat(d) if isinstance(d, str) else d


async def _load_dup_sets(
    db: AsyncSession,
    user_id: uuid.UUID | None,
    order_ids: set[str],
    dates: set[date],
) -> tuple[set, set, set]:
    """Batch-load duplicate keys: one query per dimension instead of 1-3
    EXISTS roundtrips per import row (Review 2026-07-02, M31).

    Returns ``(order_keys, exact_keys, partial_keys, order_totals)``:

    - ``order_keys``:   ``(uid, order_id, type_value)``
    - ``exact_keys``:   ``(uid, position_id_str, date, type_value, round(total, 2))``
    - ``partial_keys``: ``(uid, position_id_str, date, type_value)``
    - ``order_totals``: derselbe Schluessel wie ``order_keys`` -> gespeicherter
      ``total_chf``. Nur so laesst sich sagen, ob ein per Order-ID erkanntes
      Duplikat inhaltlich UEBEREINSTIMMT — ein aus einem kaputten Import
      stammender 0-Betrag sieht sonst aus wie eine saubere Wiedererkennung.

    Each key is stored once with the row's real user_id and once with
    ``uid=None`` — the None variant mirrors the semantics of the previous
    per-row EXISTS checks when no user scope was supplied.
    """
    order_keys: set = set()
    exact_keys: set = set()
    partial_keys: set = set()
    order_totals: dict = {}

    if order_ids:
        stmt = select(
            Transaction.user_id, Transaction.order_id, Transaction.type, Transaction.total_chf
        ).where(Transaction.order_id.in_(sorted(order_ids)))
        if user_id is not None:
            stmt = stmt.where(Transaction.user_id == user_id)
        for uid, oid, ttype, total in (await db.execute(stmt)).all():
            for u in (uid, None):
                order_keys.add((u, oid, ttype.value))
                order_totals.setdefault((u, oid, ttype.value), round(float(total or 0), 2))

    if dates:
        stmt = select(
            Transaction.user_id,
            Transaction.position_id,
            Transaction.date,
            Transaction.type,
            Transaction.total_chf,
        ).where(Transaction.date.in_(sorted(dates)))
        if user_id is not None:
            stmt = stmt.where(Transaction.user_id == user_id)
        for uid, pid, d, ttype, total in (await db.execute(stmt)).all():
            for u in (uid, None):
                partial_keys.add((u, str(pid), d, ttype.value))
                exact_keys.add((u, str(pid), d, ttype.value, round(float(total or 0), 2)))

    return order_keys, exact_keys, partial_keys, order_totals


def _collect_dup_query_inputs(
    rows: list,
) -> tuple[set[str], set[date]]:
    """Collect order_ids and dates from parsed rows (ParsedTransaction or dict)
    for the batched duplicate lookup."""
    order_ids: set[str] = set()
    dates: set[date] = set()
    for r in rows:
        oid = r.get("order_id") if isinstance(r, dict) else getattr(r, "order_id", None)
        if oid and oid != "00000000":
            order_ids.add(str(oid))
        raw_date = r.get("date") if isinstance(r, dict) else getattr(r, "date", None)
        if raw_date:
            try:
                dates.add(_to_date(raw_date))
            except (ValueError, TypeError):
                pass
    return order_ids, dates


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

    ticker_map = {p.ticker.upper(): p for p in positions}
    isin_map = {p.isin.upper(): p for p in positions if p.isin}

    # Duplikat-Keys batchweise vorladen (M31): 2 Queries für die ganze Datei
    # statt 1-3 EXISTS-Roundtrips pro Zeile.
    _order_ids, _dates = _collect_dup_query_inputs(txns)
    order_keys, exact_keys, partial_keys, order_totals = await _load_dup_sets(
        db, user_id, _order_ids, _dates
    )

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

            # Duplicate detection — order_id based (Swissquote) or exact/partial
            # match. Set-Lookup gegen die batchgeladenen Keys (M31); bereits
            # verarbeitete Zeilen derselben Datei zählen mit (Intra-File-Dupes).
            order_id = getattr(txn, "order_id", None)
            try:
                txn_d = _to_date(txn.date)
            except (ValueError, TypeError):
                txn_d = None
            pid_str = str(matched_pos.id)
            if order_id and order_id != "00000000" and (user_id, order_id, txn.type) in order_keys:
                txn.is_duplicate = True
                stored_total = order_totals.get((user_id, order_id, txn.type))
                if stored_total is not None and abs(stored_total - round(txn.total_chf, 2)) >= 0.01:
                    # Gleiche Buchung, anderer Betrag: die erfasste Zeile stammt
                    # sehr wahrscheinlich aus einem fehlerhaften Import. Ein
                    # erneuter Import repariert sie NICHT (Duplikat wird
                    # uebersprungen) — das muss der Nutzer sehen.
                    txn.duplicate_stored_total_chf = stored_total
                    txn.warnings = [
                        *txn.warnings,
                        f"Bereits erfasst mit CHF {stored_total:.2f} statt CHF {txn.total_chf:.2f}",
                    ]
            elif txn_d is not None:
                if (user_id, pid_str, txn_d, txn.type, round(txn.total_chf, 2)) in exact_keys:
                    txn.is_duplicate = True
                elif (user_id, pid_str, txn_d, txn.type) in partial_keys:
                    txn.warnings = [*txn.warnings, "Ähnliche Transaktion existiert bereits (anderer Betrag)"]

            # Intra-File-Duplikate: nicht-doppelte Zeile in die Sets aufnehmen,
            # damit eine identische Folgezeile derselben Datei erkannt wird.
            # NUR für Zeilen OHNE eigene order_id: zwei legitime Orders mit
            # unterschiedlichen order_ids (gleicher Tag/Preis/Betrag) sind
            # KEINE Duplikate — die Broker-Order-ID ist die massgebliche
            # Identität (Review-Fix 2026-07-02; DB-Stand bleibt wie früher
            # vollständig im Exact-Check).
            if not txn.is_duplicate and txn_d is not None:
                if order_id and order_id != "00000000":
                    order_keys.add((user_id, order_id, txn.type))
                else:
                    exact_keys.add((user_id, pid_str, txn_d, txn.type, round(txn.total_chf, 2)))
                    partial_keys.add((user_id, pid_str, txn_d, txn.type))

        elif txn.ticker or txn.isin:
            # New position needed
            key = txn.isin or txn.ticker or ""
            txn.is_new_position = True

            if key and key not in new_positions_map:
                suggested_type = _guess_asset_type(txn)
                yf_ticker = txn.ticker
                shown_ticker = txn.ticker or txn.isin or ""
                if suggested_type in MARKET_PRICED_TYPES and not is_market_ticker(shown_ticker):
                    # Der Ticker bleibt, wie die Datei ihn liefert. An Yahoo geht nur
                    # ein gültiges Symbol: das eindeutig ableitbare oder keines.
                    yf_ticker = yahoo_symbol_for(shown_ticker)
                    txn.warnings = [*txn.warnings, ticker_warning(shown_ticker)]
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
            txn.suggested_yfinance_ticker = (
                new_positions_map[key]["yfinance_ticker"] if key in new_positions_map else txn.ticker
            )

    # Batch-fetch historical FX rates for non-CHF transactions with default rate 1.0
    await _enrich_fx_rates(txns)

    return txns, list(new_positions_map.values())


# CNH (Offshore-Yuan bei IBKR) und GBX (Pence) stehen nicht in ISO 4217, kommen
# in Broker-Exporten aber vor. "GBp" besteht die ISO-Prüfung über die Grossschreibung.
_EXTRA_FX_LOOKUP_CODES = frozenset({"CNH", "GBX"})

# Ein Abruf ohne Ergebnis wird für diese Zeit nicht wiederholt. Der Wizard parst
# dieselbe Datei mehrmals hintereinander; kurz genug, dass ein Yahoo-Aussetzer
# nicht lange nachwirkt.
FX_MISS_TTL_SECONDS = 900


def is_fx_lookup_currency(code: str | None) -> bool:
    """True when a historical FX rate may be fetched for this currency code.

    Der Code wird Teil des Yahoo-Symbols und stammt ungeprüft aus der Datei.
    """
    return is_iso_currency(code) or (isinstance(code, str) and code.upper() in _EXTRA_FX_LOOKUP_CODES)


def _add_fx_warning(txns: list[ParsedTransaction], currencies: set[str], message: str) -> None:
    for txn in txns:
        if txn.currency in currencies and txn.fx_rate_to_chf == 1.0:
            txn.warnings = [*txn.warnings, message.format(currency=txn.currency)]


async def _enrich_fx_rates(txns: list[ParsedTransaction]) -> None:
    """Batch-fetch historical FX rates for foreign currency transactions missing a real rate."""
    from datetime import timedelta
    from yf_patch import yf_download
    import pandas as pd

    # Collect currencies that need FX lookup (non-CHF with default rate 1.0)
    currency_rows: dict[str, int] = {}
    for txn in txns:
        if txn.currency and txn.currency != "CHF" and txn.fx_rate_to_chf == 1.0:
            currency_rows[txn.currency] = currency_rows.get(txn.currency, 0) + 1

    if not currency_rows:
        return

    unknown = {c for c in currency_rows if not is_fx_lookup_currency(c)}
    if unknown:
        _add_fx_warning(
            txns, unknown,
            "Unbekannte Währung «{currency}» — kein Wechselkurs abgerufen, Kurs 1.0 verwendet",
        )
    # Je Währung bis zu vier Yahoo-Abrufe: die Zahl der Währungen je Import ist
    # gedeckelt. Die häufigsten zuerst, damit eine echte Datei vollständig bleibt.
    candidates = sorted(
        (c for c in currency_rows if c not in unknown),
        key=lambda c: (-currency_rows[c], c),
    )
    currencies_needed = candidates[:MAX_IMPORT_FX_CURRENCIES]
    over_limit = set(candidates[MAX_IMPORT_FX_CURRENCIES:])
    if over_limit:
        _add_fx_warning(
            txns, over_limit,
            f"Mehr als {MAX_IMPORT_FX_CURRENCIES} Fremdwährungen in der Datei — "
            "kein Wechselkurs für {currency} abgerufen, Kurs 1.0 verwendet",
        )

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
        miss_key = f"import_fx_miss:{pair}:{start_str}:{end_str}"
        if cache.get(miss_key):
            return None
        try:
            data = await asyncio.to_thread(
                yf_download, [pair],
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
        cache.set(miss_key, True, ttl=FX_MISS_TTL_SECONDS)
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

    failed = set(currencies_needed) - set(fx_data)
    if failed:
        _add_fx_warning(
            txns, failed,
            "Kein Wechselkurs für {currency} gefunden — Kurs 1.0 verwendet, bitte prüfen",
        )

    # Im Thread: der Nachschlag je Zeile hat kein await (pandas, rund 60 µs je Zeile).
    await asyncio.to_thread(_apply_fx_rates, txns, fx_data)


def _apply_fx_rates(txns: list[ParsedTransaction], fx_data: dict) -> None:
    """Set the historical FX rate on every transaction whose currency was fetched."""
    import pandas as pd

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
                # Recalculate total_chf if it was based on the default rate.
                # Nur Handel: bei einer Dividende mit Stückzahl und Kurs IST
                # total_chf das Netto und darf nicht zu Brutto + Gebühren werden.
                if txn.type in TRADE_TYPES and txn.shares > 0 and txn.price_per_share > 0:
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

    # 5. Bond detection — muss VOR der ETF-Heuristik laufen, sonst fängt
    # "ishares"/"etf" jeden Bond-ETF ab und er landet still als Aktien-ETF.
    # Nur börsengehandelte Bond-ETFs/-Fonds; Direktanleihen (Nominal,
    # Stückzinsen) sind ein anderes Datenmodell und werden hier nicht erkannt.
    bond_keywords = ["anleihe", "obligation", "fixed income", "rentenfonds"]
    if any(kw in name for kw in bond_keywords):
        return "bond"
    # Wortgrenzen statt Substring: "Bonduelle" (Aktie) enthält "bond".
    bond_patterns = [r"\bbonds?\b", r"\bgilts?\b", r"\bt-bills?\b", r"\btreasury bills?\b"]
    if any(re.search(p, name) for p in bond_patterns):
        return "bond"

    # 6. ETF detection
    etf_keywords = ["etf", "ishares", "vanguard", "spdr", "xtrackers", "wisdomtree", "amundi", "lyxor"]
    fund_context = etf_keywords + ["ucits", "fund", "fonds", "index"]
    # Mehrdeutige Bond-Marker zählen nur im Fonds-Kontext: "Treasury Wine
    # Estates" ist eine Aktie, "iShares $ Treasury UCITS ETF" nicht. Deckt
    # Broker-Abkürzungen ab, die "Bond" wegkürzen ("Treasury Bd 0-1yr").
    if any(kw in name for kw in fund_context):
        ambiguous_bond = [r"\btreasury\b", r"\bgovt\b", r"\btips\b", r"\baggregate\b"]
        if any(re.search(p, name) for p in ambiguous_bond):
            return "bond"

    if any(kw in name for kw in etf_keywords):
        return "etf"

    return "stock"


# --- Confirm Import ---

_IMPORT_LOCK_NAMESPACE = 0x494D5054  # "IMPT", erster der beiden Lock-Schlüssel
_IMPORT_LOCK_POLL_SECONDS = 0.25
_IMPORT_LOCK_MAX_WAIT_SECONDS = 20.0


async def _lock_user_import(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialise confirm_import per user until the end of the transaction.

    Die Duplikatprüfung liest den committeten Stand und fügt dann ein; ohne
    Sperre bestehen zwei gleichzeitige Bestätigungen derselben Datei beide die
    Prüfung und buchen alles doppelt. Der zweite Aufruf wartet und sieht danach
    die Zeilen des ersten.

    Nur Postgres; auf anderen Dialekten (Tests: SQLite) ohne Wirkung.
    ``pg_try_advisory_xact_lock`` in einer Schleife statt des blockierenden
    ``pg_advisory_xact_lock``: ein wartendes Statement fiele unter
    ``statement_timeout`` (DB_STATEMENT_TIMEOUT_MS).
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    key = int.from_bytes(user_id.bytes[:4], "big", signed=True)
    deadline = time.monotonic() + _IMPORT_LOCK_MAX_WAIT_SECONDS
    while True:
        acquired = (await db.execute(
            sa_text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
            {"ns": _IMPORT_LOCK_NAMESPACE, "key": key},
        )).scalar()
        if acquired:
            return
        if time.monotonic() >= deadline:
            raise HTTPException(
                status_code=409,
                detail="Für dieses Konto läuft bereits ein Import. Bitte kurz warten und erneut versuchen.",
            )
        await asyncio.sleep(_IMPORT_LOCK_POLL_SECONDS)


async def confirm_import(
    transactions: list[dict],
    new_positions: list[dict],
    db: AsyncSession,
    user_id: uuid.UUID | None = None,
    fx_transactions: list[dict] | None = None,
) -> dict:
    """Create new positions and bulk-insert transactions.

    Raises HTTPException 400 when the import would exceed the per-user limits
    and 409 when another import of the same user does not finish in time.
    """

    # Buchungen, die der Nutzer noch anlegen darf (None = kein Nutzerbezug).
    txn_budget: int | None = None
    if user_id is not None:
        await _lock_user_import(db, user_id)
        # Dieselben Limits wie beim Anlegen von Hand (api/positions, api/transactions).
        existing_positions = await db.scalar(
            select(func.count()).select_from(Position).where(Position.user_id == user_id)
        ) or 0
        if existing_positions + len(new_positions) > MAX_POSITIONS_PER_USER:
            raise HTTPException(
                status_code=400,
                detail=f"Import überschreitet die maximale Anzahl Positionen ({MAX_POSITIONS_PER_USER})",
            )
        existing_transactions = await db.scalar(
            select(func.count()).select_from(Transaction).where(Transaction.user_id == user_id)
        ) or 0
        txn_budget = MAX_TRANSACTIONS_PER_USER - existing_transactions

    # Quelle je neuer Position aus ihren Buchungen: das Schema der neuen Position
    # trägt sie nicht, Bucket-Regeln mit Quelle brauchen sie aber.
    source_by_key: dict[str, str] = {}
    for txn_data in transactions:
        if txn_data.get("is_new_position") and txn_data.get("import_source"):
            source_by_key.setdefault(
                txn_data.get("isin") or txn_data.get("ticker") or "", txn_data["import_source"]
            )

    created_positions = 0
    created_transactions = 0
    skipped_duplicates = 0
    derived_totals = 0  # Betrag aus Menge x Kurs abgeleitet (fehlende Spalte im Export)
    position_id_map: dict[str, uuid.UUID] = {}  # key -> new position UUID
    # Dividenden-Tracker Hook 2: gesammelte dividend-Transaktionen pro User
    # fuer Bulk-Auto-Match nach commit().
    created_dividend_txns: dict[uuid.UUID, list[Transaction]] = {}
    created_buysell_txns: dict[uuid.UUID, list[Transaction]] = {}
    # Positionen, die in diesem Lauf eine stückzahltragende Buchung erhielten.
    ledger_positions: dict[str, Position] = {}
    # Positionen, die in diesem Lauf irgendeine Buchung erhielten.
    booked_positions: dict[str, Position] = {}

    # 1. Create new positions
    for np in new_positions:
        try:
            asset_type = AssetType(np.get("suggested_type", "stock"))
        except ValueError:
            # warning statt debug: ein stiller stock-Fallback bucht die Position
            # in der falschen Assetklasse ein und fällt sonst niemandem auf.
            logger.warning(
                f"Unknown asset type {np.get('suggested_type')!r} for {np.get('ticker')!r}, "
                "defaulting to stock"
            )
            asset_type = AssetType.stock

        try:
            ps = PriceSource(np.get("price_source", "yahoo"))
        except ValueError:
            logger.debug(f"Unknown price source {np.get('price_source')!r}, defaulting to yahoo")
            ps = PriceSource.yahoo

        # CoinGecko-Kurse nur für Krypto: mit einer coingecko_id auf einer Aktie
        # liesse sich der Kurs eines beliebigen Tickers überschreiben. Die
        # Vorschau schlägt die ID vor, der Nutzer kann den Typ danach ändern.
        coingecko_id = np.get("coingecko_id") if asset_type == AssetType.crypto else None
        if asset_type != AssetType.crypto and ps == PriceSource.coingecko:
            ps = PriceSource.yahoo

        # Cash/Pension sind manuell gepflegte Salden (in _NON_YAHOO_TYPES) — sie
        # bekommen KEINEN yfinance_ticker, sonst traegt die Position ein
        # handelbares Signal und faellt potenziell in den cash-Saldo-
        # Fehlbepreisungs-Bug. Geldmarkt-/T-Bill-ETFs gehoeren als etf importiert.
        _is_manual_balance = asset_type in (AssetType.cash, AssetType.pension)
        yfinance_ticker = None if _is_manual_balance else (np.get("yfinance_ticker") or np["ticker"])
        if asset_type.value in MARKET_PRICED_TYPES and not is_market_ticker(yfinance_ticker or ""):
            # Der Anzeige-Ticker aus der Datei darf Leer- und Sonderzeichen tragen
            # (IBKR «BRK B»). Als Yahoo-Symbol zählt nur ein gültiger Markt-Ticker:
            # der eindeutig ableitbare («BRK-B») oder keiner. Der Wert geht in
            # Abrufe, deren Ergebnis sich alle Nutzer teilen.
            yfinance_ticker = yahoo_symbol_for(np["ticker"])
        pos_kwargs = dict(
            ticker=np["ticker"],
            name=np["name"],
            type=asset_type,
            currency=np.get("currency", "CHF"),
            isin=np.get("isin"),
            yfinance_ticker=yfinance_ticker,
            coingecko_id=coingecko_id,
            price_source=ps,
            is_etf=asset_type == AssetType.etf,
            shares=0,
            cost_basis_chf=0,
        )
        # Parität zu create_position_core (api/positions.py): Cash/Vorsorge sind
        # immer manuell bepreist. Ohne das landen importierte Konten auf dem
        # Model-Default auto — der Recalc-Guard schuetzt sie dann nur noch
        # ueber die Typ-Pruefung.
        if _is_manual_balance:
            pos_kwargs["pricing_mode"] = PricingMode.manual
        if user_id is not None:
            pos_kwargs["user_id"] = user_id

        # Bucket-Zuordnung: PE/RE/Pension auf System-Bucket; liquide Typen
        # auf User-spezifizierten bucket_id oder liquid_default.
        if user_id is not None:
            from models.bucket import Bucket, BucketSystemRole
            from services.bucket_service import (
                get_liquid_default_bucket,
                create_system_buckets,
            )
            type_value = asset_type.value if hasattr(asset_type, "value") else asset_type
            role_map = {
                "real_estate": BucketSystemRole.real_estate,
                "private_equity": BucketSystemRole.private_equity,
                "pension": BucketSystemRole.pension,
            }
            if type_value in role_map:
                sys_q = await db.execute(
                    select(Bucket).where(
                        Bucket.user_id == user_id,
                        Bucket.system_role == role_map[type_value],
                        Bucket.deleted_at.is_(None),
                    )
                )
                sys_b = sys_q.scalar_one_or_none()
                if sys_b is None:
                    await create_system_buckets(db, user_id)
                    await db.flush()
                    sys_q = await db.execute(
                        select(Bucket).where(
                            Bucket.user_id == user_id,
                            Bucket.system_role == role_map[type_value],
                            Bucket.deleted_at.is_(None),
                        )
                    )
                    sys_b = sys_q.scalar_one()
                pos_kwargs["bucket_id"] = sys_b.id
            else:
                # Liquide: 1. User-Wizard-Wahl 2. import_bucket_rules 3. liquid_default
                raw_bid = np.get("bucket_id")
                resolved = None
                if raw_bid:
                    try:
                        bid = uuid.UUID(str(raw_bid))
                        b_q = await db.execute(
                            select(Bucket).where(
                                Bucket.id == bid,
                                Bucket.user_id == user_id,
                                Bucket.deleted_at.is_(None),
                            )
                        )
                        b_obj = b_q.scalar_one_or_none()
                        if b_obj is not None:
                            resolved = b_obj.id
                    except (ValueError, TypeError):
                        resolved = None
                if resolved is None:
                    # Auto-Mapping aus import_bucket_rules (Phase 2 F-15)
                    from services.import_bucket_rule_service import (
                        resolve_bucket_for_import,
                    )
                    import_source = (
                        np.get("import_source")
                        or np.get("source")
                        or source_by_key.get(np.get("key", np["ticker"]))
                    )
                    resolved = await resolve_bucket_for_import(
                        db,
                        user_id,
                        ticker=np.get("ticker"),
                        source=import_source,
                    )
                if resolved is None:
                    liquid = await get_liquid_default_bucket(db, user_id)
                    resolved = liquid.id
                pos_kwargs["bucket_id"] = resolved

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

    # Duplikat-Keys batchweise vorladen (M31): 2 Queries für die ganze Datei
    # statt bis zu 2 EXISTS-Roundtrips pro Zeile.
    _order_ids, _dates = _collect_dup_query_inputs(transactions)
    order_keys, exact_keys, _, _ = await _load_dup_sets(db, user_id, _order_ids, _dates)

    # 2. Insert transactions (skip duplicates unless overridden)
    for txn_data in transactions:
        if txn_data.get("is_duplicate") and not txn_data.get("force_import"):
            skipped_duplicates += 1
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
            # check_booking_date: ein Datum vor 1970 liesse die Snapshot-
            # Regeneration über Jahrhunderte laufen.
            txn_date = check_booking_date(_to_date(txn_data["date"]))
        except (ValueError, KeyError, TypeError) as e:
            logger.warning(f"Skipping transaction with invalid date {txn_data.get('date')!r}: {e}")
            continue

        # Ownership-Check: position_id kommt vom Client und MUSS dem User
        # gehören (all_positions ist user-scoped). Fremde oder unbekannte
        # IDs werden übersprungen — sonst könnte ein User Transaktionen an
        # Positionen anderer User hängen (Recalc würde sie übernehmen).
        try:
            pos_id = str(uuid.UUID(pos_id))
        except (ValueError, AttributeError, TypeError):
            logger.warning("Skipping transaction with malformed position_id %r", pos_id)
            continue
        pos = all_positions.get(pos_id)
        if pos is None:
            logger.warning(
                "Skipping transaction with foreign/unknown position_id %s (user %s)",
                pos_id, user_id,
            )
            continue
        txn_user_id = pos.user_id

        # Ensure total_chf is derived from fx_rate_to_chf (not an independent FX lookup)
        shares = float(txn_data.get("shares", 0))
        price_per_share = float(txn_data.get("price_per_share", 0))
        currency = txn_data.get("currency", "CHF")
        fx_rate = float(txn_data.get("fx_rate_to_chf", 1.0))
        fees_chf = float(txn_data.get("fees_chf", 0))
        taxes_chf = float(txn_data.get("taxes_chf", 0))
        total_chf = float(txn_data.get("total_chf", 0))

        # Nur Handel: eine Dividende mit Stückzahl und Kurs behält ihr Netto und
        # läuft in den Dividenden-Zweig darunter (wie fix_foreign_total_chf).
        if (
            currency != "CHF" and fx_rate > 0 and fx_rate != 1.0
            and shares > 0 and price_per_share > 0
            and txn_type.value in TRADE_TYPES
        ):
            total_chf = round(abs(shares * price_per_share) * fx_rate + fees_chf, 2)
        elif currency != "CHF" and fx_rate > 0 and fx_rate != 1.0 and txn_type in (TransactionType.dividend, TransactionType.capital_gain):
            # For dividends: shares=0, use gross_amount/tax_amount for CHF conversion
            gross = float(txn_data.get("gross_amount", 0))
            tax = float(txn_data.get("tax_amount", 0))
            if gross > 0:
                total_chf = round((gross - tax) * fx_rate, 2) if tax else round(gross * fx_rate, 2)
            elif total_chf > 0 and not txn_data.get("total_in_chf"):
                # total_chf might still be in foreign currency — convert it.
                # Nicht bei total_in_chf: die Spalte «Total CHF» des eigenen
                # Exports trägt den Betrag schon in CHF.
                total_chf = round(total_chf * fx_rate, 2)

        # Sicherheitsnetz: Handel MIT Menge und Kurs, aber OHNE Betrag landete
        # bisher mit total_chf=0 in der DB — Cost-Basis 0, Position mit -100%,
        # und die Zeilen muessen einzeln wieder geloescht werden. Das passiert,
        # sobald ein Broker seine Betragsspalte umbenennt (Feedback 30.7.2026:
        # Bitcoin-Kaeufe ohne Betrag). Dieselbe Ableitung wie der API-Pfad
        # (create_transaction_core): Brutto = Menge x Kurs x FX, ohne Gebuehren.
        if (
            not total_chf
            and txn_type in (TransactionType.buy, TransactionType.sell)
            and shares > 0
            and price_per_share > 0
        ):
            total_chf = round(abs(shares * price_per_share) * fx_rate, 2)
            derived_totals += 1

        # Server-side duplicate re-check (idempotency): never trust the
        # client-supplied is_duplicate flag alone. Set-Lookup gegen die
        # batchgeladenen Keys (M31) — enthält committeten DB-Stand PLUS die
        # in DIESEM Lauf bereits eingefügten Zeilen (Intra-File-Duplikate).
        # force_import is the explicit user override.
        order_id = txn_data.get("order_id")
        if not txn_data.get("force_import"):
            is_dup = bool(
                order_id and order_id != "00000000"
                and (txn_user_id, order_id, txn_type.value) in order_keys
            )
            if not is_dup and (txn_user_id, pos_id, txn_date, txn_type.value, round(total_chf, 2)) in exact_keys:
                is_dup = True
            if is_dup:
                skipped_duplicates += 1
                logger.info(f"Import confirm: skipping server-side duplicate (position={pos_id}, date={txn_date}, type={txn_type.value})")
                continue

        if txn_budget is not None and created_transactions >= txn_budget:
            await db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Import überschreitet die maximale Anzahl Transaktionen ({MAX_TRANSACTIONS_PER_USER})",
            )

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
            notes=encrypt_field(txn_data.get("notes")),
            order_id=txn_data.get("order_id"),
            isin=txn_data.get("isin"),
            import_source=txn_data.get("import_source"),
            import_batch_id=txn_data.get("import_batch_id"),
            raw_symbol=txn_data.get("raw_symbol"),
            gross_amount=txn_data.get("gross_amount"),
            tax_amount=txn_data.get("tax_amount"),
            bucket_id_at_sale=(pos.bucket_id if pos and txn_type == TransactionType.sell else None),
        )
        db.add(txn)

        # Intra-File-Duplikate: frisch eingefügte Txn in die Dup-Sets aufnehmen,
        # damit eine identische Folgezeile derselben Datei erkannt wird.
        # NUR ohne eigene order_id — zwei Orders mit unterschiedlichen
        # order_ids sind eigenständige Trades (Review-Fix 2026-07-02).
        if order_id and order_id != "00000000":
            order_keys.add((txn_user_id, order_id, txn_type.value))
        else:
            exact_keys.add((txn_user_id, pos_id, txn_date, txn_type.value, round(total_chf, 2)))

        # Bestand erst nach der Schleife aus dem Ledger rechnen (siehe unten).
        booked_positions[pos_id] = pos
        if txn_type in LEDGER_TYPES:
            ledger_positions[pos_id] = pos

        # Hook 2 Bookkeeping: alle dividend-Transaktionen sammeln, fuer
        # spaeteren Bulk-Auto-Match (nach db.commit()).
        if txn_type == TransactionType.dividend and txn_user_id:
            created_dividend_txns.setdefault(txn_user_id, []).append(txn)
        elif txn_type in (TransactionType.buy, TransactionType.sell) and txn_user_id:
            created_buysell_txns.setdefault(txn_user_id, []).append(txn)

        created_transactions += 1

    # Bestand, Einstand und is_active je betroffener Position chronologisch aus
    # allen Buchungen ableiten. Je Zeile in Dateireihenfolge angewandt, schloss
    # ein Auszug mit der neuesten Zeile zuerst die Position zwischenzeitlich und
    # löschte ihren Stop-Loss, obwohl der Endbestand nicht 0 ist.
    if ledger_positions:
        await db.flush()
        for pos in ledger_positions.values():
            # recalculate_position gleicht is_active selbst ab. Es reaktiviert
            # nicht, wenn im selben Bucket schon eine aktive Position mit diesem
            # Ticker liegt: ein zweiter Abgleich hier verletzte den Unique-Index.
            await recalculate_position(db, pos.id)

    # Eine neu angelegte Position, die nur Dividenden oder Zinsen erhielt, erreicht
    # der Block oben nicht. Sie hat 0 Stück und bliebe sonst aktiv ohne Bestand.
    for new_id in position_id_map.values():
        pos = booked_positions.get(str(new_id))
        if pos is not None and str(new_id) not in ledger_positions:
            _sync_active_state(pos)

    # 3. Persist FX transactions if provided — idempotent (M14): ein zweiter
    # Import derselben CSV darf keine doppelten FxTransaction-Rows erzeugen.
    # Dedup-Key: (user_id, order_id) wenn order_id vorhanden, sonst
    # (user_id, date, Währungspaar, Betrag).
    created_fx = 0
    skipped_fx_duplicates = 0
    if fx_transactions and user_id:
        from models.fx_transaction import FxTransaction

        fx_order_ids = {str(f.get("order_id")) for f in fx_transactions if f.get("order_id")}
        fx_dates: set[date] = set()
        for f in fx_transactions:
            try:
                fx_dates.add(_to_date(f["date"]))
            except (KeyError, ValueError, TypeError):
                pass

        existing_fx_orders: set[str] = set()
        existing_fx_tuples: set[tuple] = set()
        if fx_order_ids:
            rows = await db.execute(
                select(FxTransaction.order_id).where(
                    FxTransaction.user_id == user_id,
                    FxTransaction.order_id.in_(sorted(fx_order_ids)),
                )
            )
            existing_fx_orders = {r[0] for r in rows}
        if fx_dates:
            rows = await db.execute(
                select(
                    FxTransaction.date,
                    FxTransaction.currency_from,
                    FxTransaction.currency_to,
                    FxTransaction.amount_from,
                ).where(
                    FxTransaction.user_id == user_id,
                    FxTransaction.date.in_(sorted(fx_dates)),
                )
            )
            existing_fx_tuples = {
                (r[0], r[1], r[2], round(float(r[3] or 0), 2)) for r in rows
            }

        for fx in fx_transactions:
            try:
                fx_date = date.fromisoformat(fx["date"]) if isinstance(fx.get("date"), str) else fx.get("date")
                if not fx_date:
                    continue
                check_booking_date(fx_date)
                fx_order_id = str(fx.get("order_id")) if fx.get("order_id") else None
                fx_tuple = (
                    fx_date,
                    fx["currency_from"],
                    fx["currency_to"],
                    round(float(fx["amount_from"]), 2),
                )
                if fx_order_id:
                    if fx_order_id in existing_fx_orders:
                        skipped_fx_duplicates += 1
                        continue
                elif fx_tuple in existing_fx_tuples:
                    skipped_fx_duplicates += 1
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
                # Intra-Batch-Duplikate ebenfalls erkennen
                if fx_order_id:
                    existing_fx_orders.add(fx_order_id)
                else:
                    existing_fx_tuples.add(fx_tuple)
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"Skipping FX transaction: {e}")
                continue

    await db.commit()

    # 4. Auto-assign industry/sector for new positions — als Background-Task:
    # der yfinance-Lookup (0.5s-Kadenz pro Position, 429-Schutz) gehört nicht
    # in die awaited Confirm-Response (50 neue Positionen ≈ 1-2 Min Latenz).
    # Starke Referenz gegen GC (_industry_bg_tasks); eigene
    # DB-Session im Task (Review 2026-07-02, LOW).
    if created_positions > 0:
        new_position_ids = list(position_id_map.values())
        task = asyncio.create_task(_auto_assign_industries_background(new_position_ids))
        _industry_bg_tasks.add(task)
        task.add_done_callback(_industry_bg_tasks.discard)

    # 5. Dividenden-Tracker Hook 2: alle frisch importierten dividend-Txns
    # gegen offene Pending-Dividenden matchen (best-effort).
    if created_dividend_txns:
        try:
            from services.pending_dividend_service import try_auto_match_transactions_bulk
            for u_id, txns in created_dividend_txns.items():
                await try_auto_match_transactions_bulk(db, txns, u_id)
        except Exception as e:
            logger.warning(f"Dividend bulk auto-match failed: {e}")

    # 6. Pending-Order Hook: importierte buy/sell-Txns gegen offene Orders matchen
    # (Fill-Reconciliation, best-effort).
    if created_buysell_txns:
        try:
            from services.pending_order_service import try_auto_fill_orders_bulk
            for u_id, txns in created_buysell_txns.items():
                await try_auto_fill_orders_bulk(db, txns, u_id)
        except Exception as e:
            logger.warning(f"Order bulk auto-fill failed: {e}")

    # 7. Trade-Journal Hook: importierte buy/sell-Txns gegen offene Vault-Trade-
    # Plaene verlinken (Plan->Ist, best-effort) — deckt asynchrone Import-Fills ab.
    if created_buysell_txns:
        try:
            from services.trade_journal_service import try_auto_link_trade_reports_bulk
            for u_id, txns in created_buysell_txns.items():
                await try_auto_link_trade_reports_bulk(db, txns, u_id)
        except Exception as e:
            logger.warning(f"Trade-report bulk auto-link failed: {e}")

    return {
        "created_transactions": created_transactions,
        "created_positions": created_positions,
        "created_fx_transactions": created_fx,
        "skipped_duplicates": skipped_duplicates,
        "skipped_fx_duplicates": skipped_fx_duplicates,
        "derived_totals": derived_totals,
    }


# Strong-Reference-Set für Industry-Enrichment-Tasks: ohne Referenz kann der
# GC einen create_task-Task vor Abschluss einsammeln (Muster wie
# ntfy_service._pending).
_industry_bg_tasks: set[asyncio.Task] = set()


async def _auto_assign_industries_background(position_ids: list[uuid.UUID]) -> None:
    """Background-Task-Wrapper: lädt die Positionen mit EIGENER DB-Session
    frisch und ruft _auto_assign_industries (best-effort, nie fatal)."""
    try:
        from db import async_session
        async with async_session() as bg_db:
            result = await bg_db.execute(select(Position).where(Position.id.in_(position_ids)))
            positions = list(result.scalars().all())
            if positions:
                await _auto_assign_industries(bg_db, positions)
    except Exception as e:
        logger.warning(f"Background industry auto-assign failed: {e}", exc_info=True)


async def _auto_assign_industries(db: AsyncSession, positions: list[Position]) -> None:
    """Auto-assign industry and sector for positions via yfinance (best-effort)."""
    from services.sector_mapping import INDUSTRY_TO_SECTOR
    from yf_patch import yf_ticker_attr, yf_to_thread

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
        # bond ist strukturell sektorlos — kein yfinance-Lookup, und der Sektor
        # bleibt bewusst None statt "Multi-Sector" (Bond-ETFs gehören weder in
        # die Sektor-Aggregation noch in die Sektor-Limits).
        if pos.type in (AssetType.cash, AssetType.pension, AssetType.real_estate, AssetType.bond):
            continue
        needs_lookup.append(pos)

    # Lookup via yfinance (sequential with delay to avoid rate limiting)
    for i, pos in enumerate(needs_lookup):
        if i > 0:
            await asyncio.sleep(0.5)
        try:
            ticker_str = pos.yfinance_ticker or pos.ticker
            # yf_patch-Wrapper statt rohem yf.Ticker(t).info (thread-safe,
            # korrekter User-Agent) — einziger Pfad am Wrapper vorbei war hier.
            info = await yf_to_thread(yf_ticker_attr, ticker_str, "info")
            industry = (info or {}).get("industry", "")
            sector = (info or {}).get("sector", "")

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
