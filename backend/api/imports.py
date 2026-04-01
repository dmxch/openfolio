import asyncio
import logging
import os
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import func, select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from db import get_db, async_session
from models.user import User
from api.portfolio import invalidate_portfolio_cache
from services.import_service import (
    ImportPreview,
    confirm_import,
    parse_csv,
)
from services.recalculate_service import recalculate_all_positions
from api.auth import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/import", tags=["import"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {".csv"}
UPLOAD_DIR = "/app/data/imports"


def _is_relai_csv(headers: list[str]) -> bool:
    """Detect Relai CSV by checking for key columns."""
    required = {"Date", "Transaction Type", "BTC Amount", "BTC Price", "Currency Pair", "Operation ID"}
    return required.issubset(set(headers))


def _get_extension(filename: str) -> str:
    return ("." + filename.rsplit(".", 1)[-1]).lower() if "." in filename else ""


@router.post("/parse", response_model=ImportPreview)
@limiter.limit("10/minute")
async def parse_file(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Upload and parse a CSV file into an ImportPreview."""
    ext = _get_extension(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Nur CSV-Dateien erlaubt")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Datei zu gross (max. 10 MB)")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Datei ist leer")

    try:
        return await parse_csv(content, file.filename, db, user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error(f"File parsing failed for {file.filename}: {e}")
        raise HTTPException(status_code=502, detail="Verarbeitung fehlgeschlagen")


class CsvRemapRequest(BaseModel):
    mapping: dict[str, str]


@router.post("/parse-csv-remap", response_model=ImportPreview)
@limiter.limit("10/minute")
async def parse_csv_remap(
    request: Request,
    file: UploadFile = File(...),
    mapping: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-parse a CSV file with a user-specified column mapping."""
    import json as json_mod

    ext = _get_extension(file.filename or "")
    if ext != ".csv":
        raise HTTPException(status_code=400, detail="Nur CSV-Dateien erlaubt")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Datei zu gross (max. 10 MB)")

    try:
        user_mapping = json_mod.loads(mapping) if mapping else None
    except json_mod.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Ungültiges Mapping-JSON")

    try:
        return await parse_csv(content, file.filename, db, user_mapping=user_mapping, user_id=user.id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class ConfirmRequest(BaseModel):
    transactions: list[dict] = Field(max_length=5000)
    new_positions: list[dict] = Field(default=[], max_length=500)
    fx_transactions: list[dict] = Field(default=[], max_length=5000)


@router.post("/confirm", status_code=201)
@limiter.limit("3/minute")
async def confirm(request: Request, data: ConfirmRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Confirm and bulk-insert parsed transactions."""
    try:
        result = await confirm_import(
            data.transactions, data.new_positions, db, user.id,
            fx_transactions=data.fx_transactions,
        )
        # Recalculate all positions from transaction history to ensure correct cost_basis_chf
        recalc_results = await recalculate_all_positions(db, user_id=user.id)
        recalc_count = len([r for r in recalc_results if "error" not in r])
        result["recalculated_positions"] = recalc_count
        logger.info(f"Recalculated {recalc_count} positions after import for user {user.id}")

        # Regenerate portfolio snapshots in background (needs own DB session)
        async def _regenerate_bg(uid):
            from services.snapshot_service import regenerate_snapshots
            try:
                async with async_session() as bg_db:
                    res = await regenerate_snapshots(bg_db, uid)
                    logger.info(f"Background snapshot regeneration done: {res}")
            except Exception as exc:
                logger.error(f"Background snapshot regeneration failed: {exc}")

        asyncio.create_task(_regenerate_bg(user.id))
        invalidate_portfolio_cache(str(user.id))
        return result
    except Exception as e:
        logger.error(f"Import confirmation failed: {e}")
        raise HTTPException(status_code=500, detail="Import fehlgeschlagen")


# --- CSV Analysis Endpoint ---


@router.post("/analyze")
@limiter.limit("10/minute")
async def analyze_csv(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Analyze CSV structure: encoding, delimiter, headers, broker detection."""
    ext = _get_extension(file.filename or "")
    if ext != ".csv":
        raise HTTPException(400, "Nur CSV-Dateien erlaubt")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(400, "Datei zu gross (max. 10 MB)")
    if not content:
        raise HTTPException(400, "Datei ist leer")

    # Detect encoding
    text = None
    detected_encoding = "utf-8"
    for enc in ["utf-8", "latin-1", "cp1252"]:
        try:
            text = content.decode(enc)
            detected_encoding = enc
            break
        except UnicodeDecodeError:
            logger.debug(f"Encoding {enc} failed for CSV detection, trying next")
            continue
    if text is None:
        raise HTTPException(422, "Encoding nicht erkennbar")

    # Detect delimiter
    import csv as csv_mod
    try:
        dialect = csv_mod.Sniffer().sniff(text[:4000])
        delimiter = dialect.delimiter
    except csv_mod.Error as e:
        logger.debug(f"CSV sniffer failed, falling back to delimiter heuristic: {e}")
        delimiter = "," if text.count(",") > text.count(";") else ";"

    # Read headers and sample rows
    import io
    reader = csv_mod.reader(io.StringIO(text), delimiter=delimiter)
    rows_raw = list(reader)
    if not rows_raw:
        raise HTTPException(422, "CSV enthält keine Daten")

    headers = [h.strip() for h in rows_raw[0]]
    sample_rows = rows_raw[1:6]  # first 5 data rows
    row_count = len(rows_raw) - 1  # exclude header

    # Auto-detect broker (order: Swissquote → IBKR → Pocket → Relai)
    from services.swissquote_parser import is_swissquote_csv
    from services.ibkr_parser import detect_ibkr
    from services.pocket_parser import detect_pocket
    detected_broker = None
    if is_swissquote_csv(headers):
        detected_broker = "swissquote"
    elif detect_ibkr(headers):
        detected_broker = "interactive_brokers"
    elif detect_pocket(headers):
        detected_broker = "pocket"
    elif _is_relai_csv(headers):
        detected_broker = "relai"

    # Build suggested column mapping
    from services.import_service import _auto_detect_mapping, TYPE_ALIASES
    suggested_mapping = _auto_detect_mapping(headers)

    # Swissquote-specific mapping override
    if detected_broker == "swissquote":
        suggested_mapping = {
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
    elif detected_broker == "interactive_brokers":
        suggested_mapping = {
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
    elif detected_broker == "pocket":
        suggested_mapping = {
            "date": "date",
            "type": "type",
            "shares": "value.amount",
            "price_per_share": "price.amount",
            "currency": "price.currency",
            "fees_chf": "fee.amount",
            "total_chf": "cost.amount",
            "order_id": "reference",
        }
    elif detected_broker == "relai":
        suggested_mapping = {
            "date": "Date",
            "type": "Transaction Type",
            "shares": "BTC Amount",
            "price_per_share": "BTC Price",
            "currency": "Fiat Currency",
            "fees_chf": "Fee",
            "total_chf": "Fiat Amount (excl. fees)",
            "order_id": "Operation ID",
        }

    # Extract unique type values from the type column
    type_col = suggested_mapping.get("type")
    unique_types = {}
    if type_col:
        type_col_idx = headers.index(type_col) if type_col in headers else None
        if type_col_idx is not None:
            for row in rows_raw[1:]:
                if type_col_idx < len(row):
                    val = row[type_col_idx].strip()
                    if val:
                        unique_types[val] = unique_types.get(val, 0) + 1

    # Build suggested type mapping from TYPE_ALIASES
    suggested_type_mapping = {}
    if detected_broker == "swissquote":
        suggested_type_mapping = {
            "Kauf": "buy", "Verkauf": "sell", "Dividende": "dividend",
            "Capital Gain": "capital_gain", "Forex-Gutschrift": "fx_credit",
            "Forex-Belastung": "fx_debit", "Fx-Gutschrift Comp.": "fx_credit",
            "Fx-Belastung Comp.": "fx_debit", "Berichtigung Börsengeb.": "fee_correction",
            "Depotgebühren": "fee", "Spesen Steuerauszug": "fee",
            "Zahlung": "deposit", "Auszahlung": "withdrawal",
            "Zinsen auf Einlagen": "interest", "Zinsen auf Belastungen": "interest",
        }
    elif detected_broker == "interactive_brokers":
        suggested_type_mapping = {
            "BUY": "buy", "SELL": "sell",
        }
    elif detected_broker == "pocket":
        suggested_type_mapping = {
            "exchange": "buy",
            "deposit": "skip",
            "withdrawal": "skip",
        }
    elif detected_broker == "relai":
        suggested_type_mapping = {
            "Buy": "buy",
            "Sell": "sell",
        }
    else:
        for val in unique_types:
            val_lower = val.strip().lower()
            matched = None
            for canonical, aliases in TYPE_ALIASES.items():
                if val_lower in aliases:
                    matched = canonical
                    break
            suggested_type_mapping[val] = matched or "skip"

    # Auto-detect date format from sample data
    date_col = suggested_mapping.get("date")
    detected_date_format = None
    if date_col and date_col in headers:
        date_idx = headers.index(date_col)
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
        for row in sample_rows[:3]:
            if date_idx < len(row) and row[date_idx].strip():
                from datetime import datetime as dt
                for fmt, label in DATE_FORMATS:
                    try:
                        dt.strptime(row[date_idx].strip(), fmt)
                        detected_date_format = label
                        break
                    except ValueError:
                        continue  # Expected: trying multiple date formats
                if detected_date_format:
                    break

    # Save file temporarily
    upload_id = str(uuid.uuid4())
    user_dir = os.path.join(UPLOAD_DIR, str(user.id))
    os.makedirs(user_dir, exist_ok=True)

    # Clean up old files (>30 min)
    now = time.time()
    for f in os.listdir(user_dir):
        fp = os.path.join(user_dir, f)
        if os.path.isfile(fp) and now - os.path.getmtime(fp) > 1800:
            os.remove(fp)

    with open(os.path.join(user_dir, f"{upload_id}.csv"), "wb") as f:
        f.write(content)

    # Load user's saved profiles
    from models.import_profile import ImportProfile
    result = await db.execute(
        sa_select(ImportProfile).where(ImportProfile.user_id == user.id).order_by(ImportProfile.name)
    )
    profiles = result.scalars().all()
    saved_profiles = [
        {"id": str(p.id), "name": p.name}
        for p in profiles
    ]

    # Broker defaults
    broker_defaults = None
    if detected_broker in ("relai", "pocket"):
        broker_defaults = {"ticker": "BTC-USD", "asset_class": "crypto", "fx_rate": 1.0, "coingecko_id": "bitcoin", "price_source": "coingecko"}

    return {
        "upload_id": upload_id,
        "filename": file.filename,
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


# --- Parse with User Mapping ---


class ParseWithMappingRequest(BaseModel):
    upload_id: str
    column_mapping: dict[str, str]  # OpenFolio field -> CSV column name
    type_mapping: dict[str, str]    # CSV type value -> OpenFolio type
    date_format: str = "DD-MM-YYYY HH:MM:SS"
    has_forex_pairs: bool = False
    aggregate_partial_fills: bool = True
    profile_id: str | None = None  # Load mapping from saved profile instead
    broker_defaults: dict | None = None  # {"ticker": "BTC-USD", "asset_class": "crypto", "fx_rate": 1.0}
    total_chf_formula: str = "standard"  # "standard" or "net_amount_plus_fees"


@router.post("/parse-with-mapping", response_model=ImportPreview)
@limiter.limit("10/minute")
async def parse_with_mapping(
    request: Request,
    data: ParseWithMappingRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Parse a previously uploaded CSV using explicit column and type mappings."""
    # Validate upload_id is a valid UUID to prevent path traversal
    try:
        uuid.UUID(data.upload_id)
    except ValueError:
        raise HTTPException(400, "Ungültige Upload-ID")

    # Load file from temp storage
    user_dir = os.path.join(UPLOAD_DIR, str(user.id))
    filepath = os.path.join(user_dir, f"{data.upload_id}.csv")

    # Verify resolved path stays within expected directory
    real_path = os.path.realpath(filepath)
    real_user_dir = os.path.realpath(user_dir)
    if not real_path.startswith(real_user_dir + os.sep):
        raise HTTPException(400, "Ungültige Upload-ID")

    if not os.path.exists(filepath):
        raise HTTPException(404, "Upload nicht gefunden. Bitte CSV erneut hochladen.")

    with open(filepath, "rb") as f:
        content = f.read()

    # If profile_id is provided, load mappings from profile
    column_mapping = data.column_mapping
    type_mapping = data.type_mapping
    if data.profile_id:
        from models.import_profile import ImportProfile
        profile = await db.get(ImportProfile, uuid.UUID(data.profile_id))
        if profile and profile.user_id == user.id:
            column_mapping = profile.column_mapping
            type_mapping = profile.type_mapping

    # Check if Swissquote format and forex pairs enabled
    if data.has_forex_pairs:
        # Use Swissquote parser for Forex pair handling
        # Detect encoding first
        text = None
        for enc in ["utf-8", "latin-1", "cp1252"]:
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                logger.debug(f"Encoding {enc} failed for Swissquote detection, trying next")
                continue
        if text is None:
            raise HTTPException(422, "Encoding nicht erkennbar")

        from services.swissquote_parser import is_swissquote_csv, parse_swissquote_csv
        # Check if it's actually Swissquote format
        import csv as csv_mod, io
        reader = csv_mod.reader(io.StringIO(text), delimiter=";")
        first_row = next(reader, None)
        if first_row and is_swissquote_csv([h.strip() for h in first_row]):
            try:
                return await parse_swissquote_csv(text, f"upload_{data.upload_id}", db, user_id=user.id)
            except Exception as e:
                raise HTTPException(422, str(e))

    # Generic CSV parsing with explicit mapping
    try:
        return await parse_csv(
            content, f"upload_{data.upload_id}.csv", db,
            user_mapping=column_mapping,
            user_id=user.id,
            type_mapping=type_mapping,
            broker_defaults=data.broker_defaults,
            total_chf_formula=data.total_chf_formula,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


# --- Import Profile CRUD ---


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    column_mapping: dict
    type_mapping: dict
    delimiter: str = Field(default=",", max_length=1)
    encoding: str = Field(default="utf-8", max_length=20)
    date_format: str = Field(default="DD-MM-YYYY HH:MM:SS", max_length=50)
    decimal_separator: str = Field(default=".", max_length=1)
    has_forex_pairs: bool = False
    aggregate_partial_fills: bool = True


@router.get("/profiles")
async def list_profiles(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from models.import_profile import ImportProfile
    result = await db.execute(
        sa_select(ImportProfile).where(ImportProfile.user_id == user.id).order_by(ImportProfile.name)
    )
    profiles = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "name": p.name,
            "column_mapping": p.column_mapping,
            "type_mapping": p.type_mapping,
            "delimiter": p.delimiter,
            "encoding": p.encoding,
            "date_format": p.date_format,
            "decimal_separator": p.decimal_separator,
            "has_forex_pairs": p.has_forex_pairs,
            "aggregate_partial_fills": p.aggregate_partial_fills,
        }
        for p in profiles
    ]


@router.post("/profiles", status_code=201)
@limiter.limit("30/minute")
async def create_profile(request: Request, data: ProfileCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from models.import_profile import ImportProfile
    from constants.limits import MAX_IMPORT_PROFILES_PER_USER
    # Per-user limit
    count_result = await db.execute(
        sa_select(func.count()).select_from(ImportProfile).where(ImportProfile.user_id == user.id)
    )
    if (count_result.scalar() or 0) >= MAX_IMPORT_PROFILES_PER_USER:
        raise HTTPException(400, f"Limit erreicht (max. {MAX_IMPORT_PROFILES_PER_USER} Import-Profile)")
    profile = ImportProfile(
        user_id=user.id,
        name=data.name,
        column_mapping=data.column_mapping,
        type_mapping=data.type_mapping,
        delimiter=data.delimiter,
        encoding=data.encoding,
        date_format=data.date_format,
        decimal_separator=data.decimal_separator,
        has_forex_pairs=data.has_forex_pairs,
        aggregate_partial_fills=data.aggregate_partial_fills,
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return {"id": str(profile.id), "name": profile.name}


@router.delete("/profiles/{profile_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_profile(request: Request, profile_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    from models.import_profile import ImportProfile
    profile = await db.get(ImportProfile, profile_id)
    if not profile or profile.user_id != user.id:
        raise HTTPException(404, "Profil nicht gefunden")
    await db.delete(profile)
    await db.commit()
