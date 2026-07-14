"""Test Netto-Vermoegen: Komponenten-Kategorisierung + Brutto-RE − Hypothek.

Private Equity kommt seit E1 NICHT mehr aus summary["positions"] (der echte
portfolio_service filtert PE hart aus, Invariante #2), sondern als eigener
Service-Aufruf get_pe_summary — analog zu get_properties_summary. Gezählt wird
der NETTO-Wert (Steuerwert nach Illiquiditäts-Discount), nicht brutto.
"""
from __future__ import annotations

import uuid

import services.net_worth_service as nw


async def _pe_empty(_db, user_id=None):
    """Neutraler get_pe_summary-Stub für Tests ohne PE-Fokus (hermetisch:
    der echte Service darf hier nie laufen — er zöge sonst FX-Raten)."""
    return {"total_gross_value_chf": 0.0, "total_net_value_chf": 0.0, "count": 0}


async def test_net_worth_breakdown(db, monkeypatch):
    async def _summary(_db, user_id=None):
        # Vertragsgetreu: der echte portfolio_service liefert NIE private_equity-
        # oder real_estate-Positionen (harter Filter, Invariante #2). Der frühere
        # PE-Eintrag hier war genau die Attrappe, die den unerreichbaren
        # elif-Zweig im net_worth_service grün aussehen liess.
        return {"positions": [
            {"type": "stock", "market_value_chf": 5000},
            {"type": "etf", "market_value_chf": 3000, "count_as_cash": False},
            {"type": "etf", "market_value_chf": 1000, "count_as_cash": True},   # -> cash
            {"type": "bond", "market_value_chf": 2500},                         # -> eigene Kategorie
            {"type": "cash", "market_value_chf": 2000},
            {"type": "pension", "market_value_chf": 4000},
        ]}

    async def _props(_db, user_id=None):
        return {"total_value_chf": 800000.0, "total_mortgage_chf": 500000.0, "total_equity_chf": 300000.0}

    async def _pe(_db, user_id=None):
        # gross ≠ net, absichtlich: der Test pinnt, dass NETTO zählt (E1).
        return {"total_gross_value_chf": 2000.0, "total_net_value_chf": 1400.0, "count": 1}

    monkeypatch.setattr(nw, "get_portfolio_summary", _summary)
    monkeypatch.setattr(nw, "get_properties_summary", _props)
    monkeypatch.setattr(nw, "get_pe_summary", _pe)

    res = await nw.get_net_worth(db, uuid.uuid4())
    comp = {c["key"]: c["value_chf"] for c in res["components"]}
    assert comp["securities"] == 8000.0          # 5000 + 3000 (count_as_cash-etf NICHT, bond NICHT)
    assert comp["bonds"] == 2500.0               # eigene Kategorie, nicht in securities versteckt
    assert comp["cash"] == 3000.0                # 1000 (count_as_cash) + 2000
    assert comp["pension"] == 4000.0
    assert comp["private_equity"] == 1400.0      # NETTO (Steuerwert), NICHT 2000 brutto
    assert comp["real_estate"] == 800000.0       # brutto
    assert comp["mortgage"] == -500000.0         # Verbindlichkeit, negativ

    assert res["total_assets_chf"] == 818900.0   # 8000+2500+3000+4000+1400+800000
    assert res["total_liabilities_chf"] == 500000.0
    assert res["net_worth_chf"] == 318900.0      # 818900 - 500000
    assert res["has_real_estate"] is True


async def test_pe_and_re_positions_in_summary_count_exactly_once(db, monkeypatch):
    """Doppelzähl-Guard: liefert die Summary (vertragswidrig) doch eine
    private_equity- oder real_estate-Position, zählt der Wert genau EINMAL.

    PE kommt ausschliesslich aus get_pe_summary (netto), Immobilien
    ausschliesslich aus get_properties_summary. Eine dennoch ankommende
    Position muss der Skip-Guard fressen — sie darf weder die Komponente
    aufblähen noch im else-Warn-Zweig als "securities" landen.
    """
    async def _summary(_db, user_id=None):
        return {"positions": [
            {"type": "stock", "market_value_chf": 1000},
            {"type": "private_equity", "market_value_chf": 999},   # vertragswidrig
            {"type": "real_estate", "market_value_chf": 777},      # vertragswidrig
        ]}

    async def _props(_db, user_id=None):
        return {"total_value_chf": 500000.0, "total_mortgage_chf": 0.0, "total_equity_chf": 500000.0}

    async def _pe(_db, user_id=None):
        return {"total_gross_value_chf": 2000.0, "total_net_value_chf": 1400.0, "count": 1}

    monkeypatch.setattr(nw, "get_portfolio_summary", _summary)
    monkeypatch.setattr(nw, "get_properties_summary", _props)
    monkeypatch.setattr(nw, "get_pe_summary", _pe)

    res = await nw.get_net_worth(db, uuid.uuid4())
    comp = {c["key"]: c["value_chf"] for c in res["components"]}
    assert comp["private_equity"] == 1400.0       # genau einmal: netto aus get_pe_summary, NICHT +999
    assert comp["real_estate"] == 500000.0        # genau einmal: aus get_properties_summary, NICHT +777
    assert comp.get("securities", 0.0) == 1000.0  # 999/777 NICHT als securities einsortiert
    assert res["total_assets_chf"] == 502400.0    # 1000 + 1400 + 500000 — nichts doppelt


async def test_bond_is_own_category_and_in_total_assets(db, monkeypatch):
    """Eine Anleihe darf weder still aus dem Netto-Vermoegen fallen noch in
    "Wertschriften" verschwinden — sie ist eine eigene Zeile "Anleihen".

    Fiele sie durch (kein Kategorie-Zweig), waeren total_assets 0 statt 2500.
    """
    async def _summary(_db, user_id=None):
        return {"positions": [{"type": "bond", "market_value_chf": 2500}]}

    async def _props(_db, user_id=None):
        return {"total_value_chf": 0.0, "total_mortgage_chf": 0.0, "total_equity_chf": 0.0}

    monkeypatch.setattr(nw, "get_portfolio_summary", _summary)
    monkeypatch.setattr(nw, "get_properties_summary", _props)
    monkeypatch.setattr(nw, "get_pe_summary", _pe_empty)

    res = await nw.get_net_worth(db, uuid.uuid4())
    # Nullwertige Komponenten werden herausgefiltert -> .get statt [] (securities
    # und cash duerfen hier gar nicht erst auftauchen).
    comp = {c["key"]: c["value_chf"] for c in res["components"]}
    assert comp["bonds"] == 2500.0
    assert comp.get("securities", 0.0) == 0.0    # NICHT in Wertschriften einsortiert
    assert comp.get("cash", 0.0) == 0.0          # und erst recht kein Cash
    assert res["total_assets_chf"] == 2500.0
    assert res["net_worth_chf"] == 2500.0
    # Deutsches Label der Klasse (UI-Text).
    labels = {c["key"]: c["label"] for c in res["components"]}
    assert labels["bonds"] == "Anleihen"


async def test_bond_with_count_as_cash_flag_still_counts_once(db, monkeypatch):
    """Verteidigt gegen Alt-/Fremddaten: eine bond-Position, die (entgegen E1)
    noch ein count_as_cash=true traegt, darf nicht doppelt gezaehlt werden.

    Die API klemmt das Flag fuer bond hart auf False; kaeme es dennoch an, ist
    "einmal gezaehlt" die einzig richtige Antwort — der Wert muss in genau einer
    Kategorie landen (die Cash-Regel schlaegt hier den Typ, wie in der by_type-
    Allokation).
    """
    async def _summary(_db, user_id=None):
        return {"positions": [
            {"type": "bond", "market_value_chf": 2500, "count_as_cash": True},
        ]}

    async def _props(_db, user_id=None):
        return {"total_value_chf": 0.0, "total_mortgage_chf": 0.0, "total_equity_chf": 0.0}

    monkeypatch.setattr(nw, "get_portfolio_summary", _summary)
    monkeypatch.setattr(nw, "get_properties_summary", _props)
    monkeypatch.setattr(nw, "get_pe_summary", _pe_empty)

    res = await nw.get_net_worth(db, uuid.uuid4())
    # Nullwertige Komponenten werden herausgefiltert -> .get; welcher der beiden
    # Toepfe gewinnt, pinnt der Test bewusst NICHT (das ist eine Alt-Daten-Ecke) —
    # entscheidend ist, dass der Wert genau einmal im Vermoegen landet.
    comp = {c["key"]: c["value_chf"] for c in res["components"]}
    assert comp.get("bonds", 0.0) + comp.get("cash", 0.0) == 2500.0
    assert res["total_assets_chf"] == 2500.0


async def test_no_real_estate_filters_zero_lines(db, monkeypatch):
    async def _summary(_db, user_id=None):
        return {"positions": [{"type": "stock", "market_value_chf": 1000}]}

    async def _props(_db, user_id=None):
        return {"total_value_chf": 0.0, "total_mortgage_chf": 0.0, "total_equity_chf": 0.0}

    monkeypatch.setattr(nw, "get_portfolio_summary", _summary)
    monkeypatch.setattr(nw, "get_properties_summary", _props)
    monkeypatch.setattr(nw, "get_pe_summary", _pe_empty)

    res = await nw.get_net_worth(db, uuid.uuid4())
    assert res["net_worth_chf"] == 1000.0
    assert res["has_real_estate"] is False
    keys = {c["key"] for c in res["components"]}
    assert "real_estate" not in keys and "mortgage" not in keys   # 0 -> gefiltert
    assert "private_equity" not in keys                           # 0 -> gefiltert
