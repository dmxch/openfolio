"""Guards fuer yf_patch.py gegen die stillen Bruchstellen des yfinance-1.x-Ports.

Netzfrei: prueft nur, WOMIT yfinance sprechen wuerde, nicht ob Yahoo antwortet.
Genau diese Eigenschaften brechen bei einem Upgrade lautlos — kein Fehler, keine
Warnung, nur langsam veraltende Kurse bzw. dauerhaft leere Earnings.
"""
import importlib.util

import yf_patch  # noqa: F401 — Import hat Seiteneffekte (Logger, Warnfilter)
import yfinance.data as yfdata


def test_no_dead_user_agent_patch():
    """Bis yfinance 0.2.x setzte yf_patch `YfData.user_agent_headers`. Ab 1.x gibt
    es das Attribut nicht mehr — ein Zuweisen waere ein stiller No-op gewesen.
    Taucht es je wieder auf, ist entweder yfinance zurueckgerollt oder jemand hat
    den toten Patch guten Glaubens reanimiert."""
    assert not hasattr(yfdata.YfData, "user_agent_headers"), (
        "YfData.user_agent_headers existiert wieder — yf_patch-Annahmen pruefen"
    )


def test_yfinance_uses_impersonating_session():
    """DER entscheidende Guard: yfinance 1.x spricht ueber curl_cffi und imitiert
    einen Browser bis auf den TLS-Fingerprint. Eine untergeschobene
    `requests.Session` wuerde klaglos akzeptiert, aber ohne JA3-Fingerprint senden
    — also mit exakt der Signatur, die Yahoo blockt. Sichtbar ist das nur hier."""
    from yfinance import _http

    assert _http.HAS_CURL_CFFI, "curl_cffi-Backend fehlt — yfinance faellt auf requests zurueck"

    session = yfdata.YfData()._session
    module = type(session).__module__
    assert module.startswith("curl_cffi"), (
        f"YfData-Session ist {module}.{type(session).__name__} statt curl_cffi — "
        "die TLS-Impersonation ist ausgehebelt (stille Degradation, keine Fehlermeldung)"
    )


def test_lxml_available_for_earnings_scrape():
    """`get_earnings_dates()` geht ueber pandas.read_html, das lxml ZUERST probiert
    und dessen ImportError nicht faengt. lxml war bis 0.2.x transitive
    yfinance-Dependency und faellt ab 1.x weg — ohne expliziten Pin waere der
    EPS-Fallback dauerhaft leer."""
    assert importlib.util.find_spec("lxml") is not None, (
        "lxml fehlt — yf_earnings_dates() wuerde mit ImportError sterben"
    )


def test_wrappers_do_not_inject_own_session():
    """Die Wrapper duerfen kein `session=` mehr setzen: YfData ist ein prozessweiter
    Singleton, ein `session=` setzt ihn GLOBAL um, und das frueher folgende
    `session.close()` hinterliess eine geschlossene Session, auf der curl_cffi
    beim naechsten Zugriff hart wirft."""
    import inspect

    src = inspect.getsource(yf_patch)
    assert "requests.Session()" not in src, "yf_patch baut wieder eine eigene requests.Session"
    assert 'kwargs["session"]' not in src, "yf_patch schiebt yfinance wieder eine Session unter"
