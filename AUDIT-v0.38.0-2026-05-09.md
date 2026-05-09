# Audit Report — OpenFolio v0.38.0 — 2026-05-09

**Scope:** External REST API Erweiterung (`/api/v1/external/*`) — Release-Commit 3516477  
**Auditor:** @openfolio-audit  
**Urteil:** BEDINGT FREIGEGEBEN — 1 Bug (HOCH) muss vor dem ersten produktiven Einsatz von `/positions/without-type` behoben werden. Alle übrigen Findings sind Verbesserungspotenzial ohne Blockiercharakter.

---

## Zusammenfassung

| Bereich | Bewertung | Kritische Punkte |
|---------|-----------|-----------------|
| Security | PASS | IBAN-Maskierung wasserdicht; Scope-Gating korrekt; Secrets gefiltert |
| HEILIGE Regeln | PASS | Alle Performance-Services nur read-only genutzt |
| Multi-User-Isolation | PASS | Alle Endpoints korrekt user_id-gescoped |
| Audit-Logging | PASS mit Hinweis | Stop-Loss-Audit in separater Transaktion |
| Rate-Limiting | PASS mit Hinweis | Screening per_page=2000 unproportional gross |
| Routing | FAIL | `/positions/without-type` dauerhaft unerreichbar (Shadowingbug) |
| Doku-Realität | PASS mit Hinweis | Scopes-Tabelle in Doku veraltet |
| Testabdeckung | PASS mit Luecken | 62 Tests, 14 Klassen; neue Read-Endpoints ohne Tests |

---

## Findings

| # | Bereich | Severity | Problem | Empfehlung |
|---|---------|----------|---------|------------|
| 1 | Routing | **HOCH** | `GET /positions/without-type` (Zeile 1903) ist dauerhaft unerreichbar. In FastAPI/Starlette werden Routen in Registrierungsreihenfolge evaluiert. Da `GET /positions/{ticker}` (Zeile 221) früher registriert ist, matcht jeder Aufruf von `/positions/without-type` den ticker-Handler mit `ticker="without-type"` — Ergebnis: stets 404. Verifiziert mit Live-Container-Test. | Route nach vorne verschieben (vor Zeile 221) oder Pfad in `/positions/unclassified` umbenennen. Test hinzufügen: `GET /positions/without-type` muss 200 mit einer Liste antworten, kein 404. |
| 2 | Doku | MITTEL | Scopes-Tabelle in `docs/EXTERNAL_API.md` (Zeile 115-116) sagt noch: "Bei Read-Only-Tokens werden persönliche Notizen aus `/watchlist` ausgeblendet." Das ist pre-v0.38-Verhalten. Ab v0.38 liefert `/watchlist` `notes` und die Marker-Felder **immer** aus, auch für read-only Tokens (wie im Changelog Zeile 1313-1315 und im Test `test_read_only_get_watchlist_includes_notes_and_markers` korrekt dokumentiert). Die Scopes-Tabelle widerspricht dem Rest des Dokuments. | Zeile 115: Text anpassen auf "notes und notes_last_api_*-Marker werden immer ausgeliefert". |
| 3 | Audit-Logging | NIEDRIG | Stop-Loss-Update (single + batch): Die Service-Funktionen `update_stop_loss` / `batch_update_stop_loss` committen intern bereits (Zeilen 163/212 in `stoploss_service.py`). Die externen Router-Handler fügen danach `ApiWriteLog`-Einträge in einer **zweiten** Transaktion ein und committen erneut (Zeilen 1672/1705). Wenn der zweite Commit scheitert (z.B. DB-Verbindungsunterbruch), ist der Stop-Loss persistiert, der Audit-Log-Eintrag jedoch verloren. Alle anderen Write-Endpoints (Watchlist, Alerts, Orders) nutzen korrekt einen einzigen Commit. | Stop-Loss-Service-Commit aus dem Service entfernen (oder den ApiWriteLog-Insert vor den Service-Aufruf stellen und beides in einer Transaktion halten). Alternativ: `on_conflict_do_nothing` + Error-Handling dokumentieren. |
| 4 | Performance/Resource | NIEDRIG | `GET /screening/results` erlaubt `per_page` bis zu 2000 (Zeile 2520), während `/transactions` auf 200 begrenzt ist. Ein einzelner Screening-Request kann bei einer grossen DB potenziell Tausende von Zeilen serialisieren — ein valider Angriff innerhalb des Rate-Limits (30 Requests/Minute = bis zu 60'000 Zeilen/Minute). | `le=200` konsistent mit anderen paginierten Endpoints setzen. Grosse Exporte ggf. über Streaming oder einen dedizierten Export-Endpoint anbieten. |
| 5 | Testabdeckung | NIEDRIG | Folgende neue v0.38-Endpoints haben **keine** Smoke-Tests: `/private-equity`, `/private-equity/{id}`, `/precious-metals`, `/precious-metals/sold`, `/precious-metals/expenses`, `/precious-metals/expenses/summary`, `/positions/by-id/{id}/history`, `/positions/by-id/{id}/dividends`, `/dividends/pending`, `/dividends/count`, `/positions/without-type` (letzteres ist ohnehin gebrochen, s. Finding #1). | Je ein Happy-Path-Test pro Endpoint (200 + Shape-Check). Die bestehende `_seed_stock_with_buy`-Hilfsfunktion im Testfile liefert die nötige Datenbasis. |
| 6 | Testabdeckung | NIEDRIG | `test_settings_secrets_masked` prüft nur, dass Klartext-Key absent ist und `has_fred_api_key=True`. Es wird **nicht** explizit geprüft, dass `fred_api_key_masked` (das einen 7-Zeichen-Prefix + 4-Zeichen-Suffix des Klartext-Keys enthält) im externen Response **nicht** vorhanden ist. `filter_settings` entfernt dieses Feld korrekt (Zeile 287 in `external_v1_schemas.py`), aber der Test verifiziert es nicht. | `assert "fred_api_key_masked" not in body` zur Testmethode hinzufügen. |
| 7 | Input-Validierung | INFO | `GET /market/fx/{from_currency}` und `to_currency=Query(...)` haben keine Längen- oder Muster-Einschränkung auf den Currency-String. `get_fx_rate` gibt für unbekannte Währungen stillschweigend `1.0` zurück (Fall: CHF-als-Fallback). Ein Konsument, der z.B. `from_currency=GARBAGE` aufruft, erhält `{"from":"GARBAGE","to":"CHF","rate":1.0}` ohne Fehlermeldung — das kann irreführend sein. | `Pattern r"^[A-Z]{3,4}$"` als Query-Validator ergänzen. |

---

## HEILIGE Regeln — Verifikation

Alle 11 HEILIGEN Regeln wurden geprüft und sind in v0.38.0 eingehalten:

1. **Performance-Berechnung unverändert**: `portfolio_service.py`, `recalculate_service.py`, `price_service.py`, `utils.py` — keine dieser Dateien wurde in `external_v1.py` schreibend aufgerufen. `recalculate_service` ist überhaupt nicht importiert. `get_portfolio_summary` und `get_monthly_returns`/`get_total_return` sind read-only.
2. **MRS-Berechnung**: Nur via `get_mrs_history` in `asyncio.to_thread` gelesen — OK.
3. **Breakout-Logik**: Nur via `get_breakout_events` gelesen — OK.
4. **Immobilien nicht in liquide Performance**: Eigener `/immobilien`-Namespace, kein Einfluss auf `/portfolio/*` oder `/performance/*`.
5. **Vorsorge nicht in liquides Vermögen**: Eigener `/vorsorge`-Namespace.
6. **Private Equity aus Performance ausgeschlossen**: `/private-equity` liest via `get_holdings_summary` / `get_holding_detail` (nur PE-spezifische Felder, kein Einfluss auf Snapshots).
7. **yfinance nur via Wrapper**: Alle yfinance-Aufrufe in `external_v1.py` laufen via `asyncio.to_thread(...)` — `_yf_search`-Closure in `/stock/search` ist in `asyncio.to_thread` eingebettet.
8. **HTTP via httpx**: Keine direkten `requests`-Aufrufe in `external_v1.py`.
9. **SMTP via aiosmtplib**: Kein SMTP in `external_v1.py`.
10. **Signal-Sprache neutral**: Nicht tangiert.
11. **Renditeberechnung**: `performance_history_service.py` und `total_return_service.py` nur read-only gelesen.

---

## Security — Detail

### IBAN-Maskierung

Die Maskierung ist wasserdicht:

- **Portfolio-Positionen** (`GET /positions`, `GET /portfolio/summary`, `GET /positions/{ticker}`): IBAN wird via `_enrich_positions_with_pii` → `decrypt_and_mask_iban` verarbeitet. Klartext-IBAN verlässt die Funktion nie.
- **GET /positions/by-id/{id}**: Direkt `decrypt_and_mask_iban(pos.iban)` — korrekt.
- **Vorsorge** (`GET /vorsorge`, `GET /vorsorge/{id}`): `_pension_to_dict` ruft `decrypt_and_mask_iban` auf — korrekt.
- **Legacy Plaintext-Fallback**: `decrypt_and_mask_iban` maskiert auch unverschlüsselte (Legacy-)IBANs via Substring — kein Klartext-Leak.

### Settings-Secrets

`filter_settings` (Zeile 275-289 in `external_v1_schemas.py`) entfernt:
- `fred_api_key`, `fmp_api_key`, `finnhub_api_key` (Klartext — existieren sowieso nicht im internen Dict)
- `fred_api_key_masked`, `fmp_api_key_masked`, `finnhub_api_key_masked` (7+4-Zeichen-Substring des Klartext-Keys)

Nur `has_*`-Booleans bleiben. Der Mechanismus ist korrekt implementiert und hat einen zweiten Riegel über `SETTINGS_SECRET_FIELDS`.

### Multi-User-Isolation

Alle Endpoints mit user-spezifischen Daten filtern korrekt per `user.id`:

- Portfolio/Positions: `get_portfolio_summary(db, user.id)` — `portfolio_service.py` Zeile 80 filtert `Position.user_id == user_id`.
- Stop-Loss (single): `pos.user_id != user.id` direkt im Router geprüft (Zeile 1650), dann nochmals im Service (Zeile 114).
- Stop-Loss (batch): `Position.user_id == user_id` im Service (Zeile 186) — kein IDOR möglich.
- Private Equity: `PrivateEquityHolding.user_id == user_id` im Service (Zeile 102/127).
- Edelmetalle: `PreciousMetalItem.user_id == user.id` direkt im Router.
- Transaktionen: `Transaction.user_id == user.id` — korrekt.
- Immobilien: `get_property_detail(db, pid, user_id=user.id)` — Service-seitig validiert.

**Einzige Ausnahme (kein IDOR-Risiko, da public):** `GET /screening/scan/{scan_id}/progress` — `ScreeningScan` hat kein `user_id` (Scans sind systemweit, kein User-spezifischer Inhalt). Der Endpunkt liefert nur Status/Steps/Count-Metadata, keine User-Daten.

### Scope-Gating

Alle schreibenden Endpoints prüfen `require_scope(request, "write")` korrekt. Der `_user`-Parameter bei rein öffentlichen Market-Daten-Endpoints (kein User-Context, aber dennoch Auth-Pflicht) ist konsistent. `require_scope` liest aus `request.state.api_token`, das von `get_api_user` gesetzt wird — fail-closed bei fehlendem Token.

### Rate-Limiting

Alle 81 Routen tragen `@limiter.limit(RATE_LIMIT)` (30/Minute), ausser `/health` (intentionally ungeschützt). Die Decorator-Reihenfolge (`@router.get` dann `@limiter.limit`) ist in FastAPI/Slowapi korrekt — Slowapi evaluiert den äusseren Decorator.

---

## Staerken

- **IBAN-Maskierung**: Zwei-Schicht-Schutz (Decrypt-dann-Mask in `decrypt_and_mask_iban`, zusätzlich durch `EXTERNAL_POSITION_FIELDS`-Whitelist). Legacy-Plaintext-IBAN wird ebenfalls maskiert — kein Migrations-Gap.
- **Schema-Entkopplung**: Write-Schemas (`ExternalStopLossUpdate`, `ExternalPendingOrderCreate`, etc.) sind explizit von den internen Schemas entkoppelt. Interne Erweiterungen werden nicht automatisch nach aussen exponiert.
- **`confirmed_at_broker=False`-Default**: Korrekt — API-Call ohne das Feld impliziert keine Broker-Bestätigung. Durch Pydantic-Feld-Default und durch den Test `test_write_token_patches_stop_loss_default_not_confirmed` abgesichert.
- **Batch-Cap (100)**: Der STOP_LOSS_BATCH_MAX_ITEMS-Cap ist auf Pydantic-Ebene (`Field(max_length=...)`) erzwungen — der Validator greift vor Datenbankzugriff. Symmetrie mit `MAX_PENDING_ORDERS_PER_USER`.
- **Audit-Log-Konsistenz**: Alle Write-Endpoints (Watchlist, Alerts, Orders) hinterlassen `ApiWriteLog`-Einträge mit `token_id`, `user_id`, `ticker`, `action`. Nur Stop-Loss leidet am Two-Transaction-Problem (Finding #3).
- **`notes_last_api_*`-Marker**: Provenienz-Felder werden im GET-Response immer ausgeliefert und im PATCH-Response bewusst nicht wiederholt (kein Content-Echo im Audit-Log — verifiziert durch `test_audit_log_does_not_persist_content`).
- **Cascade-Verhalten Watch­list-Delete**: Korrekte Beibehaltung von Stop-Loss-Alarmen bei aktiven Positionen — durch dedizierte Tests abgedeckt.
- **Testtiefe**: 62 Tests in 14 Klassen decken alle kritischen Sicherheitspfade ab: IBAN-Maskierung, Scope-Enforcement, Revocation, Cascade, Stop-Loss-Default, Audit-Log-Persistenz.
