"""Report-Vault — JWT-Endpoints fuer das UI.

List/Read/Tag/Export/Delete der vom Claude-Finance-Workspace hochgeladenen
Markdown-Briefe. Upload-Pfad (Token, write-Scope) liegt in external_v1.py.
Alles user-scoped (Multi-User).
"""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from api.auth import limiter
from auth import get_current_user
from constants.limits import MAX_TAGS_PER_REPORT
from db import get_db
from models.report import Report
from models.user import User

router = APIRouter(prefix="/api/reports", tags=["reports"])


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
    q: str | None = Query(default=None, max_length=200),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
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
        like = f"%{q}%"
        conds.append(or_(Report.title.ilike(like), Report.body.ilike(like)))
    if date_from:
        conds.append(Report.report_date >= date_from)
    if date_to:
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
@limiter.limit("30/minute")
async def export_report(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Report als Markdown-Datei zum Download."""
    report = await _get_owned(db, report_id, user)
    # Dateiname aus Datum + Titel-Slug.
    slug = re.sub(r"[^a-z0-9]+", "-", (report.title or "report").lower()).strip("-")[:60] or "report"
    prefix = report.report_date.isoformat() if report.report_date else "report"
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
