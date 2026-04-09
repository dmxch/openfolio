"""Schweizer Makro-Snapshot-Service.

Aggregiert CH-spezifische Makro-Daten (SNB-Leitzins, SARON, CHF-Cross-Rates,
CH-Inflation, CH-10Y, SMI-vs-SP500) in einem Call. Jede Quelle ist in einen
eigenen try/except gewrappt — wenn eine Quelle ausfaellt, fehlt das Feld in
der Response, und ein maschinenlesbarer Warning-String landet in `warnings[]`.

Design: die `get_ch_macro_snapshot()`-Funktion wirft bewusst NICHT. Die
asyncio.gather(..., return_exceptions=True)-Orchestration unten ist
Belt-and-Suspenders gegen unerwartete Helper-Fehler.

HEILIGE Regeln 7 (yfinance nur via yf_download + asyncio.to_thread) und
8 (httpx statt requests) werden hier strikt eingehalten.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from config import settings
from dateutils import utcnow
from services.property_service import fetch_saron_rate
# Privater Cross-Modul-Import: beide Funktionen liegen im selben
# `backend/services/`-Package. Direkter Aufruf ist pragmatisch OK und
# vermeidet eine invasive Refactor-Aenderung an macro_indicators_service.py.
from services.macro_indicators_service import (  # noqa: PLC2701
    _fred_get_series,
    _fred_get_with_date,
)
from yf_patch import yf_download

logger = logging.getLogger(__name__)


# --- Konstanten (manuell zu pflegen) ---------------------------------------

# Letzter bekannter SNB-Policy-Rate-Stand als Fallback. Wird verwendet, wenn
# das SNB Data Portal nicht erreichbar ist oder eine unbekannte Serie liefert.
_SNB_POLICY_RATE_FALLBACK: dict[str, Any] = {"rate": 0.5, "changed_on": "2025-12-12"}

# Naechste geplante SNB-Leitzinsentscheide. Jaehrlich aktualisieren.
_SNB_MEETING_DATES: list[str] = ["2026-06-19", "2026-09-25", "2026-12-11"]

# Naechste BFS-CPI-Releases. Leer lassen wenn nicht gepflegt — Feld wird
# dann einfach weggelassen.
_BFS_CPI_RELEASE_DATES: list[str] = []

# SNB Data Portal: cube `snbgwdzid` enthaelt alle SNB-Zinssaetze in einem
# Tisch. Policy Rate = series `LZ` (Leitzins), SARON = series `SARON`.
# API-Pattern: GET /api/cube/{cube}/data/json/en?dimSel=D0({series})&fromDate=YYYY-MM-DD
_SNB_CUBE_URL = "https://data.snb.ch/api/cube/snbgwdzid/data/json/en"
_SNB_POLICY_RATE_SERIES = "LZ"
_SNB_SARON_SERIES = "SARON"


# --- Sync Helpers -----------------------------------------------------------

def _trend_label(delta: float | None, threshold: float = 0.5) -> str:
    """Klassifiziert ein Delta als up / down / stable."""
    if delta is None:
        return "unknown"
    if delta > threshold:
        return "up"
    if delta < -threshold:
        return "down"
    return "stable"


def _fx_trend_label(delta_pct: float | None, threshold: float = 0.3) -> str:
    """Trend fuer eine CHF-Cross-Rate aus Schweizer Sicht.

    Eingabe: prozentuale Aenderung der Rate `1 CHF = X FREMD`. Steigt die
    Rate, kauft 1 CHF mehr Fremdwaehrung -> CHF hat aufgewertet.
    """
    if delta_pct is None:
        return "unknown"
    if delta_pct > threshold:
        return "chf_stronger"
    if delta_pct < -threshold:
        return "chf_weaker"
    return "stable"


def _next_snb_meeting(today: date | None = None) -> str | None:
    """Liefert das naechste geplante SNB-Meeting >= heute, oder None."""
    today = today or date.today()
    for iso in _SNB_MEETING_DATES:
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            continue
        if d >= today:
            return iso
    return None


def _next_cpi_release(today: date | None = None) -> str | None:
    today = today or date.today()
    for iso in _BFS_CPI_RELEASE_DATES:
        try:
            d = date.fromisoformat(iso)
        except ValueError:
            continue
        if d >= today:
            return iso
    return None


def _fred_key() -> str | None:
    """Normalisiert die FRED-Key-Config: leerer String == None."""
    key = settings.fred_api_key
    return key if key else None


# --- Async Helpers: jeder isoliert via try/except --------------------------

async def _fetch_snb_policy_rate() -> dict[str, Any]:
    """SNB Policy Rate aus dem Data Portal, mit Fallback bei Fehler.

    Quelle: cube `snbgwdzid`, series `LZ` (Leitzins). fromDate wird auf
    2019-01-01 gesetzt, damit die komplette Historie seit Einfuehrung der
    aktuellen Policy-Rate-Systematik abgedeckt ist und wir `changed_on`
    korrekt finden koennen.
    """
    warnings: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _SNB_CUBE_URL,
                params={
                    "dimSel": f"D0({_SNB_POLICY_RATE_SERIES})",
                    "fromDate": "2019-01-01",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()

        # SNB JSON-Schema ist nicht 100% stabil — defensiv parsen.
        observations: list[tuple[str, float]] = []
        if isinstance(payload, dict):
            for tl in (payload.get("timeseries") or []):
                for val in (tl.get("values") or []):
                    d = val.get("date")
                    v = val.get("value")
                    if d is not None and v is not None:
                        try:
                            observations.append((str(d), float(v)))
                        except (TypeError, ValueError):
                            continue

        if not observations:
            raise ValueError("snb policy rate: empty observations")

        observations.sort()
        last_date, last_val = observations[-1]
        # Letzte Aenderung: laufe rueckwaerts bis sich der Wert unterscheidet.
        changed_on = last_date
        for d, v in reversed(observations[:-1]):
            if v != last_val:
                break
            changed_on = d

        return {
            "data": {
                "policy_rate_pct": last_val,
                "policy_rate_changed_on": changed_on,
            },
            "warnings": warnings,
        }
    except Exception as e:
        logger.warning(f"ch_macro: SNB policy rate fetch failed, using fallback: {e}")
        return {
            "data": {
                "policy_rate_pct": _SNB_POLICY_RATE_FALLBACK["rate"],
                "policy_rate_changed_on": _SNB_POLICY_RATE_FALLBACK["changed_on"],
            },
            "warnings": ["snb_policy_rate_fallback_used"],
        }


async def _fetch_saron_history_30d() -> list[tuple[str, float]]:
    """Parst die SNB-SARON-Historie (JSON, cube `snbgwdzid`, series `SARON`)
    und liefert eine Liste (date, rate) der letzten ~60 Tage. Leere Liste
    bei Fehler.

    Ohne `fromDate` liefert das SNB Data Portal nur die letzten ~5 Tage —
    zu wenig fuer ein 30d-Delta. Deshalb expliziter Startpunkt.
    """
    try:
        start = (date.today() - timedelta(days=60)).isoformat()
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                _SNB_CUBE_URL,
                params={
                    "dimSel": f"D0({_SNB_SARON_SERIES})",
                    "fromDate": start,
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()

        rows: list[tuple[str, float]] = []
        for ts in (payload.get("timeseries") or []):
            for val in (ts.get("values") or []):
                d = val.get("date")
                v = val.get("value")
                if d is None or v is None:
                    continue
                try:
                    rows.append((str(d), float(v)))
                except (TypeError, ValueError):
                    continue
        rows.sort()
        return rows
    except Exception as e:
        logger.warning(f"ch_macro: SARON history fetch failed: {e}")
        return []


async def _fetch_saron_with_delta() -> dict[str, Any]:
    """Aktueller SARON + 30d-Delta via SNB-CSV-History."""
    warnings: list[str] = []
    try:
        current, history = await asyncio.gather(
            fetch_saron_rate(),
            _fetch_saron_history_30d(),
            return_exceptions=True,
        )
        if isinstance(current, Exception) or not current:
            return {"data": None, "warnings": ["saron_current_unavailable"]}

        current_rate = float(current["rate"])
        current_date = current.get("date")

        delta_30d: float | None = None
        if isinstance(history, list) and history:
            target = date.today() - timedelta(days=30)
            # Suche den Eintrag mit Datum <= target (naechster <= 30 Tage alt).
            past_val: float | None = None
            for d_str, v in reversed(history):
                try:
                    d_parsed = date.fromisoformat(d_str)
                except ValueError:
                    continue
                if d_parsed <= target:
                    past_val = v
                    break
            if past_val is not None:
                delta_30d = round(current_rate - past_val, 4)
            else:
                warnings.append("saron_history_too_short")
        else:
            warnings.append("saron_history_unavailable")

        return {
            "data": {
                "current_pct": current_rate,
                "as_of": current_date,
                "delta_30d_bps": None if delta_30d is None else round(delta_30d * 100, 1),
                "trend": _trend_label(delta_30d, threshold=0.05),
            },
            "warnings": warnings,
        }
    except Exception as e:
        logger.warning(f"ch_macro: SARON aggregate failed: {e}")
        return {"data": None, "warnings": ["saron_unavailable"]}


async def _fetch_fx_pairs() -> dict[str, Any]:
    """EUR/CHF und USD/CHF in eine CHF-zentrische Sicht drehen."""
    warnings: list[str] = []
    try:
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=70)
        df = await asyncio.to_thread(
            yf_download,
            "EURCHF=X USDCHF=X",
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
        )
        if df is None or len(df) == 0:
            return {"data": None, "warnings": ["fx_unavailable"]}

        def _rate(ticker: str) -> tuple[float | None, float | None, str | None]:
            """Liefert (current, value_30d_ago, as_of_iso) fuer EURCHF/USDCHF.
            Rates sind: 1 FREMD = X CHF (yahoo format).
            Wir drehen spaeter auf: 1 CHF = 1/X FREMD.
            """
            try:
                col = df["Close"][ticker].dropna()
            except Exception:
                return None, None, None
            if col.empty:
                return None, None, None
            current = float(col.iloc[-1])
            as_of = col.index[-1].date().isoformat() if hasattr(col.index[-1], "date") else str(col.index[-1])
            target_ts = col.index[-1] - timedelta(days=30)
            past_slice = col[col.index <= target_ts]
            past = float(past_slice.iloc[-1]) if len(past_slice) > 0 else None
            return current, past, as_of

        def _build(cur: float | None, past: float | None, as_of: str | None) -> dict[str, Any] | None:
            if cur is None or cur == 0:
                return None
            chf_rate = 1.0 / cur  # 1 CHF = X Fremdwaehrung
            delta_30d_pct: float | None = None
            if past and past != 0:
                chf_rate_past = 1.0 / past
                delta_30d_pct = round(((chf_rate / chf_rate_past) - 1.0) * 100, 3)
            return {
                "rate": round(chf_rate, 5),
                "as_of": as_of,
                "delta_30d_pct": delta_30d_pct,
                "trend": _fx_trend_label(delta_30d_pct),
            }

        eur_cur, eur_past, eur_asof = _rate("EURCHF=X")
        usd_cur, usd_past, usd_asof = _rate("USDCHF=X")

        eur_block = _build(eur_cur, eur_past, eur_asof)
        usd_block = _build(usd_cur, usd_past, usd_asof)

        if eur_block is None:
            warnings.append("fx_eur_unavailable")
        if usd_block is None:
            warnings.append("fx_usd_unavailable")

        if eur_block is None and usd_block is None:
            return {"data": None, "warnings": warnings or ["fx_unavailable"]}

        return {
            "data": {
                "chf_eur": eur_block,
                "chf_usd": usd_block,
            },
            "warnings": warnings,
        }
    except Exception as e:
        logger.warning(f"ch_macro: FX fetch failed: {e}")
        return {"data": None, "warnings": ["fx_unavailable"]}


_EUROSTAT_HICP_URL = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr"
)


async def _fetch_eurostat_hicp_ch(coicop: str) -> tuple[float | None, str | None]:
    """Holt die neueste CH-HICP-YoY-Monatsrate von Eurostat fuer einen COICOP-
    Index. Rueckgabe: (value_pct, yyyy_mm) oder (None, None) bei Fehler.

    COICOP-Codes:
      - `CP00` = All items (Headline)
      - `TOT_X_NRG_FOOD` = Excl. energy, food, alcohol, tobacco (Core)

    Eurostat publiziert monatlich ~4 Wochen nach Monatsende, ist im Gegensatz
    zu FRED-OECD-Serien zuverlaessig aktuell und benoetigt keinen API-Key.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                _EUROSTAT_HICP_URL,
                params={
                    "format": "JSON",
                    "geo": "CH",
                    "coicop": coicop,
                    "lang": "EN",
                    "sinceTimePeriod": "2024-01",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            payload = resp.json()

        # SDMX-JSON: `value` ist Dict[str_index, number], `dimension.time.category.index`
        # mapped Label-String (YYYY-MM) auf int Index.
        values = payload.get("value", {}) or {}
        if not values:
            return None, None
        time_cat = (
            payload.get("dimension", {}).get("time", {}).get("category", {})
        )
        label_to_idx: dict[str, int] = time_cat.get("index", {}) or {}
        idx_to_label: dict[int, str] = {int(v): k for k, v in label_to_idx.items()}

        # Sortiere vorhandene Werte nach Zeit-Index (chronologisch) und nimm
        # den neuesten der tatsaechlich einen Wert hat.
        present = sorted(int(k) for k in values.keys())
        for idx in reversed(present):
            raw = values[str(idx)]
            if raw is None:
                continue
            try:
                return float(raw), idx_to_label.get(idx)
            except (TypeError, ValueError):
                continue
        return None, None
    except Exception as e:
        logger.warning(f"ch_macro: eurostat HICP fetch failed for {coicop}: {e}")
        return None, None


async def _fetch_ch_inflation() -> dict[str, Any]:
    """CH-CPI headline + core via Eurostat HICP (monthly YoY rate).

    Eurostat wird statt FRED verwendet, weil die FRED-OECD-CH-Serien seit
    April 2025 nicht mehr aktualisiert werden. Eurostat hat CH als EFTA-
    Land regulaer und aktualisiert monatlich ~4 Wochen nach Monatsende.
    """
    warnings: list[str] = []
    try:
        headline, core = await asyncio.gather(
            _fetch_eurostat_hicp_ch("CP00"),
            _fetch_eurostat_hicp_ch("TOT_X_NRG_FOOD"),
        )
        cpi_val, cpi_date = headline
        core_val, _ = core

        if cpi_val is None:
            warnings.append("ch_cpi_unavailable")
        if core_val is None:
            warnings.append("ch_core_cpi_unavailable")

        data: dict[str, Any] = {
            "cpi_yoy_pct": cpi_val,
            "cpi_as_of": cpi_date,
            "core_cpi_yoy_pct": core_val,
        }
        if _BFS_CPI_RELEASE_DATES:
            data["next_release"] = _next_cpi_release()
        return {"data": data, "warnings": warnings}
    except Exception as e:
        logger.warning(f"ch_macro: CH inflation fetch failed: {e}")
        return {"data": None, "warnings": ["ch_inflation_unavailable"]}


async def _fetch_ch_10y() -> dict[str, Any]:
    """CH 10Y Yield via FRED (IRLTLT01CHM156N, monatlich)."""
    warnings: list[str] = []
    key = _fred_key()
    if key is None:
        return {
            "data": {"eidg_10y_yield_pct": None, "delta_30d_bps": None},
            "warnings": ["fred_no_api_key"],
        }
    try:
        series = await _fred_get_series("IRLTLT01CHM156N", limit=4, api_key=key)
        if not series:
            return {"data": None, "warnings": ["ch_10y_unavailable"]}
        current = series[0]
        delta_bps: float | None = None
        # _fred_get_series ist sort_order=desc, also [0] = neuester,
        # [1] = Vormonat (~30 Tage frueher).
        if len(series) >= 2:
            delta_bps = round((current - series[1]) * 100, 1)
        return {
            "data": {
                "eidg_10y_yield_pct": round(current, 3),
                "delta_30d_bps": delta_bps,
                "trend": _trend_label(delta_bps, threshold=5),
            },
            "warnings": warnings,
        }
    except Exception as e:
        logger.warning(f"ch_macro: CH 10Y fetch failed: {e}")
        return {"data": None, "warnings": ["ch_10y_unavailable"]}


async def _fetch_smi_vs_sp500() -> dict[str, Any]:
    """30d-Performance-Vergleich SMI vs SP500 via yfinance."""
    try:
        end = date.today() + timedelta(days=1)
        start = end - timedelta(days=70)
        df = await asyncio.to_thread(
            yf_download,
            "^SSMI ^GSPC",
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
        )
        if df is None or len(df) == 0:
            return {"data": None, "warnings": ["smi_vs_sp500_unavailable"]}

        def _ret(ticker: str) -> float | None:
            try:
                col = df["Close"][ticker].dropna()
            except Exception:
                return None
            if len(col) < 2:
                return None
            current = float(col.iloc[-1])
            target_ts = col.index[-1] - timedelta(days=30)
            past_slice = col[col.index <= target_ts]
            if len(past_slice) == 0:
                return None
            past = float(past_slice.iloc[-1])
            if past == 0:
                return None
            return round(((current / past) - 1.0) * 100, 3)

        smi_ret = _ret("^SSMI")
        sp_ret = _ret("^GSPC")

        if smi_ret is None or sp_ret is None:
            return {"data": None, "warnings": ["smi_vs_sp500_unavailable"]}

        return {
            "data": {
                "smi_return_pct": smi_ret,
                "sp500_return_pct": sp_ret,
                "relative_pct": round(smi_ret - sp_ret, 3),
            },
            "warnings": [],
        }
    except Exception as e:
        logger.warning(f"ch_macro: SMI-vs-SP500 fetch failed: {e}")
        return {"data": None, "warnings": ["smi_vs_sp500_unavailable"]}


# --- Orchestrator -----------------------------------------------------------

_SECTION_KEYS = (
    "snb",
    "saron",
    "fx",
    "ch_inflation",
    "ch_rates",
    "smi_vs_sp500_30d",
)


async def get_ch_macro_snapshot() -> dict[str, Any]:
    """Liefert CH-Makro-Kontext (SNB, SARON, FX, CPI, 10Y, SMI-vs-SP500).

    Partial-Failure-tolerant: jede nicht erreichbare Quelle wird in
    `warnings[]` gelistet, vorhandene Felder bleiben in der Response.
    """
    results = await asyncio.gather(
        _fetch_snb_policy_rate(),
        _fetch_saron_with_delta(),
        _fetch_fx_pairs(),
        _fetch_ch_inflation(),
        _fetch_ch_10y(),
        _fetch_smi_vs_sp500(),
        return_exceptions=True,
    )

    warnings: list[str] = []
    snapshot: dict[str, Any] = {"as_of": utcnow().isoformat()}

    for key, result in zip(_SECTION_KEYS, results):
        if isinstance(result, Exception):
            logger.warning(f"ch_macro: {key} raised unexpectedly: {result}")
            warnings.append(f"{key}_unavailable")
            snapshot[key] = None
        elif isinstance(result, dict):
            snapshot[key] = result.get("data")
            warnings.extend(result.get("warnings", []) or [])
        else:
            snapshot[key] = None
            warnings.append(f"{key}_unavailable")

    # Next SNB meeting ist hardcoded, immer verfuegbar — an snb-Block haengen.
    snb_block = snapshot.get("snb") or {}
    if not isinstance(snb_block, dict):
        snb_block = {}
    snb_block["next_meeting"] = _next_snb_meeting()
    snapshot["snb"] = snb_block

    snapshot["warnings"] = warnings
    return snapshot
