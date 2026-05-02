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


# --- Phase B: Core-Overlap-Flag ---
# Banner / Watchlist-Spalte zeigt indirekte Aktien-Exposure via User-ETFs.
# ≥2% Gewicht im ETF → Eintrag triggert. Phase 1 nur US-ETFs (FMP-Coverage).
CORE_OVERLAP_MIN_WEIGHT_PCT: float = 2.0
# FMP-Holdings refreshen wöchentlich, Daten hinken 30-60 Tage Filings-Lag.
# TTL-Check macht den wöchentlichen Cron idempotent.
CORE_OVERLAP_HOLDINGS_TTL_DAYS: int = 30
# Default-Annahme für Banner-Berechnung "ein Direktkauf von X% würde
# Total-Exposure auf Y% heben" — User-Strategie: 5% pro Position.
CORE_OVERLAP_HYPOTHETICAL_POSITION_PCT: float = 5.0
# Single-Name-Cap der Strategie (NICHT Sektor-Limit, das wäre 15-25%).
# Wird im Banner-Text referenziert: "am oberen Rand des Single-Name-Caps".
CORE_OVERLAP_SINGLE_NAME_CAP_LOW_PCT: float = 6.0
CORE_OVERLAP_SINGLE_NAME_CAP_HIGH_PCT: float = 8.0


# --- Phase 1.1: Sektor-Aggregation + Direkt-Position-Baseline ---
# Sektor-Klassifikation Cascade-Override-Dict (analog INDUSTRY_OVERRIDES).
# Manuelle Manual-Overrides für Tickers wo TradingView/INDUSTRY_TO_SECTOR
# daneben liegt. In Git, reviewbar. Befüllt durch Pre-Deployment-Coverage-Sweep.
SECTOR_OVERRIDES: dict[str, str] = {
    # Befüllt durch Pre-Deployment Coverage-Sweep:
    "BRK-B": "Financials",     # Berkshire Hathaway B (Insurance/Conglomerate)
    "BRK-A": "Financials",     # Berkshire Hathaway A
}

# Sektor-Limit-Schwellen (zwei absolute, KEIN Benchmark-Tilt in Phase 1.1).
# Soft-Warn bei 25%: gelb, "am oberen Rand der Strategie-Range (15-25%)".
# Hard-Warn bei 35%: rot, "deutlich über Strategie-Range, Konzentrationsrisiko".
# Hard-Schwelle bei 35% = Strategie-Mid-Range 20% + 15pp Toleranz für Mag7-Index-Drift.
SECTOR_LIMIT_SOFT_WARN_PCT: float = 25.0
SECTOR_LIMIT_HARD_WARN_PCT: float = 35.0

# Coverage-Schwelle pro ETF: Wenn unclassified_pct ≤ 5% (also Coverage ≥ 95%),
# gilt die Sektor-Aggregation für diesen ETF. Sonst skipped + Cron-Logger
# schreibt unclassified-Tickers für nachträglichen Override-Sweep.
SECTOR_COVERAGE_MIN_PCT: float = 95.0

# Coverage-Suppression: Wenn ein ETF mit ≥10% Portfolio-Weight unter
# SECTOR_COVERAGE_MIN_PCT fällt → ganze Sektor-Aggregation auf
# status=low_coverage. Lieber gar nichts zeigen als verzerrte Zahl
# (z.B. wenn OEF 35% des Portfolios ausmacht und Coverage einbricht,
# wäre Aggregation ohne OEF zugunsten EIMI verschoben — gefährlich).
SECTOR_AGGREGATION_SUPPRESS_ETF_WEIGHT_PCT: float = 10.0


# --- Phase 2 Heartbeat: Wyckoff-Volumen-Profil ---
# Slope-Regression auf log(volumes) in der Range. Normalisiert: % pro Tag
# relativ zum Range-Median-Volumen. -0.5%/d = schrumpfend (Cause-Building),
# +0.5%/d = steigend (atypisch, Distributions-Verdacht). Zone dazwischen
# = neutral, kein Wyckoff-Score.
HEARTBEAT_WYCKOFF_VOLUME_SLOPE_SHRINKING_PCT: float = -0.5
HEARTBEAT_WYCKOFF_VOLUME_SLOPE_RISING_PCT: float = 0.5

# Spring-Marker: Wyckoff-treu = kurze Penetration unter Support mit Vol-Spike.
# Hauptbedingung: low_at_vol_max ≤ support_level (penetriert).
# Floor: low_at_vol_max ≥ support × (1 - 0.02), max 2% darunter — sonst
# wäre es ein Crash, kein Spring. Konstante = Penetrations-Tiefen-Floor.
HEARTBEAT_WYCKOFF_SPRING_PENETRATION_FLOOR_PCT: float = 0.02

# Mindest-Volumen-Datenpunkte in der Range für robusten Slope. <30 → score=None.
HEARTBEAT_WYCKOFF_MIN_RANGE_VOLUME_DAYS: int = 30


# --- v0.30 Long-Accumulation-Detector (FORSCHUNGS-CODE, NICHT PRODUKTIV) ---
# Held-Out 0/3 Recall — siehe LONG_ACCUMULATION_HELD_OUT_RESULTS.md.
# Werte sind aus Phase-1.5-Diagnose abgeleitet, nicht produktiv genutzt.
# Konstanten bleiben als Baseline-Snapshot für v0.31.x-Forschungs-Release.
LONG_ACCUMULATION_LOOKBACK_DAYS: int = 180
LONG_ACCUMULATION_MIN_DURATION_DAYS: int = 60
LONG_ACCUMULATION_MIN_RANGE_PCT: float = 0.05
LONG_ACCUMULATION_RANGE_TOLERANCE: float = 0.03
LONG_ACCUMULATION_ATR_PERIOD: int = 14
LONG_ACCUMULATION_ATR_HISTORY_DAYS: int = 90
LONG_ACCUMULATION_ATR_PERCENTILE: int = 50  # Phase-1.5-Befund: AMD 37, NVDA 43 → 50 mit Buffer
LONG_ACCUMULATION_SWING_LOOKBACK: int = 5
LONG_ACCUMULATION_MIN_HIGH_TOUCHES: int = 3
LONG_ACCUMULATION_MIN_LOW_TOUCHES: int = 3
# WICHTIG: Long-Acc-Detector nutzt Rolling-Median-ATR-Percentile statt Spot,
# anders als Heartbeat (`atr_now = atr_series.iloc[-1]`). Begründung Phase 1.5:
# Spot-ATR im Window-End-Modus zeigte Akku-Cases (AMD/NVDA) bei Percentile
# 99/83 — der Live-Detector hätte denselben Window-End-Bias und würde
# Akkumulationen kurz vor Breakout verwerfen. Coupling auf MIN_DURATION_DAYS
# ist methodisch begründet ("wenn die Range mindestens MIN_DURATION lang
# ist, messen wir den ATR-Rank über genau diese Dauer") — keine willkürliche
# 60d-Wahl. Wer MIN_DURATION ändert, ändert atomar auch das Mess-Window.
LONG_ACCUMULATION_ATR_RANK_WINDOW: int = LONG_ACCUMULATION_MIN_DURATION_DAYS
