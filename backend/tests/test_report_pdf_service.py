"""Tests fuer services/report_pdf_service.py (gebrandeter PDF-Export)."""
from datetime import date

from services.report_pdf_service import (
    _category_label,
    _render_html,
    _strip_leading_title,
    render_report_pdf,
)

SAMPLE_MD = """# Weekly Check 2026-07-05

Guten Sonntag,

die ehrliche Sicht steht oben. Portfolio bei **CHF 442'419** (Woche +1.1%).

## Positionen

- CHSPI (+13.5%), EIMI (+8.3%)
- JNJ (+9.9%) — reitet die Rotation

| Ticker | Perf |
|--------|------|
| CHSPI  | +13.5% |
| PEP    | -12.6% |

> Neutrale Status-Mitteilung, keine Handlungsaufforderung.

```
[FINANCE TIME CONTEXT]
Jetzt: Sonntag 2026-07-05 08:04 CEST
```
"""


def test_category_label_maps_known_and_falls_back():
    assert _category_label("weekly_check") == "Weekly Check"
    assert _category_label("some_new_thing") == "Some New Thing"
    assert _category_label(None) == "Report"


def test_strip_leading_title_removes_duplicate_h1():
    body = "# Weekly Check 2026-07-05\n\nGuten Sonntag,\n"
    assert _strip_leading_title(body, "Weekly Check 2026-07-05") == "Guten Sonntag,\n"
    # Nicht-passende erste Ueberschrift bleibt erhalten
    keep = "# Andere Ueberschrift\n\nText"
    assert _strip_leading_title(keep, "Weekly Check 2026-07-05") == keep


def test_render_html_escapes_title_and_renders_markdown():
    html = _render_html(
        title="A <b>& Co",
        category="trade",
        report_date=date(2026, 7, 5),
        source="claude-finance",
        body_md="# H\n\ntext **fett**",
    )
    assert "A &lt;b&gt;&amp; Co" in html          # Titel escaped (kein XSS)
    assert "Trade-Plan" in html                    # Kategorie-Label
    assert "05.07.2026" in html                    # DE-Datum
    assert "<strong>fett</strong>" in html         # Markdown gerendert


def test_render_report_pdf_produces_pdf_bytes():
    pdf = render_report_pdf(
        title="Weekly Check 2026-07-05",
        category="weekly_check",
        report_date=date(2026, 7, 5),
        source="claude-finance",
        body_md=SAMPLE_MD,
    )
    assert isinstance(pdf, bytes)
    assert pdf[:5] == b"%PDF-"      # gueltiges PDF
    assert len(pdf) > 2000          # nicht leer


def test_render_report_pdf_handles_empty_body():
    pdf = render_report_pdf(
        title="Leer", category="other", report_date=None, source=None, body_md=""
    )
    assert pdf[:5] == b"%PDF-"
