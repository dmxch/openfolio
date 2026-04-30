"""[DEPRECATED in v0.29.0] — Re-Export-Alias für concentration_service.

Phase B (v0.28.0) hat diesen Service unter dem Namen `core_overlap_service`
gebaut. Phase 1.1 hat den Scope auf volles Konzentrations-Bild erweitert
(Direkt-Position + Sektor-Aggregation), daher Rename auf `concentration_service`.

Dieses Modul bleibt 1 Release als Backward-Compat-Alias für externe
Caller (Watchlist-Service, ältere Imports). Wird in v0.30.x entfernt.
"""
from services.concentration_service import (  # noqa: F401
    get_overlap_for_ticker,
    get_overlap_max_weight_for_tickers,
)
