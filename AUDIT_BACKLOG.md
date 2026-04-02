# OpenFolio Team-Audit Backlog

**Datum:** 2026-04-02 | **Version:** v0.21.14 → v0.21.20 | **Vorheriges Audit:** 2026-04-01 (73 Findings, 57 behoben)

## Zusammenfassung

| Severity | Total | Behoben | Offen |
|----------|-------|---------|-------|
| CRITICAL | 0 | 0 | 0 |
| HIGH | 4 | 4 | 0 |
| MEDIUM | 12 | 12 | 0 |
| LOW | 8 | 8 | 0 |
| **Total** | **24** | **24** | **0** |

---

## Behoben (20)

| ID | Version | Beschreibung |
|----|---------|--------------|
| SEC-H1 | v0.21.17 | Async httpx Migration (10 sync calls → AsyncClient) |
| SEC-H2 | v0.21.15 | Rate Limits auf 8 Performance GET-Endpoints |
| UX-H1 | v0.21.16 | CommandPalette A11y (role, aria-modal, focus trap, scroll lock) |
| SEC-M1 | — | Kein Fix noetig (`requests` direkt in `yf_patch.py` verwendet) |
| SEC-M2 | v0.21.16 | Watchlist-Limit zentralisiert in `constants/limits.py` |
| SEC-M3 | v0.21.16 | PE-Limits zentralisiert in `constants/limits.py` |
| PERF-M1 | v0.21.18 | 3 FMP-API-Calls parallelisiert mit `asyncio.gather()` |
| PERF-M2 | v0.21.15 | `pytest-cov` zu requirements.txt hinzugefuegt |
| PERF-M3 | v0.21.15 | Rate Limits auf price-alerts, triggered, taxonomy |
| UX-M1 | v0.21.17 | EmptyState.jsx Dead Code entfernt |
| UX-M2 | v0.21.19 | format.js liest jetzt User number_format/date_format Settings |
| ARCH-M1 | v0.21.20 | Migration Hash-Prefix → numerisches Schema (038_) |
| ARCH-M2 | v0.21.17 | daily_change Logik in performance_service extrahiert |
| DOCS-M1 | v0.21.17 | CLAUDE.md Rate-Limit-Zaehler aktualisiert (120/18) |
| DEVOPS-M1 | v0.21.18 | Frontend Dockerfile non-root User |
| SEC-L1 | v0.21.19 | Type Hints in alert_service.py verifiziert (bereits vollstaendig) |
| ARCH-L1 | v0.21.18 | Unbenutzter ttl-Parameter aus _get_cached entfernt |
| ARCH-L2 | v0.21.18 | Silent except:pass → logger.warning in Migration 023 |
| UX-L1 | v0.21.20 | Glossar-Link mit BookOpen-Icon in Sidebar |
| DOCS-L1 | v0.21.20 | README.md Drift behoben (Rate-Limit-Zaehler, Mobile-Referenz) |
| DEVOPS-L1 | v0.21.19 | Redis no-persistence in CLAUDE.md dokumentiert |
| DEVOPS-L2 | v0.21.19 | Monitoring optional/manuell in CLAUDE.md dokumentiert |

---

## Offen (0)

Alle Findings behoben. UX-M2-NOTE manuell verifiziert (2026-04-02).

---

## Nachtraeglich behoben

| ID | Version | Beschreibung |
|----|---------|--------------|
| QA-H1 | v0.21.20 | 13 API-Router abgedeckt (~136 Tests in 13 Dateien) |
| QA-L1 | v0.21.21 | Vitest eingerichtet, 42 Frontend-Tests (format.js, tradingview.js) |
| ARCH-M1-NOTE | v0.21.20 | Alembic Naming in alembic.ini dokumentiert |
