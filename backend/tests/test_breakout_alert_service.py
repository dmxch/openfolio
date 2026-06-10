"""Regression tests for breakout_alert_service.

Hintergrund: Der Service importierte `download_and_analyze` lazy aus
stock_scorer — die Funktion heisst aber `_download_and_analyze`. Der
ImportError wurde vom per-User-try/except verschluckt, Breakout-Alerts
feuerten dadurch seit v0.21.4 nie (Review 2026-06-10, H1). Diese Tests
lösen ALLE lazy Imports des Moduls auf, damit so etwas nie wieder
unbemerkt bleibt.
"""

import ast
import importlib
import inspect


def _resolve_lazy_imports(module) -> list[str]:
    """Resolve every function-level `from X import Y` in a module's source.

    Returns a list of error strings (empty = all imports resolve).
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)
    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            try:
                target = importlib.import_module(node.module)
            except ImportError as e:
                errors.append(f"line {node.lineno}: module {node.module!r} not importable: {e}")
                continue
            for alias in node.names:
                if alias.name == "*":
                    continue
                if not hasattr(target, alias.name):
                    errors.append(
                        f"line {node.lineno}: {node.module}.{alias.name} does not exist"
                    )
    return errors


def test_all_imports_in_breakout_alert_service_resolve():
    import services.breakout_alert_service as mod

    errors = _resolve_lazy_imports(mod)
    assert errors == [], "Unresolvable imports (silent-failure risk): " + "; ".join(errors)


def test_scorer_exposes_functions_used_by_alert_service():
    from services import stock_scorer

    assert callable(getattr(stock_scorer, "_download_and_analyze", None))
    assert callable(getattr(stock_scorer, "check_breakout_trigger", None))
