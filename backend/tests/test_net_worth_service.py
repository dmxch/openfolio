"""Test Netto-Vermoegen: Komponenten-Kategorisierung + Brutto-RE − Hypothek."""
from __future__ import annotations

import uuid

import services.net_worth_service as nw


async def test_net_worth_breakdown(db, monkeypatch):
    async def _summary(_db, user_id=None):
        return {"positions": [
            {"type": "stock", "market_value_chf": 5000},
            {"type": "etf", "market_value_chf": 3000, "count_as_cash": False},
            {"type": "etf", "market_value_chf": 1000, "count_as_cash": True},   # -> cash
            {"type": "cash", "market_value_chf": 2000},
            {"type": "pension", "market_value_chf": 4000},
            {"type": "private_equity", "market_value_chf": 1500},
            {"type": "real_estate", "market_value_chf": 0},                     # shares=0, ignoriert
        ]}

    async def _props(_db, user_id=None):
        return {"total_value_chf": 800000.0, "total_mortgage_chf": 500000.0, "total_equity_chf": 300000.0}

    monkeypatch.setattr(nw, "get_portfolio_summary", _summary)
    monkeypatch.setattr(nw, "get_properties_summary", _props)

    res = await nw.get_net_worth(db, uuid.uuid4())
    comp = {c["key"]: c["value_chf"] for c in res["components"]}
    assert comp["securities"] == 8000.0          # 5000 + 3000 (count_as_cash-etf NICHT)
    assert comp["cash"] == 3000.0                # 1000 (count_as_cash) + 2000
    assert comp["pension"] == 4000.0
    assert comp["private_equity"] == 1500.0
    assert comp["real_estate"] == 800000.0       # brutto
    assert comp["mortgage"] == -500000.0         # Verbindlichkeit, negativ

    assert res["total_assets_chf"] == 816500.0   # 8000+3000+4000+1500+800000
    assert res["total_liabilities_chf"] == 500000.0
    assert res["net_worth_chf"] == 316500.0      # 816500 - 500000
    assert res["has_real_estate"] is True


async def test_no_real_estate_filters_zero_lines(db, monkeypatch):
    async def _summary(_db, user_id=None):
        return {"positions": [{"type": "stock", "market_value_chf": 1000}]}

    async def _props(_db, user_id=None):
        return {"total_value_chf": 0.0, "total_mortgage_chf": 0.0, "total_equity_chf": 0.0}

    monkeypatch.setattr(nw, "get_portfolio_summary", _summary)
    monkeypatch.setattr(nw, "get_properties_summary", _props)

    res = await nw.get_net_worth(db, uuid.uuid4())
    assert res["net_worth_chf"] == 1000.0
    assert res["has_real_estate"] is False
    keys = {c["key"] for c in res["components"]}
    assert "real_estate" not in keys and "mortgage" not in keys   # 0 -> gefiltert
