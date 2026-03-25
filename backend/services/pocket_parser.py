"""Parser for Pocket (pocketbitcoin.com) CSV exports.

Pocket is a Swiss Bitcoin exchange. CSV format:
- Encoding: UTF-8
- Delimiter: Semicolon (;)
- Header: type;date;reference;price.currency;price.amount;cost.currency;cost.amount;fee.currency;fee.amount;value.currency;value.amount
- Row types: deposit (CHF bank transfer), exchange (BTC buy), withdrawal (BTC wallet transfer)
- Only 'exchange' rows are imported as buy transactions.
"""

import csv
import io
import logging
import uuid
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from services.import_service import ImportPreview, ParsedTransaction, enrich_transactions

logger = logging.getLogger(__name__)

POCKET_REQUIRED_HEADERS = {"type", "date", "reference", "price.currency", "price.amount",
                           "cost.currency", "cost.amount", "fee.currency", "fee.amount",
                           "value.currency", "value.amount"}


def detect_pocket(fieldnames: list[str]) -> bool:
    """Detect if CSV headers match Pocket export format."""
    if not fieldnames:
        return False
    cleaned = {h.strip().lower() for h in fieldnames}
    return POCKET_REQUIRED_HEADERS.issubset(cleaned)


def _parse_pocket_date(date_str: str) -> date | None:
    """Parse Pocket ISO 8601 date (e.g. '2024-12-20T11:11:08.000Z')."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    logger.warning(f"Could not parse Pocket date: {date_str!r}")
    return None


def _safe_float(val: str) -> float:
    """Parse a float, returning 0.0 on failure."""
    try:
        return float(val.strip()) if val and val.strip() else 0.0
    except (ValueError, TypeError):
        return 0.0


async def parse_pocket_csv(text: str, filename: str, db: AsyncSession | None = None, user_id: uuid.UUID | None = None) -> ImportPreview:
    """Parse Pocket CSV into ImportPreview.

    Only 'exchange' rows are imported (BTC purchases).
    'deposit' and 'withdrawal' rows are skipped.
    """
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    if not reader.fieldnames:
        raise ValueError("CSV enthält keine Header-Zeile")

    # Normalize headers (Pocket uses lowercase with dots)
    fieldnames_clean = [h.strip().lower() for h in reader.fieldnames]
    header_map = dict(zip(fieldnames_clean, reader.fieldnames))

    def get(row: dict, key: str) -> str:
        """Get value by normalized key."""
        original = header_map.get(key, key)
        return (row.get(original) or "").strip()

    batch_id = str(uuid.uuid4())
    transactions: list[ParsedTransaction] = []
    warnings: list[str] = []
    skipped_deposits = 0
    skipped_withdrawals = 0
    skipped_other = 0
    total_rows = 0

    for i, row in enumerate(reader, start=2):
        total_rows += 1
        row_type = get(row, "type").lower()

        if row_type == "deposit":
            skipped_deposits += 1
            continue
        if row_type == "withdrawal":
            skipped_withdrawals += 1
            continue
        if row_type != "exchange":
            skipped_other += 1
            if row_type:
                warnings.append(f"Zeile {i}: Unbekannter Typ '{row_type}' übersprungen")
            continue

        # Parse exchange row (BTC purchase)
        txn_date = _parse_pocket_date(get(row, "date"))
        if not txn_date:
            warnings.append(f"Zeile {i}: Ungültiges Datum übersprungen")
            continue

        shares = _safe_float(get(row, "value.amount"))  # BTC amount
        price = _safe_float(get(row, "price.amount"))    # BTC price in CHF
        cost = _safe_float(get(row, "cost.amount"))      # CHF net cost
        fees = _safe_float(get(row, "fee.amount"))        # CHF fees
        currency = get(row, "price.currency") or "CHF"
        reference = get(row, "reference")

        if shares <= 0:
            warnings.append(f"Zeile {i}: BTC-Menge <= 0, übersprungen")
            continue

        total_chf = cost + fees

        transactions.append(ParsedTransaction(
            ticker="BTC-USD",
            name="Bitcoin",
            type="buy",
            date=txn_date.isoformat(),
            shares=round(shares, 8),
            price_per_share=round(price, 2),
            currency=currency,
            fx_rate_to_chf=1.0,
            fees_chf=round(fees, 2),
            total_chf=round(total_chf, 2),
            order_id=reference,
            import_source="pocket_csv",
            import_batch_id=batch_id,
            suggested_asset_type="crypto",
        ))

    # Summary warnings
    if skipped_deposits > 0:
        warnings.insert(0, f"{skipped_deposits} Einzahlung(en) übersprungen (deposit)")
    if skipped_withdrawals > 0:
        warnings.insert(0, f"{skipped_withdrawals} Auszahlung(en) übersprungen (withdrawal)")
    if skipped_other > 0:
        warnings.insert(0, f"{skipped_other} unbekannte Zeile(n) übersprungen")

    # Enrich: match to existing positions or mark as new
    new_positions = []
    if db is not None and transactions:
        transactions, new_positions = await enrich_transactions(transactions, db, user_id=user_id)

    return ImportPreview(
        source_type="pocket_csv",
        filename=filename,
        total_rows=total_rows,
        transactions=transactions,
        new_positions=new_positions,
        warnings=warnings,
        broker_meta={
            "broker": "Pocket",
            "total_rows": total_rows,
            "exchanges": len(transactions),
            "skipped_deposits": skipped_deposits,
            "skipped_withdrawals": skipped_withdrawals,
        },
    )
