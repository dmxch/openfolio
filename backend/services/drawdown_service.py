"""Portfolio drawdown calculation.

Peak-to-trough drawdown per period, plus the Drawdown-Bremse flag (active when
current drawdown vs. peak >= 6%).

Methodology: cash-flow-adjusted TWR so that Einzahlungen/Auszahlungen keinen
Drawdown vortaeuschen.

Sowohl Portfolio-level (``bucket_id is None``) als auch Bucket-level
(``bucket_id`` gesetzt) leiten den Drawdown aus DERSELBEN rekonstruierten
``portfolio_indexed``-Kurve ab wie ``/performance/history`` (history_service),
nur einmal global und einmal auf die Positionen des Buckets eingeschraenkt.
Damit koennen die Endpoints nicht divergieren und — entscheidend — rohe
Snapshot-Marktwerte inkl. Netto-Einzahlungen erzeugen KEINEN Phantom-Drawdown
mehr: der Index ist cash-flow-bereinigt (Sub-Period-TWR), Ein-/Auszahlungen
und DCA-Zufluesse taeuschen also keinen Drawdown vor.

Auch die CHF-Anker (peak_value_chf/trough_value_chf/running_peak_value_chf)
werden aus DERSELBEN indexierten Serie abgeleitet (current_value × Index-Ratio),
NICHT mehr aus den rohen Snapshot-Marktwerten. Damit sind sie konsistent mit den
%-Feldern (trough_value <= peak_value, max_drawdown/current_vs_peak passen exakt)
und nicht mehr cash-flow-kontaminiert. ``current_value_chf`` bleibt der reale
nominale Buchwert von heute (Skalierungs-Anker). Details in
``_running_peak_drawdown``.

Frueher rechnete Bucket-level auf dem in BucketSnapshot vorab-gechainten
``wealth_index`` (TWR aus total_value_chf + net_cash_flow_chf). Diese Reihe
driftete in Produktion massiv (trough > peak, current_vs_peak ~ -60 %), weil
sie auf den kontaminierten Snapshot-Rohwerten aufsetzte. Die Rekonstruktion
aus Positionen + historischen Kursen umgeht die korrupte gespeicherte Reihe
komplett.
"""
import logging
import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DRAWDOWN_BRAKE_THRESHOLD_PCT = 6.0

_VALID_PERIODS = {"ytd", "1m", "3m", "6m", "1y", "all"}


def _period_start(period: str, today: date) -> date | None:
    if period == "ytd":
        return date(today.year, 1, 1)
    if period == "1m":
        return today - timedelta(days=30)
    if period == "3m":
        return today - timedelta(days=90)
    if period == "6m":
        return today - timedelta(days=182)
    if period == "1y":
        return today - timedelta(days=365)
    return None  # all


def _empty(period: str, threshold: float, bucket_id: uuid.UUID | None) -> dict:
    return {
        "period": period,
        "snapshots_count": 0,
        "max_drawdown_pct": None,
        "peak_date": None,
        "peak_value_chf": None,
        "trough_date": None,
        "trough_value_chf": None,
        "current_value_chf": None,
        "running_peak_date": None,
        "running_peak_value_chf": None,
        "current_vs_peak_pct": None,
        "drawdown_brake_active": False,
        "drawdown_brake_threshold_pct": threshold,
        "bucket_id": str(bucket_id) if bucket_id else None,
        "warning": "keine_snapshots_im_zeitraum",
    }


def _running_peak_drawdown(series: list[tuple[date, float, float]], threshold: float):
    """series = [(date, wealth_index, raw_value)] in chronologischer Reihenfolge.

    Liefert das fertige Drawdown-Dict (ohne period/snapshots_count/bucket_id).

    Peak/Trough/Running-Peak werden am cash-flow-bereinigten WEALTH-INDEX bestimmt;
    die Datums-Felder zeigen folglich auf die Extrema DER INDEXIERTEN Serie. Die
    CHF-Anker (*_value_chf) werden NICHT aus den rohen Snapshot-Marktwerten gelesen
    (die enthalten Netto-Einzahlungen → trough > peak, current < trough), sondern
    aus derselben indexierten Serie abgeleitet: jeder Anker ist der heutige reale
    Buchwert ``current_value`` skaliert mit dem Index-Verhaeltnis. Damit gilt
    strikt:
      - trough_value_chf <= peak_value_chf,
      - max_drawdown_pct  == (trough_value_chf - peak_value_chf) / peak_value_chf,
      - current_vs_peak_pct == (current_value_chf - running_peak_value_chf)
                               / running_peak_value_chf,
    alle innerhalb der Rundung. ``current_value_chf`` bleibt der reale nominale
    Buchwert von heute (der Skalierungs-Anker, Faktor 1.0 zum aktuellen Index).
    ``peak``/``trough`` beschreiben die tiefste Drawdown-Episode; ``running_peak``
    ist das Allzeit-Hoch (High-Water-Mark), gegen das ``current_vs_peak_pct`` und
    die Bremse messen — beide Peaks koennen auseinanderfallen.
    """
    running_peak_index = 0.0
    running_peak_date: date | None = None
    max_dd_pct = 0.0
    max_dd_peak_index = 0.0
    max_dd_peak_date: date | None = None
    max_dd_trough_index = 0.0
    max_dd_trough_date: date | None = None

    for d, w, v in series:
        if w > running_peak_index:
            running_peak_index = w
            running_peak_date = d
        if running_peak_index > 0:
            dd_pct = (w / running_peak_index - 1) * 100
            if dd_pct < max_dd_pct:
                max_dd_pct = dd_pct
                max_dd_peak_index = running_peak_index
                max_dd_peak_date = running_peak_date
                max_dd_trough_index = w
                max_dd_trough_date = d

    current_index = series[-1][1]
    current_value = series[-1][2]

    # CHF-Anker aus der indexierten Serie: V_heute * (Index_x / Index_heute).
    def _chf(index_level: float):
        if current_index and current_index > 0 and index_level:
            return round(current_value * (index_level / current_index), 2)
        return None

    current_vs_peak_pct = None
    if running_peak_index > 0:
        current_vs_peak_pct = round((current_index / running_peak_index - 1) * 100, 2)

    max_drawdown_pct = round(max_dd_pct, 2) if max_dd_pct < 0 else 0.0
    brake_active = (
        current_vs_peak_pct is not None and current_vs_peak_pct <= -threshold
    )

    return {
        "max_drawdown_pct": max_drawdown_pct,
        "peak_date": max_dd_peak_date.isoformat() if max_dd_peak_date else None,
        "peak_value_chf": _chf(max_dd_peak_index) if max_dd_peak_date else None,
        "trough_date": max_dd_trough_date.isoformat() if max_dd_trough_date else None,
        "trough_value_chf": _chf(max_dd_trough_index) if max_dd_trough_date else None,
        "current_value_chf": round(current_value, 2),
        "running_peak_date": running_peak_date.isoformat() if running_peak_date else None,
        "running_peak_value_chf": _chf(running_peak_index) if running_peak_date else None,
        "current_vs_peak_pct": current_vs_peak_pct,
        "drawdown_brake_active": brake_active,
        "drawdown_brake_threshold_pct": threshold,
    }


async def _indexed_drawdown(
    db: AsyncSession,
    user_id: uuid.UUID,
    period: str,
    start: date | None,
    today: date,
    *,
    bucket_id: uuid.UUID | None,
    threshold: float,
) -> dict:
    """Drawdown aus der rekonstruierten portfolio_indexed-Kurve.

    ``bucket_id is None`` -> ganzes Portfolio; gesetzt -> nur die Positionen
    dieses Buckets. Beide Pfade nutzen dieselbe cash-flow-bereinigte
    Sub-Period-TWR-Methodik (history_service), daher kein Phantom-Drawdown aus
    Einzahlungen/DCA.
    """
    from services.history_service import get_portfolio_history

    # "all" spiegelt exakt den /performance/history-Endpoint (start = 2000-01-01),
    # damit beide Endpoints dieselbe Kurve sehen und ein Drawdown vor dem ersten
    # Snapshot nicht uebersehen wird. history_service kuerzt intern an die echte
    # Inception (erste Transaktion), erzeugt also keine synthetische Vorhistorie.
    hist_start = start if start is not None else date(2000, 1, 1)

    hist = await get_portfolio_history(
        db, hist_start, today, user_id=user_id, bucket_id=bucket_id
    )
    points = hist.get("data", [])

    if not points:
        return _empty(period, threshold, bucket_id)

    series = [
        (date.fromisoformat(p["date"]), float(p["portfolio_indexed"]), float(p["value"]))
        for p in points
    ]
    return {
        "period": period,
        "snapshots_count": len(points),
        **_running_peak_drawdown(series, threshold),
        "bucket_id": str(bucket_id) if bucket_id else None,
    }


async def get_max_drawdown(
    db: AsyncSession,
    user_id: uuid.UUID,
    period: str = "ytd",
    *,
    bucket_id: uuid.UUID | None = None,
    brake_threshold_pct: float | None = None,
) -> dict:
    """Compute max drawdown (peak-to-trough) over the period.

    Sowohl Portfolio- als auch Bucket-level leiten aus der
    ``/performance/history``-Kurve (portfolio_indexed) ab — cash-flow-bereinigt,
    konsistent mit jenem Endpoint, kein Phantom-Drawdown aus rohen Snapshot-
    Marktwerten. Bei gesetztem ``bucket_id`` wird die Rekonstruktion auf die
    Positionen des Buckets eingeschraenkt; ``brake_threshold_pct`` ueberschreibt
    den Default-Schwellwert (6%).
    """
    if period not in _VALID_PERIODS:
        raise ValueError(f"Ungueltige Periode: {period}")

    today = date.today()
    start = _period_start(period, today)
    threshold = (
        brake_threshold_pct
        if brake_threshold_pct is not None
        else DRAWDOWN_BRAKE_THRESHOLD_PCT
    )

    return await _indexed_drawdown(
        db, user_id, period, start, today, bucket_id=bucket_id, threshold=threshold
    )
