"""Parser for Pocket (pocketbitcoin.com) CSV exports.

Pocket is a Swiss Bitcoin exchange. CSV format:
- Encoding: UTF-8
- Delimiter: Komma ODER Semikolon — Pocket hat das Format gewechselt, beide
  kommen vor. Wird pro Datei ermittelt, siehe _pocket_reader().
- Spalten: type, date, reference, price.currency, price.amount, cost.currency,
  cost.amount, fee.currency, fee.amount, value.currency, value.amount
- Row types: deposit (CHF bank transfer), exchange (BTC buy), withdrawal (BTC wallet transfer)

Was importiert wird:
- 'exchange' -> Kauf. fee.amount ist hier die Servicegebuehr in CHF.
- 'withdrawal' -> NUR die Netzwerkgebuehr als Abgang. Bei einer Abhebung auf die
  eigene Wallet wechseln die Bitcoin nur den Aufbewahrungsort, sie verlassen den
  Besitz nicht — verloren geht ausschliesslich die Miner-Gebuehr (fee.amount in
  BTC). Ohne diese Buchung laeuft der Bestand in OpenFolio dauerhaft ueber dem
  tatsaechlichen Wallet-Guthaben.
- 'deposit' -> uebersprungen (reine CHF-Einzahlung).
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


def _pocket_reader(text: str) -> csv.DictReader:
    """Reader mit dem Delimiter, unter dem die Datei wirklich ein Pocket-Export ist.

    Pocket lieferte frueher semikolongetrennt; aktuelle Exporte (belegt an einem
    echten Export vom 30.07.2026) sind kommagetrennt. Ein fest verdrahtetes
    Trennzeichen liess den Import deshalb still auf null Transaktionen laufen:
    jede Zeile wurde zu einer einzigen Spalte, `type` blieb leer und alle Zeilen
    fielen als "unbekannt" heraus — ohne Hinweis auf die Ursache.

    Statt zu raten oder dem csv.Sniffer zu vertrauen (der bei Betragsfeldern mit
    Komma danebenliegen kann) wird das Trennzeichen genommen, unter dem die
    Pocket-Pflichtspalten tatsaechlich erscheinen. Das ist deterministisch und
    deckt beide Formate ab.
    """
    fallback: csv.DictReader | None = None
    for delimiter in (",", ";"):
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        if fallback is None:
            fallback = reader
        if reader.fieldnames and detect_pocket(reader.fieldnames):
            return reader
    return fallback


async def parse_pocket_csv(text: str, filename: str, db: AsyncSession | None = None, user_id: uuid.UUID | None = None) -> ImportPreview:
    """Parse Pocket CSV into ImportPreview.

    'exchange' rows become BTC purchases. 'withdrawal' rows contribute only their
    network fee (see below). 'deposit' rows are skipped.
    """
    reader = _pocket_reader(text)
    if not reader or not reader.fieldnames:
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
    network_fee_btc = 0.0
    network_fee_rows = 0

    for i, row in enumerate(reader, start=2):
        total_rows += 1
        row_type = get(row, "type").lower()

        if row_type == "deposit":
            skipped_deposits += 1
            continue
        if row_type == "withdrawal":
            # Von einer Abhebung ist nur die Netzwerkgebuehr ein echter Abgang —
            # der Rest wechselt bloss in die eigene Wallet (siehe Modul-Docstring).
            # Gegenprobe am echten Export: exchange 0.00945167 BTC =
            # withdrawal 0.00945136 + fee 0.00000031.
            fee_currency = get(row, "fee.currency").upper()
            fee_amount = _safe_float(get(row, "fee.amount"))
            wd_date = _parse_pocket_date(get(row, "date"))
            if fee_currency == "BTC" and fee_amount > 0 and wd_date:
                transactions.append(ParsedTransaction(
                    ticker="BTC-USD",
                    name="Bitcoin",
                    type="delivery_out",
                    date=wd_date.isoformat(),
                    shares=round(fee_amount, 8),
                    price_per_share=0.0,
                    currency="CHF",
                    fx_rate_to_chf=1.0,
                    fees_chf=0.0,
                    total_chf=0.0,
                    notes="Bitcoin-Netzwerkgebühr (Pocket-Abhebung)",
                    # Abhebungen tragen im Export keine Referenz. Ohne eigene Kennung
                    # greift die Duplikatspruefung auf (Datum, Typ, Betrag) zurueck —
                    # und weil jeder Gebuehren-Abgang total_chf=0 hat, wuerden zwei
                    # Abhebungen am selben Tag als Duplikat gelten und die zweite
                    # stillschweigend wegfallen. Datum + Gebuehrenhoehe macht sie
                    # wieder unterscheidbar, ohne die Wiedererkennung beim erneuten
                    # Import derselben Datei zu verlieren.
                    order_id=f"pocket-fee-{wd_date.isoformat()}-{fee_amount:.8f}",
                    import_source="pocket_csv",
                    import_batch_id=batch_id,
                    suggested_asset_type="crypto",
                ))
                network_fee_btc += fee_amount
                network_fee_rows += 1
            else:
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
    if network_fee_rows > 0:
        warnings.insert(
            0,
            f"{network_fee_rows} Abhebung(en): {network_fee_btc:.8f} BTC Netzwerkgebühren "
            f"als Abgang erfasst. Die abgehobenen Bitcoin selbst bleiben im Bestand — "
            f"nur die Miner-Gebühr verlässt ihn.",
        )
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
            "exchanges": len(transactions) - network_fee_rows,
            "skipped_deposits": skipped_deposits,
            "skipped_withdrawals": skipped_withdrawals,
            "network_fee_rows": network_fee_rows,
            "network_fee_btc": round(network_fee_btc, 8),
        },
    )
