"""Regression: das /portfolio/summary-response_model darf die FX-Felder NICHT
strippen. Genau dieser Bug liess die neue FX-Spalte im UI leer ("-"), obwohl
get_portfolio_summary die Felder liefert — Pydantic verwarf sie, weil sie im
PortfolioPositionResponse-Schema fehlten.
"""
from api.schemas import PortfolioPositionResponse


def test_response_model_preserves_fx_fields():
    p = PortfolioPositionResponse(
        id="p1", ticker="JNJ", name="J&J", type="stock", currency="USD",
        shares=10, cost_basis_chf=1000, market_value_chf=1120,
        pnl_chf=120, pnl_pct=12.0, weight_pct=5.0,
        local_return_pct=9.87, fx_return_pct=3.30, fx_cross_pct=0.33,
    )
    d = p.model_dump()
    assert d["local_return_pct"] == 9.87
    assert d["fx_return_pct"] == 3.30
    assert d["fx_cross_pct"] == 0.33


def test_fx_fields_present_as_none_when_not_decomposable():
    # CHF-/nicht-zerlegbare Positionen: Felder muessen als Key mit None erscheinen
    # (nicht fehlen), sonst kann das Frontend "-" vs. echten Wert nicht unterscheiden.
    p = PortfolioPositionResponse(
        id="p2", ticker="CHSPI.SW", name="SPI", type="etf", currency="CHF",
        shares=1, cost_basis_chf=100, market_value_chf=110,
        pnl_chf=10, pnl_pct=10.0, weight_pct=1.0,
    )
    d = p.model_dump()
    assert "fx_return_pct" in d and d["fx_return_pct"] is None
    assert "local_return_pct" in d and d["local_return_pct"] is None
    assert "fx_cross_pct" in d and d["fx_cross_pct"] is None
