"""Tunables for chart-pattern detectors (MA-Cross, Heartbeat, Volume-Spike).

Centralised here for the same reason ``sector_rotation_config`` exists:
threshold-justierungen ohne Code-Hunt durch detector-Files.

Each constant is named with the pattern domain prefix (MA_CROSS_*,
HEARTBEAT_*, VOLUME_*) so a grep against the prefix shows the full
surface area for that domain.
"""
from decimal import Decimal


# --- MA-Cross 50/150 (Bullish-Cross & Death-Cross) ---
MA_CROSS_FAST: int = 50
MA_CROSS_SLOW: int = 150

# Cross zählt als "frisch" wenn das Vorzeichen der MA-Diff in den
# letzten N Handelstagen gewechselt hat. 60 Tage waren in der ersten
# Plan-Iteration — nach 60 Tagen ist die Bewegung typisch gelaufen,
# das "Trendwende"-Label trifft nicht mehr.
MA_CROSS_LOOKBACK_DAYS: int = 20

# Failed-Cross-Filter: ein Bullish-Cross gilt als tot, wenn der Preis
# seit dem Cross-Datum mehr als X% gegen die Richtung gelaufen ist
# (Setup-Invalidierung). Symmetrisch für Death-Cross.
MA_CROSS_FAILED_PCT: float = 0.05


# --- Heartbeat-Pattern (Felix Prinz, Phase 1: ATR-Compression statt Volume) ---

# Zwei Touches an einem Resistance- oder Support-Level zählen zum
# selben "Cluster", wenn ihre relative Preis-Differenz innerhalb dieser
# Toleranz liegt. ±3% ist eng genug, um echte horizontale Levels zu
# identifizieren, weit genug, um normales Tagesrauschen zu schlucken.
HEARTBEAT_RANGE_TOLERANCE: float = 0.03

# Ein Heartbeat muss mindestens 30 Tage zwischen erstem und letztem
# Touch liegen — sonst ist es kein Pattern, sondern Tagesrauschen.
HEARTBEAT_MIN_DURATION_DAYS: int = 30

# Box muss mindestens 3% breit sein. Eine Range ≤ 3% ist für Trading
# irrelevant (jede Bewegung ist Lärm im Verhältnis zum Setup).
HEARTBEAT_MIN_RANGE_PCT: float = 0.03

# Suchfenster für Touches.
HEARTBEAT_LOOKBACK_DAYS: int = 120

# ATR-Compression-Filter — percentile-basiert, nicht differenz-basiert.
# Begründung: ein Stock, der seit 60 Tagen flach läuft (klassischer
# Heartbeat), hat atr_now ≈ atr_30d_ago — ein Differenz-Check würde
# das herausfiltern, obwohl es genau das gesuchte Pattern ist. Der
# Percentile-Ansatz erkennt persistent niedrige Volatilität.
HEARTBEAT_ATR_PERIOD: int = 14
HEARTBEAT_ATR_HISTORY_DAYS: int = 90
HEARTBEAT_ATR_PERCENTILE: int = 30  # ≤ percentile(atr_history, 30) erforderlich

# Lookback für Swing-High/Low-Detection (symmetrisches Fenster).
HEARTBEAT_SWING_LOOKBACK: int = 5


# --- Volumen-Spike-Down (Distribution Day, Risiken-Gruppe) ---
# Volume-Spike + Down-Day in den letzten N Tagen → aktives Distributions-Signal.
VOLUME_SPIKE_MULTIPLIER: float = 3.0
VOLUME_SPIKE_LOOKBACK_DAYS: int = 20
VOLUME_SPIKE_AVG_WINDOW: int = 20  # Avg-Volume-Berechnungs-Fenster


# --- Phase A: 2-Tages-Confirm Donchian-Breakout ---
# Tag 1 = klassischer Donchian-Breakout + Volumen ≥ 1.5×.
# Tag 2 = Close hält über demselben 20d-Hoch. Verhindert Fakeouts.
DONCHIAN_CONFIRM_DAYS: int = 2


# --- Phase A: Earnings-Proximity-Veto (harter Block) ---
# Wenn next_earnings_date - today < EARNINGS_PROXIMITY_DAYS:
# - id=19 Risiken-Kriterium passed=False
# - setup_quality wird auf "BEOBACHTEN" gecapt (kein STARK in Earnings-Woche)
EARNINGS_PROXIMITY_DAYS: int = 7


# --- Phase A: Distance-from-MA50 (Modifier id=20) ---
# pct_above_ma50 = (close - ma50) / ma50
MA50_DISTANCE_HEALTHY_PCT: float = 0.15      # 0..15% über MA50 → score_modifier = +1
MA50_DISTANCE_OVEREXTENDED_PCT: float = 0.25  # > 25% → score_modifier = -1
                                              # Dazwischen → 0 (neutral)


# --- Phase A: Volume-Confirmation (Modifier id=21) ---
# Linear-Regression-Slope der 20 Closes (normalisiert auf Anfangskurs) gegen
# Vol-Ratio = mean(winsorized(volumes_20d)) / mean(winsorized(volumes_60d)).
# Asymmetrische Schwellen für Mega-Caps weil VolRatio dort strukturell
# näher an 1.0 klebt (institutionelle Liquidität).
VOLUME_CONFIRM_SLOPE_THRESHOLD_PCT: float = 3.0   # |slope| ≤ 3% = Grauzone, modifier=0
VOLUME_CONFIRM_RATIO_LOW: float = 0.85
VOLUME_CONFIRM_RATIO_HIGH: float = 1.15
VOLUME_CONFIRM_MEGACAP_RATIO_LOW: float = 0.75
VOLUME_CONFIRM_MEGACAP_RATIO_HIGH: float = 1.25
VOLUME_CONFIRM_MEGACAP_THRESHOLD_USD: float = 500_000_000_000.0
VOLUME_CONFIRM_MCAP_SMOOTHING_DAYS: int = 90
# Top-N-Volume-Tage trimmen (~5%-Winsorization), nicht nur Top-1 — fängt
# 2-3-Tages-Earnings-Reactions die das 20d-Avg sonst wochenlang verzerren.
VOLUME_CONFIRM_WINSORIZATION_TOP_N: int = 3


# --- Phase A: Industry-Mapping-Overrides (für Falsch-Mappings aus TradingView) ---
# Wird im Pre-Deployment Sanity-Check (Plan-Punkt 1) befüllt — Falsch-Mappings
# wie AMAT als "Industrial Machinery" statt "Semiconductor Equipment" werden
# hier vor Live-Schaltung korrigiert. Override hat Vorrang vor ticker_industries.
INDUSTRY_OVERRIDES: dict[str, str] = {
    # Beispiel-Form, befüllt durch Sanity-Check:
    # "AMAT": "Semiconductor Equipment",
}


# --- Phase A: Industry-MRS (Score-Kriterium id=22) ---
# Phase 1: einfache Variante — perf_3m der Industry vs S&P-perf_3m,
# mit ±2pp Buffer-Zone gegen Endpunkt-Sensitivität.
INDUSTRY_MRS_PERIOD: str = "perf_3m"
INDUSTRY_MRS_BENCHMARK: str = "^GSPC"
INDUSTRY_MRS_BUFFER_PCT: float = 0.02  # ±2 Prozentpunkte neutrale Zone


# --- Phase A: Score-Aggregation (asymmetrische Modifier-Wirkung — Risk-First) ---
# Display-pct: kosmetisch, positive UND negative Modifier wirken voll.
# Quality-pct: NUR negative Modifier wirken (degradieren). Positive Modifier
# können ein schwaches Setup nicht künstlich auf STARK heben — verhindert
# Late-Stage-Bug, in dem ein 16/18-Setup mit Distribution-Verdacht trotzdem
# als STARK durchgewunken wurde.
MODIFIER_WEIGHT_PCT_DISPLAY: int = 3
MODIFIER_WEIGHT_PCT_QUALITY: int = 8
