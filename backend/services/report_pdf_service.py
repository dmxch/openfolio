"""Server-seitiges, gebrandetes PDF-Rendering fuer Report-Vault-Briefe.

markdown -> gebrandetes HTML (Logo-Masthead + laufender Kopf + seiten-nummerierter
Fuss) -> PDF via WeasyPrint. Der WeasyPrint-Import ist LAZY (schwere native Libs
pango/cairo): so bleibt der Modul-Import billig und eine fehlende native Lib
betrifft nur den PDF-Pfad, nicht den App-Start.

Der Renderer ist rein praesentativ und beruehrt keine Report-Daten/Definitionen.

Der Report-Body ist Fremdtext. Die API rendert deshalb nie im eigenen Prozess,
sondern ueber ``render_report_pdf_isolated``: ein Kindprozess mit CPU- und
Speichergrenze, hoechstens ein Rendering je Nutzer und ``MAX_PARALLEL_RENDERS``
je Prozess. Dieses Modul ist zugleich das Programm des Kindprozesses
(``python -m services.report_pdf_service``) und importiert deshalb auf
Modulebene nichts aus der App.
"""
from __future__ import annotations

import contextlib
import html as _html
import json
import os
import sys
import uuid
from datetime import date
from pathlib import Path

import markdown as _md
from markdown.extensions import Extension

# --- Grenzen des isolierten Renderings ---
#
# Gemessen im Backend-Container (WeasyPrint 69.0, 13.11.2026): 200 kB Fliesstext
# mit kleinen Tabellen rechnen rund 9 s. Eine einzige Tabelle mit 200 kB erreicht
# beide Grenzen nach rund 20 s; ohne Grenze waeren es 71 s und 2,7 GB.
PDF_CPU_SECONDS = 20
PDF_MEMORY_BYTES = 1024 ** 3
# Wanduhr ueber der CPU-Grenze: sie greift nur, wenn der Kindprozess nicht rechnet.
PDF_WALL_SECONDS = 30
PDF_SLOT_WAIT_SECONDS = 10
# Je Prozess. uvicorn laeuft mit zwei Workern, zusammen rendern also hoechstens
# zwei Kindprozesse: 2 x PDF_MEMORY_BYTES bleibt unter dem 4-GB-Limit des Containers.
MAX_PARALLEL_RENDERS = 1

_EXIT_MEMORY = 3
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
# Der Kindprozess liest Fremdtext und bekommt deshalb weder Schluessel noch DB-URL.
_CHILD_ENV_KEYS = (
    "PATH", "PYTHONPATH", "PYTHONDONTWRITEBYTECODE", "HOME", "LANG", "LC_ALL", "TZ",
    "TMPDIR", "XDG_CACHE_HOME", "FONTCONFIG_PATH", "FONTCONFIG_FILE", "LD_LIBRARY_PATH",
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"

# ``extra`` ohne ``attr_list`` und ``md_in_html``: ``attr_list`` setzt beliebige
# Attribute, also auch ``style``, und ``md_in_html`` gibt es nur fuer rohes HTML.
_MD_EXTENSIONS = ["abbr", "def_list", "fenced_code", "footnotes", "tables", "sane_lists"]


class ReportPdfError(Exception):
    """Das PDF-Rendering ist gescheitert."""


class ReportPdfLimitError(ReportPdfError):
    """Das Rendering hat die CPU-, Speicher- oder Zeitgrenze erreicht."""


class ReportPdfBusyError(ReportPdfError):
    """Kein Rendering frei: ``per_user`` sagt, ob der Nutzer selbst schon rendert."""

    def __init__(self, *, per_user: bool) -> None:
        super().__init__("user already renders" if per_user else "no render slot free")
        self.per_user = per_user


class _NoRawHtml(Extension):
    """Rohes HTML bleibt Text: ohne diese zwei Bausteine escapt der Serializer es.

    Der Viewer im Frontend (react-markdown ohne rehype-raw) rendert rohes HTML
    auch nicht. Im PDF waere es der Hebel fuer teures Layout (verschachteltes
    ``display:flex``) und fuer ``<img>`` mit beliebigem Bildformat.
    """

    def extendMarkdown(self, md: _md.Markdown) -> None:
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")


# Brand-Tokens (identisch zum Frontend-Logo / Design-System).
_ACCENT_A = "#5b8def"
_ACCENT_B = "#29c3b1"
_INK = "#1b1f27"
_MUTED = "#6b7787"

# Kategorie-Slugs -> DE-Anzeige (Spiegel von frontend Reports.jsx CATEGORY_LABELS).
_CATEGORY_LABELS = {
    "daily_brief": "Daily Brief",
    "weekly_check": "Weekly Check",
    "trade": "Trade-Plan",
    "earnings": "Earnings",
    "institutional_flow": "Institutional Flow",
    "macro": "Makro",
    "review": "Review",
    "strategy": "Strategie",
    "decision": "Decision",
    "quarterly_review": "Quartals-Review",
    "concept": "Konzept",
    "discovery": "Discovery",
    "sektor_only": "Sektor",
    "other": "Sonstiges",
}

# Offener-Ring-Mark (identisch zur favicon.svg-Geometrie, Gradient Blau->Teal).
_LOGO_SVG = (
    '<svg width="30" height="30" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="ofpdf" x1="0" y1="0" x2="1" y2="1">'
    f'<stop offset="0%" stop-color="{_ACCENT_A}"/><stop offset="100%" stop-color="{_ACCENT_B}"/>'
    '</linearGradient></defs>'
    '<rect x="0" y="0" width="100" height="100" rx="24" fill="url(#ofpdf)"/>'
    '<g transform="translate(18,18) scale(0.64)">'
    '<circle cx="50" cy="50" r="32" fill="none" stroke="#ffffff" stroke-width="12" '
    'stroke-linecap="round" stroke-dasharray="166 48" transform="rotate(-52 50 50)"/>'
    '<circle cx="76" cy="33" r="6.5" fill="#ffffff"/></g></svg>'
)


def _category_label(category: str | None) -> str:
    if not category:
        return "Report"
    return _CATEGORY_LABELS.get(category, category.replace("_", " ").title())


def _fmt_date(d: date | None) -> str:
    return d.strftime("%d.%m.%Y") if d else ""


def _stylesheet() -> str:
    return f"""
    @page {{
      size: A4;
      margin: 2.3cm 1.9cm 1.8cm;
      @top-right {{
        content: element(runhead);
        vertical-align: bottom; padding-bottom: 6pt;
      }}
      @bottom-left {{
        content: "OpenFolio · Report-Vault";
        font: 7.5pt 'DejaVu Sans', sans-serif; color: {_MUTED};
      }}
      @bottom-right {{
        content: "Seite " counter(page) " / " counter(pages);
        font: 7.5pt 'DejaVu Sans', sans-serif; color: {_MUTED};
      }}
    }}
    :root {{ }}
    html {{ font-family: 'DejaVu Sans', sans-serif; color: {_INK}; font-size: 10.5pt; line-height: 1.5; }}
    body {{ margin: 0; }}

    .runhead {{ position: running(runhead); font-size: 8pt; color: {_MUTED}; }}
    .runhead b {{ color: {_INK}; font-weight: 600; }}

    .masthead {{ width: 100%; border-collapse: collapse; margin-bottom: 4pt; }}
    .masthead td {{ vertical-align: middle; border: none; padding: 0; }}
    .brand {{ font-size: 15pt; font-weight: 600; letter-spacing: -0.02em; padding-left: 9pt; }}
    .brand .b1 {{ color: {_INK}; }} .brand .b2 {{ color: {_ACCENT_A}; }}
    .meta {{ text-align: right; font-size: 8.5pt; color: {_MUTED}; }}
    .badge {{
      display: inline-block; font-size: 8pt; font-weight: 600; color: #06140d;
      background: linear-gradient(135deg, {_ACCENT_A}, {_ACCENT_B});
      padding: 2pt 7pt; border-radius: 5pt;
    }}
    .rule {{ height: 2pt; margin: 8pt 0 14pt;
      background: linear-gradient(90deg, {_ACCENT_A}, {_ACCENT_B} 55%, #e6ebf2 55%); }}

    h1.doc-title {{ font-size: 20pt; font-weight: 600; letter-spacing: -0.015em;
      margin: 0 0 14pt; color: #0b0e14; }}

    .body h1 {{ font-size: 15pt; margin: 16pt 0 6pt; color: #0b0e14; }}
    .body h2 {{ font-size: 13pt; margin: 15pt 0 6pt; padding-bottom: 3pt;
      border-bottom: 1px solid #e2e7ee; color: #0b0e14; }}
    .body h3 {{ font-size: 11.5pt; margin: 12pt 0 4pt; color: #0b0e14; }}
    .body h1, .body h2, .body h3 {{ break-after: avoid; font-weight: 600; }}
    .body p, .body li {{ orphans: 2; widows: 2; }}
    .body p {{ margin: 0 0 8pt; }}
    .body ul, .body ol {{ margin: 0 0 8pt; padding-left: 18pt; }}
    .body li {{ margin: 2pt 0; }}
    .body a {{ color: #1a4fd6; text-decoration: none; }}
    .body strong {{ color: #0b0e14; }}
    .body blockquote {{ margin: 8pt 0; padding: 2pt 12pt; border-left: 3px solid #cfd8e6;
      color: #4a5566; break-inside: avoid; }}
    .body code {{ font-family: 'DejaVu Sans Mono', monospace; font-size: 9pt;
      background: #f3f5f8; padding: 1pt 3pt; border-radius: 3pt; }}
    .body pre {{ background: #f3f5f8; border: 1px solid #e2e7ee; border-radius: 6pt;
      padding: 9pt 11pt; font-family: 'DejaVu Sans Mono', monospace; font-size: 8.7pt;
      line-height: 1.45; white-space: pre-wrap; break-inside: avoid; }}
    .body pre code {{ background: none; padding: 0; }}
    .body table {{ border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9pt;
      break-inside: avoid; }}
    .body th, .body td {{ border: 1px solid #dbe1ea; padding: 4pt 7pt; text-align: left; }}
    .body th {{ background: #f3f5f8; font-weight: 600; color: #0b0e14; }}
    .body hr {{ border: none; border-top: 1px solid #e2e7ee; margin: 14pt 0; }}
    """


def _strip_leading_title(body_md: str, title: str) -> str:
    """Entfernt eine fuehrende ``# <Titel>``-Zeile, wenn sie den Doc-Titel
    dupliziert (die Briefe wiederholen ihn oft als erste Markdown-Zeile)."""
    lines = (body_md or "").lstrip("\n").split("\n")
    if lines and lines[0].strip().lower() == f"# {title}".strip().lower():
        return "\n".join(lines[1:]).lstrip("\n")
    return body_md or ""


def _render_html(*, title: str, category: str | None, report_date: date | None,
                 source: str | None, body_md: str) -> str:
    body_html = _md.markdown(
        _strip_leading_title(body_md, title),
        extensions=[*_MD_EXTENSIONS, _NoRawHtml()],
        output_format="html5",
    )
    cat = _html.escape(_category_label(category))
    date_str = _fmt_date(report_date)
    meta_line = " · ".join(x for x in [date_str, _html.escape(source) if source else ""] if x)
    return f"""<!DOCTYPE html>
<html lang="de-CH"><head><meta charset="utf-8"><style>{_stylesheet()}</style></head>
<body>
  <div class="runhead">OpenFolio · <b>{_html.escape(title)}</b></div>
  <table class="masthead"><tr>
    <td style="width:50%">{_LOGO_SVG}<span class="brand"><span class="b1">Open</span><span class="b2">Folio</span></span></td>
    <td class="meta" style="width:50%"><span class="badge">{cat}</span><div style="margin-top:5pt">{_html.escape(meta_line)}</div></td>
  </tr></table>
  <div class="rule"></div>
  <h1 class="doc-title">{_html.escape(title)}</h1>
  <div class="body">{body_html}</div>
</body></html>"""


def _inline_image_fetcher():
    """Fetcher fuer WeasyPrint: nur ``data:``-URIs, deren Inhalt PNG oder JPEG ist.

    WeasyPrint reicht jedes geholte Bild ohne Formatliste an Pillow. Pillow waehlt
    den Decoder nach den ersten Bytes; die Pruefung der Magic-Bytes haelt damit
    alle anderen Decoder (XBM, TIFF, JPEG 2000 ...) vom Fremdtext fern. Der
    deklarierte Medientyp zaehlt nicht, er kommt aus dem Report-Body.
    """
    from weasyprint.urls import URLFetcher, URLFetcherResponse

    class _InlineImageFetcher(URLFetcher):
        def fetch(self, url, headers=None):
            response = super().fetch(url, headers)
            try:
                data = response.read()
            finally:
                response.close()
            if data.startswith(_PNG_MAGIC):
                mime_type = "image/png"
            elif data.startswith(_JPEG_MAGIC):
                mime_type = "image/jpeg"
            else:
                raise ValueError("Only inline PNG or JPEG images are allowed")
            return URLFetcherResponse(response.url, data, {"Content-Type": mime_type})

    # Redirects aus: sonst waere eine erlaubte URL ein Sprungbrett.
    return _InlineImageFetcher(allowed_protocols=("data",), allow_redirects=False, timeout=5)


def _html_to_pdf(doc_html: str) -> bytes:
    from weasyprint import HTML  # lazy: schwere native Libs (pango/cairo)

    return HTML(string=doc_html, url_fetcher=_inline_image_fetcher()).write_pdf()


def render_report_pdf(*, title: str, category: str | None, report_date: date | None,
                      source: str | None, body_md: str) -> bytes:
    """Rendert einen Report als gebrandetes PDF (bytes), im aufrufenden Prozess.

    Ohne Zeit- und Speichergrenze: fuer Fremdtext ``render_report_pdf_isolated``
    verwenden. Der Kindprozess ruft diese Funktion auf.

    Der Report-Body kommt per Write-Token ueber `POST /api/v1/external/reports`.
    Rohes HTML darin wird escapt (``_NoRawHtml``). Bilder in Markdown-Syntax
    bleiben moeglich; ohne eigenen Fetcher wuerde WeasyPrint dafuer holen, was im
    Body steht — `![x](file:///app/.env)` oder `![x](http://db:5432/)` waeren
    LFI/SSRF aus dem Docker-Netz heraus, und OpenFolio ist Multi-User. Der Fetcher
    laesst deshalb nur eingebettete PNG- und JPEG-Bilder zu (das Logo-SVG steht
    inline im HTML). `fail_on_errors` bleibt aus (Default), ein geblocktes Bild
    degradiert also sauber, statt den Export zu killen.
    """
    return _html_to_pdf(_render_html(
        title=title, category=category, report_date=report_date,
        source=source, body_md=body_md,
    ))


# --- Isoliertes Rendering (Elternseite) ---

# Zaehler statt asyncio.Semaphore: der Zaehler haengt an keinem Event-Loop.
_active_renders = 0


async def _acquire_render_slot(wait_seconds: float) -> bool:
    global _active_renders
    import asyncio  # lazy wie unten: spart dem Kindprozess rund 50 ms Startzeit

    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait_seconds
    # Zwischen Pruefung und Erhoehung steht kein await: im Event-Loop ist das atomar.
    while _active_renders >= MAX_PARALLEL_RENDERS:
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.1)
    _active_renders += 1
    return True


def _release_render_slot() -> None:
    global _active_renders
    _active_renders -= 1


def _child_env() -> dict[str, str]:
    return {k: os.environ[k] for k in _CHILD_ENV_KEYS if k in os.environ}


async def _render_in_subprocess(payload: dict, *, cpu_seconds: int, memory_bytes: int,
                                wall_seconds: float) -> bytes:
    import asyncio

    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "services.report_pdf_service",
        str(cpu_seconds), str(memory_bytes),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_BACKEND_ROOT),
        env=_child_env(),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(json.dumps(payload).encode("utf-8")), timeout=wall_seconds,
        )
    except asyncio.TimeoutError:
        raise ReportPdfLimitError(f"wall clock limit of {wall_seconds}s reached") from None
    finally:
        # Auch bei Abbruch des Requests: der Kindprozess darf nicht weiterrechnen.
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()

    code = proc.returncode
    if code == 0 and stdout.startswith(b"%PDF-"):
        return stdout
    # Negativer Code = durch Signal beendet: vom Kernel an der CPU-Grenze oder
    # von einer nativen Bibliothek nach gescheitertem malloc.
    if code < 0 or code == _EXIT_MEMORY:
        raise ReportPdfLimitError(f"renderer stopped at a resource limit (exit code {code})")
    last_line = (stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1][:300]
    raise ReportPdfError(f"renderer failed (exit code {code}): {last_line}")


async def render_report_pdf_isolated(
    *,
    user_id: uuid.UUID | str,
    title: str,
    category: str | None,
    report_date: date | None,
    source: str | None,
    body_md: str,
    cpu_seconds: int = PDF_CPU_SECONDS,
    memory_bytes: int = PDF_MEMORY_BYTES,
    wall_seconds: float = PDF_WALL_SECONDS,
    slot_wait_seconds: float = PDF_SLOT_WAIT_SECONDS,
) -> bytes:
    """Rendert einen Report in einem Kindprozess mit CPU- und Speichergrenze.

    Raises:
        ReportPdfBusyError: der Nutzer rendert schon (``per_user``), oder innert
            ``slot_wait_seconds`` wurde kein Rendering frei.
        ReportPdfLimitError: das Dokument hat eine Grenze erreicht.
        ReportPdfError: jeder andere Fehler des Renderers.
    """
    from services import cache  # lazy: der Kindprozess laedt dieses Modul ohne App

    lock_key = f"report_pdf:{user_id}"
    # Das Lock kennt keinen Besitzer, die TTL muss Warten und Rendern ueberdauern.
    lock_ttl = int(slot_wait_seconds + wall_seconds) + 30
    if not cache.acquire_lock(lock_key, lock_ttl):
        raise ReportPdfBusyError(per_user=True)
    try:
        if not await _acquire_render_slot(slot_wait_seconds):
            raise ReportPdfBusyError(per_user=False)
        try:
            return await _render_in_subprocess(
                {
                    "title": title,
                    "category": category,
                    "report_date": report_date.isoformat() if report_date else None,
                    "source": source,
                    "body_md": body_md,
                },
                cpu_seconds=cpu_seconds, memory_bytes=memory_bytes, wall_seconds=wall_seconds,
            )
        finally:
            _release_render_slot()
    finally:
        cache.release_lock(lock_key)


# --- Kindprozess ---

def _apply_child_limits(cpu_seconds: int, memory_bytes: int) -> None:
    """Setzt die Grenzen im eigenen Prozess, bevor er Fremdtext liest.

    Kein ``preexec_fn`` im Elternprozess: das ist in einem Prozess mit Threads
    nicht sicher. An der CPU-Grenze beendet der Kernel den Prozess per Signal.
    """
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


def _child_main(argv: list[str]) -> int:
    _apply_child_limits(int(argv[0]), int(argv[1]))
    try:
        payload = json.loads(sys.stdin.buffer.read())
        report_date = payload.get("report_date")
        pdf = render_report_pdf(
            title=payload["title"],
            category=payload.get("category"),
            report_date=date.fromisoformat(report_date) if report_date else None,
            source=payload.get("source"),
            body_md=payload.get("body_md") or "",
        )
    except MemoryError:
        return _EXIT_MEMORY
    sys.stdout.buffer.write(pdf)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    # os._exit statt sys.exit: an der Speichergrenze scheitert sonst schon das
    # Abraeumen des Interpreters (gemessen: 5 von 80 Laeufen), und statt
    # _EXIT_MEMORY kaeme Exit-Code 1 zurueck.
    try:
        _code = _child_main(sys.argv[1:])
    except MemoryError:
        _code = _EXIT_MEMORY
    os._exit(_code)
