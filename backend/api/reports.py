"""Report-Vault — JWT-Endpoints fuer das UI.

List/Read/Tag/Export/Delete der vom Claude-Finance-Workspace hochgeladenen
Markdown-Briefe. Upload-Pfad (Token, write-Scope) liegt in external_v1.py.
Alles user-scoped (Multi-User).
"""
import logging
import re
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from api.auth import limiter
from api.validation import escape_like
from auth import get_current_user
from config import settings
from constants.limits import MAX_TAGS_PER_REPORT, RL_HEAVY, RL_WRITE
from db import get_db
from models.report import Report
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/reports", tags=["reports"])

# Volltextsuche: ILIKE ueber alle Bodies des Users, ohne Index. Kurzes Muster und
# kurze Laufzeit deckeln die DB-Last einer einzelnen Abfrage. Gleiche Werte wie
# die externe Liste in external_v1.py.
SEARCH_QUERY_MAX_LEN = 64
SEARCH_STATEMENT_TIMEOUT_MS = 3000
_PG_QUERY_CANCELED = "57014"


async def _limit_search_time(db: AsyncSession) -> None:
    """Deckelt die Laufzeit der folgenden Abfragen dieser Transaktion (nur Postgres)."""
    if db.get_bind().dialect.name != "postgresql":
        return
    timeout_ms = SEARCH_STATEMENT_TIMEOUT_MS
    # Ein strengeres DB_STATEMENT_TIMEOUT_MS des Betreibers nicht aufweichen.
    if 0 < settings.db_statement_timeout_ms < timeout_ms:
        timeout_ms = settings.db_statement_timeout_ms
    # SET nimmt keine Bind-Parameter; der Wert ist eine Zahl aus dem Code.
    await db.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))


def _is_statement_timeout(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == _PG_QUERY_CANCELED


def _is_not_pdf_export(request: Request) -> bool:
    return request.query_params.get("format") != "pdf"


class ReportTagsUpdate(BaseModel):
    tags: list[str] = Field(default_factory=list)


def _meta(r: Report) -> dict:
    """Listen-Repraesentation ohne Body (leichtgewichtig)."""
    return {
        "id": str(r.id),
        "category": r.category,
        "title": r.title,
        "report_date": r.report_date.isoformat() if r.report_date else None,
        "tags": r.tags or [],
        "source": r.source,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        "archived_at": r.archived_at.isoformat() if r.archived_at else None,
    }


@router.get("")
@limiter.limit("60/minute")
async def list_reports(
    request: Request,
    category: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=SEARCH_QUERY_MAX_LEN),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    archived: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Reports des Users — gefiltert + paginiert, Metadaten ohne Body.

    Standardmaessig nur **aktive** Reports; `?archived=true` zeigt nur das
    Archiv. `categories`/`all_tags` werden VOR den uebrigen Filtern (aber
    innerhalb des Archiv-Scopes) aufgebaut, damit die UI-Facetten vollstaendig
    bleiben, auch wenn ein Filter sie ausschliesst.
    """
    arch_cond = Report.archived_at.isnot(None) if archived else Report.archived_at.is_(None)

    # Facetten (vor Filter, innerhalb Archiv-Scope) — fuer vollstaendige Dropdowns.
    all_rows = (await db.execute(
        select(Report.category, Report.tags).where(Report.user_id == user.id, arch_cond)
    )).all()
    categories = sorted({(c or "other") for c, _ in all_rows})
    all_tags: set[str] = set()
    for _, tg in all_rows:
        for t in (tg or []):
            all_tags.add(t)

    conds = [Report.user_id == user.id, arch_cond]
    if category:
        conds.append(Report.category == category)
    if q:
        like = f"%{escape_like(q)}%"
        conds.append(or_(
            Report.title.ilike(like, escape="\\"),
            Report.body.ilike(like, escape="\\"),
        ))
    if date_from is not None:
        conds.append(Report.report_date >= date_from)
    if date_to is not None:
        conds.append(Report.report_date <= date_to)

    # Listen-Query OHNE body-Spalte (bis 5000 Markdown-Bodies pro User) —
    # Filter/Sort/Pagination in SQL (Review 2026-07-02, M28).
    stmt = (
        select(Report)
        .options(load_only(
            Report.id, Report.category, Report.title, Report.report_date,
            Report.tags, Report.source, Report.created_at, Report.updated_at,
            Report.archived_at,
        ))
        .where(*conds)
        # Sortierung: report_date desc (NULLs zuletzt), dann created_at desc.
        .order_by(
            desc(Report.report_date).nullslast(),
            desc(Report.created_at).nullslast(),
        )
    )
    start = (page - 1) * per_page

    try:
        await _limit_search_time(db)
        if tag:
            # Tag-Filter in Python (JSONB-Array, portabel ueber SQLite-Tests) —
            # Pagination dann ebenfalls in Python, aber ohne geladene Bodies.
            rows = (await db.execute(stmt)).scalars().all()
            rows = [r for r in rows if tag in (r.tags or [])]
            total = len(rows)
            page_rows = rows[start:start + per_page]
        else:
            total = (
                await db.scalar(select(func.count()).select_from(Report).where(*conds))
            ) or 0
            page_rows = (
                await db.execute(stmt.offset(start).limit(per_page))
            ).scalars().all()
    except DBAPIError as exc:
        if not _is_statement_timeout(exc):
            raise
        # Kein rollback hier: es liesse `user` verfallen, und get_db rollt die
        # abgebrochene Transaktion beim Schliessen der Session ohnehin zurueck.
        logger.warning("Report list query hit the statement timeout (user %s)", user.id)
        raise HTTPException(
            status_code=503,
            detail=(
                "Die Abfrage hat zu lange gedauert und wurde abgebrochen. "
                "Bitte den Suchbegriff oder die Filter enger fassen."
            ),
        )

    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "categories": categories,
        "all_tags": sorted(all_tags),
        "results": [_meta(r) for r in page_rows],
    }


async def _get_owned(db: AsyncSession, report_id: uuid.UUID, user: User) -> Report:
    report = await db.get(Report, report_id)
    if not report or report.user_id != user.id:
        raise HTTPException(status_code=404, detail="Report nicht gefunden")
    return report


@router.get("/{report_id}")
@limiter.limit("60/minute")
async def get_report(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Voller Report inkl. Markdown-Body."""
    report = await _get_owned(db, report_id, user)
    return {**_meta(report), "body": report.body, "source_path": report.source_path}


@router.patch("/{report_id}")
@limiter.limit("30/minute")
async def update_report_tags(
    request: Request,
    report_id: uuid.UUID,
    data: ReportTagsUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Tags eines Reports setzen (user-editiert, wird vom Sync nicht ueberschrieben)."""
    report = await _get_owned(db, report_id, user)
    tags = [str(t).strip()[:50] for t in (data.tags or []) if str(t).strip()]
    # Dedup, Reihenfolge erhalten.
    seen: set[str] = set()
    deduped = [t for t in tags if not (t in seen or seen.add(t))]
    if len(deduped) > MAX_TAGS_PER_REPORT:
        raise HTTPException(status_code=422, detail=f"Maximal {MAX_TAGS_PER_REPORT} Tags pro Report")
    report.tags = deduped
    await db.commit()
    return {"id": str(report.id), "tags": deduped}


@router.get("/{report_id}/export")
@limiter.limit(RL_WRITE)
# Das PDF kostet bis zu PDF_CPU_SECONDS Rechenzeit, der Markdown-Download nichts.
@limiter.limit(RL_HEAVY, exempt_when=_is_not_pdf_export)
async def export_report(
    request: Request,
    report_id: uuid.UUID,
    format: str = Query("md", pattern="^(md|pdf)$"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Report als Markdown- oder gebrandetes PDF-Datei zum Download."""
    report = await _get_owned(db, report_id, user)
    # Dateiname aus Datum + Titel-Slug.
    slug = re.sub(r"[^a-z0-9]+", "-", (report.title or "report").lower()).strip("-")[:60] or "report"
    prefix = report.report_date.isoformat() if report.report_date else "report"

    if format == "pdf":
        # Der Body ist Fremdtext und WeasyPrint rechnet ohne eigene Grenze: das
        # Rendering laeuft in einem Kindprozess mit CPU- und Speichergrenze,
        # hoechstens eines je User (Vollreview 11/2026, K027).
        from services.report_pdf_service import (
            ReportPdfBusyError,
            ReportPdfLimitError,
            render_report_pdf_isolated,
        )
        try:
            pdf = await render_report_pdf_isolated(
                user_id=user.id,
                title=report.title or "Report",
                category=report.category,
                report_date=report.report_date,
                source=report.source,
                body_md=report.body or "",
            )
        except ReportPdfBusyError as exc:
            if exc.per_user:
                raise HTTPException(
                    status_code=429,
                    detail="Es läuft bereits ein PDF-Export. Bitte warten, bis er fertig ist.",
                )
            raise HTTPException(
                status_code=503,
                detail="Die PDF-Erzeugung ist gerade ausgelastet. Bitte in Kürze erneut versuchen.",
                headers={"Retry-After": "10"},
            )
        except ReportPdfLimitError as exc:
            logger.warning("PDF rendering for report %s stopped at a limit: %s", report_id, exc)
            raise HTTPException(
                status_code=422,
                detail=(
                    "Der Report ist zu gross oder zu komplex für den PDF-Export. "
                    "Der Markdown-Export funktioniert weiterhin."
                ),
            )
        except Exception:
            logger.exception("PDF rendering failed for report %s", report_id)
            raise HTTPException(status_code=500, detail="PDF-Erzeugung fehlgeschlagen")
        return Response(
            content=pdf,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{prefix}_{slug}.pdf"'},
        )

    filename = f"{prefix}_{slug}.md"
    return Response(
        content=report.body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{report_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_report(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Report loeschen."""
    report = await _get_owned(db, report_id, user)
    await db.delete(report)
    await db.commit()
    return Response(status_code=204)
