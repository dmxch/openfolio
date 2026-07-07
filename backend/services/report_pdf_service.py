"""Server-seitiges, gebrandetes PDF-Rendering fuer Report-Vault-Briefe.

markdown -> gebrandetes HTML (Logo-Masthead + laufender Kopf + seiten-nummerierter
Fuss) -> PDF via WeasyPrint. Der WeasyPrint-Import ist LAZY (schwere native Libs
pango/cairo): so bleibt der Modul-Import billig und eine fehlende native Lib
betrifft nur den PDF-Pfad, nicht den App-Start.

Der Renderer ist rein praesentativ und beruehrt keine Report-Daten/Definitionen.
"""
from __future__ import annotations

import html as _html
from datetime import date

import markdown as _md

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
        extensions=["extra", "sane_lists"],
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


def render_report_pdf(*, title: str, category: str | None, report_date: date | None,
                      source: str | None, body_md: str) -> bytes:
    """Rendert einen Report als gebrandetes PDF (bytes). WeasyPrint lazy importiert."""
    from weasyprint import HTML  # lazy: schwere native Libs (pango/cairo)

    doc_html = _render_html(
        title=title, category=category, report_date=report_date,
        source=source, body_md=body_md,
    )
    return HTML(string=doc_html).write_pdf()
