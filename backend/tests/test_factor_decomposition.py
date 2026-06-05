"""Tests fuer die serverseitige Faktor-Decomposition.

Deckt: (1) Beta-Recovery — bei exakt linear konstruierten Returns muss die OLS
die wahren Betas/Alpha/R2 zurueckgewinnen; (2) fehlender Faktor wird sauber
gemeldet statt zu crashen; (3) NYSE-Session-Alignment — 7/7-Portfolio-Tage
kollabieren auf den Werktags-Kalender (Finding B), nicht umgekehrt.

Monkeypatcht get_portfolio_history + yf_download im Service-Modul, damit kein
DB/Netz noetig ist.
"""
import numpy as np
import pandas as pd
import pytest

import services.factor_decomposition_service as fds


def _factor_frame(rets: dict[str, np.ndarray], index: pd.DatetimeIndex):
    """Baut einen yfinance-artigen MultiIndex-DataFrame (Close, ticker) aus
    Tagesrenditen — Level = 100 * cumprod(1 + ret)."""
    cols = {}
    for key, yf in fds.FACTORS:
        if key not in rets:
            continue
        level = 100.0 * np.cumprod(1.0 + rets[key])
        cols[("Close", yf)] = level
    df = pd.DataFrame(cols, index=index)
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


def _history_points(level: np.ndarray, index: pd.DatetimeIndex) -> dict:
    return {
        "data": [
            {"date": d.date().isoformat(), "value": float(v), "portfolio_indexed": float(v)}
            for d, v in zip(index, level)
        ],
        "summary": {},
    }


@pytest.mark.asyncio
async def test_beta_recovery(monkeypatch):
    days = pd.bdate_range("2024-01-01", periods=150)
    t = np.arange(len(days), dtype=float)

    def fret(freq, phase, amp=0.01):
        r = amp * np.sin(freq * t + phase)
        r[0] = 0.0  # erste pct_change-Zeile wird ohnehin verworfen
        return r

    rets = {
        "SPY": fret(0.10, 0.0),
        "MTUM": fret(0.17, 0.5),
        "VLUE": fret(0.23, 1.0),
        "QUAL": fret(0.31, 1.5),
        "IWM": fret(0.41, 2.0),
        "GLD": fret(0.53, 2.5),
        "BTCUSD": fret(0.61, 3.0, amp=0.02),
        "USDCHF": fret(0.71, 3.5, amp=0.005),
    }

    # PF haengt exakt an SPY (1.2) + GLD (0.4) + konstantem Alpha — sonst nichts.
    alpha_true = 0.0002
    pf_ret = alpha_true + 1.2 * rets["SPY"] + 0.4 * rets["GLD"]
    pf_ret[0] = 0.0
    pf_level = 100.0 * np.cumprod(1.0 + pf_ret)

    async def fake_history(*a, **k):
        return _history_points(pf_level, days)

    def fake_yf(tickers, **k):
        return _factor_frame(rets, days)

    monkeypatch.setattr(fds, "get_portfolio_history", fake_history)
    monkeypatch.setattr(fds, "yf_download", fake_yf)

    res = await fds.factor_decomposition(None, days[0].date(), days[-1].date(), user_id=None)

    assert res.get("error") is None
    assert res["n_obs"] == 149  # 150 Level → 149 Returns
    assert res["factors"]["SPY"]["beta"] == pytest.approx(1.2, abs=1e-3)
    assert res["factors"]["GLD"]["beta"] == pytest.approx(0.4, abs=1e-3)
    # alle anderen Faktoren haben wahres Beta 0
    for k in ("MTUM", "VLUE", "QUAL", "IWM", "BTCUSD", "USDCHF"):
        assert res["factors"][k]["beta"] == pytest.approx(0.0, abs=1e-3)
    assert res["alpha"]["daily"] == pytest.approx(alpha_true, abs=1e-4)
    assert res["r_squared"] == pytest.approx(1.0, abs=1e-4)
    assert res["missing_factors"] == []
    # SPY hat klares Signal → hoher t-Wert
    assert res["factors"]["SPY"]["t_stat"] > 10


@pytest.mark.asyncio
async def test_missing_factor_is_reported_not_fatal(monkeypatch):
    days = pd.bdate_range("2024-01-01", periods=120)
    t = np.arange(len(days), dtype=float)

    def fret(freq, phase, amp=0.01):
        r = amp * np.sin(freq * t + phase)
        r[0] = 0.0
        return r

    rets = {
        "SPY": fret(0.10, 0.0),
        "MTUM": fret(0.17, 0.5),
        "VLUE": fret(0.23, 1.0),
        # QUAL fehlt absichtlich
        "IWM": fret(0.41, 2.0),
        "GLD": fret(0.53, 2.5),
        "BTCUSD": fret(0.61, 3.0, amp=0.02),
        "USDCHF": fret(0.71, 3.5, amp=0.005),
    }
    pf_ret = 1.0 * rets["SPY"]
    pf_ret[0] = 0.0
    pf_level = 100.0 * np.cumprod(1.0 + pf_ret)

    monkeypatch.setattr(fds, "get_portfolio_history", lambda *a, **k: _async(_history_points(pf_level, days)))
    monkeypatch.setattr(fds, "yf_download", lambda tickers, **k: _factor_frame(rets, days))

    res = await fds.factor_decomposition(None, days[0].date(), days[-1].date(), user_id=None)
    assert "QUAL" in res["missing_factors"]
    assert "QUAL" not in res["factors"]
    assert res["factors"]["SPY"]["beta"] == pytest.approx(1.0, abs=1e-3)


@pytest.mark.asyncio
async def test_nyse_alignment_collapses_weekend(monkeypatch):
    # SPY nur werktags; PF 7/7 (inkl. Wochenende). Erwartung: n_obs richtet sich
    # nach den SPY-Handelstagen, Wochenend-PF-Tage werden in die Session
    # kompoundiert (nicht verworfen, nicht expandiert).
    spy_days = pd.bdate_range("2024-01-01", periods=60)  # 60 Werktage
    pf_days = pd.date_range("2024-01-01", spy_days[-1])  # alle Kalendertage 7/7
    t_pf = np.arange(len(pf_days), dtype=float)
    t_spy = np.arange(len(spy_days), dtype=float)

    pf_level = 100.0 * np.cumprod(1.0 + np.r_[0.0, 0.003 * np.sin(0.2 * t_pf[1:])])
    spy_ret = 0.01 * np.sin(0.1 * t_spy)
    spy_ret[0] = 0.0
    rets = {"SPY": spy_ret}

    monkeypatch.setattr(fds, "get_portfolio_history", lambda *a, **k: _async(_history_points(pf_level, pf_days)))
    monkeypatch.setattr(fds, "yf_download", lambda tickers, **k: _factor_frame(rets, spy_days))

    res = await fds.factor_decomposition(None, pf_days[0].date(), pf_days[-1].date(), user_id=None)
    assert res.get("error") is None
    # Auf SPY-Handelskalender alignt: 60 Handelstage → 59 Returns, nicht ~90 Kalendertage
    assert res["n_obs"] == len(spy_days) - 1
    assert res["window"]["end"] == spy_days[-1].date().isoformat()


async def _async(value):
    return value
