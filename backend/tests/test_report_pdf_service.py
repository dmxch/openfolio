"""Tests fuer services/report_pdf_service.py (gebrandeter PDF-Export)."""
import http.server
import threading
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


def test_render_report_pdf_does_not_fetch_network_urls():
    """Report-Bodies sind Fremdtext (Write-Token ueber `POST /api/v1/external/reports`)
    und Markdown `extra` reicht rohes HTML durch. Ohne restriktiven url_fetcher wuerde
    WeasyPrint beim Rendern aufloesen, was im Body steht — SSRF aus dem Docker-Netz.

    Beweisfuehrung ueber einen echten lokalen Listener statt ueber PDF-Inhalt: ein
    `<img>`, das auf eine Textantwort zeigt, wuerde ohnehin nicht gerendert. Nur die
    Frage "ist ein Request rausgegangen?" trennt Fetcher-aktiv von Fetcher-inaktiv.
    """
    hits = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(b"\x89PNG\r\n\x1a\n")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        pdf = render_report_pdf(
            title="SSRF-Probe",
            category="other",
            report_date=date(2026, 7, 27),
            source=None,
            body_md=(
                f'Netz: <img src="http://127.0.0.1:{port}/geholt.png">\n\n'
                'Lokal: <img src="file:///etc/hostname">\n'
            ),
        )
    finally:
        srv.shutdown()
        srv.server_close()

    assert pdf[:5] == b"%PDF-"          # geblockte Ressource killt den Export nicht
    assert hits == [], f"WeasyPrint hat trotz url_fetcher geladen: {hits}"


def test_render_report_pdf_still_renders_embedded_data_uri():
    """Gegenprobe zum Fetcher: data:-URIs muessen weiterhin durchgehen, sonst
    waere das eingebettete Logo mitgeblockt."""
    px = (
        "data:image/gif;base64,"
        "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
    )
    pdf = render_report_pdf(
        title="Data-URI", category="other", report_date=None, source=None,
        body_md=f'<img src="{px}">',
    )
    assert pdf[:5] == b"%PDF-"


def test_render_report_pdf_handles_empty_body():
    pdf = render_report_pdf(
        title="Leer", category="other", report_date=None, source=None, body_md=""
    )
    assert pdf[:5] == b"%PDF-"
