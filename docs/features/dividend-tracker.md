# Feature-Spec: Dividenden-Tracker

**Version:** 1.0  
**Datum:** 2026-05-08  
**Status:** Bereit zur Implementierung  
**Autor:** Design-Agent (OpenFolio)

---

## 1. Problem & Kontext

### Problem
User erfassen empfangene Dividenden in OpenFolio nicht oder vergessen es. Da `TransactionType.dividend` bereits existiert, gehen diese Einnahmen im XIRR/Total-Return komplett verloren und verfälschen die angezeigte Gesamtrendite. Das Problem trifft alle Personas gleichermassen — Self-Hosted-Investor, Power-User und Einsteiger — wobei Einsteiger am häufigsten betroffen sind, weil sie den Transaktions-Workflow noch nicht verinnerlicht haben.

### Lösungsansatz
Der Worker prüft täglich per yfinance-Ex-Date, ob für jede aktive stock/ETF-Position Dividendenzahlungen stattgefunden haben, die noch keine korrespondierende `dividend`-Transaktion besitzen. Offene Fälle werden als `pending_dividends`-Datensätze persistiert und im UI als dediziertes Dashboard-Widget mit Counter-Badge sichtbar gemacht.

### Multi-User-Constraint
OpenFolio ist multi-user-fähig. Alle Queries, Worker-Loops, API-Endpunkte und UI-Daten müssen zwingend auf `user_id` gescoped sein. Es darf niemals ein ungefilterter Query über alle User laufen, ausser explizit für Admin-Zwecke vorgesehen.

---

## 2. User Stories

### Story A — Offene Dividende erfassen

**Als** Portfolio-Inhaber  
**möchte ich** sehen, welche Dividenden meiner Positionen laut Ex-Date fällig waren, aber noch nicht als Transaktion erfasst sind,  
**damit** mein XIRR und meine Gesamtrendite vollständig und korrekt ausgewiesen werden.

#### Acceptance Criteria

**AC-A1: Widget erscheint nur wenn Einträge vorhanden**
- Given: Ich habe mindestens eine offene Pending-Dividende mit Status `pending`
- When: Ich die Portfolio-Seite oder die Dashboard-Seite aufrufe
- Then: Das Widget "Offene Dividenden" ist sichtbar mit der Anzahl ausstehender Einträge

**AC-A2: Confirm öffnet vorausgefülltes Modal**
- Given: Ich sehe einen Pending-Eintrag für AAPL, Ex-Date 2026-02-07, 0.25 USD/Aktie, 50 Aktien
- When: Ich auf "Erfassen" klicke
- Then: Das Transaktions-Modal öffnet sich mit vorausgefüllten Feldern:
  - Typ: Dividende
  - Position: AAPL (nicht editierbar — gleiche Position)
  - Datum: 2026-02-07 (editierbar)
  - Bruttobetrag CHF: `expected_gross_chf` (editierbar)
  - Nettobetrag CHF: `expected_gross_chf * (1 - withholding_default)` (editierbar)
  - Währung: USD (editierbar)

**AC-A3: Nach Erfassen verschwindet der Eintrag aus dem Widget**
- Given: Ich bestätige die vorausgefüllte Transaktion im Modal
- When: Die Transaktion erfolgreich gespeichert wurde
- Then: Der entsprechende Pending-Eintrag erhält Status `confirmed`, verschwindet aus der Widget-Liste und der Badge-Counter reduziert sich um 1

**AC-A4: Badge ist 0 wenn keine offenen Einträge**
- Given: Alle Pending-Dividenden haben Status `confirmed` oder `dismissed`
- When: Ich eine beliebige Seite aufrufe
- Then: Das Badge im Top-Bar ist nicht sichtbar, das Widget ist nicht gerendert

---

### Story B — Dividende ablehnen

**Als** Portfolio-Inhaber  
**möchte ich** einen Pending-Eintrag als irrelevant markieren können,  
**damit** ich Dividenden, die ich bewusst nicht erfassen möchte (z.B. bereits in der Broker-Abrechnung konsolidiert), dauerhaft aus der Liste entfernen kann.

#### Acceptance Criteria

**AC-B1: Dismiss entfernt Eintrag dauerhaft aus der Liste**
- Given: Ein Pending-Eintrag ist sichtbar im Widget
- When: Ich auf "Ignorieren" klicke und den Bestätigungs-Dialog bestätige
- Then: Der Eintrag erhält Status `dismissed`, verschwindet aus der Liste, der Counter sinkt

**AC-B2: Dismissed Einträge werden nicht erneut erstellt**
- Given: Ein Eintrag für Position X, Ex-Date Y hat Status `dismissed`
- When: Der Worker erneut läuft
- Then: Kein neuer Pending-Eintrag für dieselbe Kombination (Position X, Ex-Date Y) wird erstellt (UNIQUE-Constraint schützt, Worker prüft vorher)

**AC-B3: Dismiss erfordert Bestätigung**
- Given: Ich klicke auf "Ignorieren"
- When: Der Bestätigungs-Dialog erscheint
- Then: Der Text erklärt, dass der Eintrag dauerhaft ausgeblendet wird — ohne imperativ oder wertend

---

### Story C — Einstellung: Quellensteuer-Standard

**Als** Portfolio-Inhaber  
**möchte ich** meinen Standard-Quellensteuersatz konfigurieren können,  
**damit** der vorausgefüllte Nettobetrag im Erfassungs-Modal meiner Steuersituation entspricht und ich weniger manuell korrigieren muss.

#### Acceptance Criteria

**AC-C1: Einstellung ist in den Settings sichtbar und persistiert**
- Given: Ich navigiere zu Einstellungen → Portfolio
- When: Ich den Wert bei "Standard-Quellensteuer (%)" von 35 auf 15 ändere und speichere
- Then: Der neue Wert wird unter `dividend_withholding_default` für meinen User gespeichert und beim nächsten Modal-Aufruf als Basis für die Netto-Berechnung verwendet

**AC-C2: Default ist 35% (Schweizer Verrechnungssteuer)**
- Given: Ein neuer User hat `dividend_withholding_default` noch nicht konfiguriert
- When: Das Confirm-Modal für eine Pending-Dividende öffnet sich
- Then: Der Netto-Vorschlag basiert auf 35% Abzug

**AC-C3: Eingabefeld akzeptiert nur 0–100**
- Given: Ich bin im Einstellungs-Formular
- When: Ich einen Wert < 0 oder > 100 eingebe
- Then: Clientseitige Validierung verhindert das Speichern mit einer deutschen Fehlermeldung

---

## 3. Scope (MoSCoW)

### Must (MVP)
- Datenmodell `pending_dividends` mit allen Pflichtfeldern (siehe Abschnitt 4)
- Worker-Job täglich 09:00 CET, der für alle aktiven stock/ETF-Positionen aller User prüft
- Initial-Seeding: Lookback 90 Tage beim ersten Run, danach Rolling
- Auto-Match beim Erfassen einer `dividend`-Transaktion (±60d Ex-Date)
- GET `/api/dividends/pending` (nur Status `pending`)
- POST `/api/dividends/{id}/confirm` (legt Transaktion an, matched Eintrag)
- POST `/api/dividends/{id}/dismiss`
- Dashboard-Widget "Offene Dividenden"
- Top-Bar-Badge mit Counter (bestehende `AlertBadge`-Infrastruktur erweitern)
- User-Setting `dividend_withholding_default` (Default 0.35)
- Refactor `dividend_service.py`: weg von `yf.Ticker()` direkt, hin zu `asyncio.to_thread` + `yf_download`-Pattern (Heilige Regel #7)

### Should (v1, nach MVP)
- E-Mail-Benachrichtigung via bestehende `AlertPreference`-Infrastruktur (`category="pending_dividend"`, `notify_email`)
- GET `/api/dividends/pending` mit optionalem `?include_dismissed=true` für Admin-Debugging
- Widget auf der Portfolio-Seite zusätzlich zum Dashboard
- Link vom Pending-Eintrag direkt zur Position in der Portfolio-Tabelle

### Could (Später)
- Jahres-Dividendenübersicht (total CHF erhalten pro Jahr, nach Position/Sektor aufgeschlüsselt)
- Dividend-Yield-Schätzung auf Basis bekannter ex-dates der letzten 12 Monate
- CSV-Export der erfassten Dividenden-Transaktionen

### Won't (Out of Scope — explizit)
- Pay-Date-Tracking (yfinance liefert es unzuverlässig, Entscheidung getroffen)
- Crypto-Staking-Rewards (anderer Mechanismus, anderer Scope)
- Multi-Currency-Reporting für Steuerzwecke (kein Steuerberater-Tool)
- Automatische Verrechnungssteuer-Rückforderungs-Workflows
- Dividenden auf Immobilien, Vorsorge, Private Equity, Edelmetalle
- Dividenden-Prognose / Forward-Yield basierend auf Analystenschätzungen

---

## 4. Datenmodell

### 4.1 Neue Tabelle: `pending_dividends`

```sql
CREATE TABLE pending_dividends (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    position_id     UUID NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    ex_date         DATE NOT NULL,
    dividend_per_share   NUMERIC(14, 6) NOT NULL,
    currency        VARCHAR(10) NOT NULL,
    shares_at_ex_date    NUMERIC(20, 8) NOT NULL,
    expected_gross_chf   NUMERIC(14, 2) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
                    -- Werte: 'pending' | 'confirmed' | 'dismissed'
    matched_transaction_id UUID REFERENCES transactions(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_pending_dividend_user_position_exdate
        UNIQUE (user_id, position_id, ex_date),
    CONSTRAINT ck_pending_dividend_status
        CHECK (status IN ('pending', 'confirmed', 'dismissed'))
);

CREATE INDEX idx_pending_dividends_user_status
    ON pending_dividends (user_id, status);

CREATE INDEX idx_pending_dividends_position
    ON pending_dividends (position_id);

CREATE INDEX idx_pending_dividends_matched_txn
    ON pending_dividends (matched_transaction_id)
    WHERE matched_transaction_id IS NOT NULL;
```

**SQLAlchemy-Model-Datei:** `backend/models/pending_dividend.py`

Felder als Mapped Columns (analog bestehende Models):
- `status` als `String(20)`, nicht als Enum, damit kein Alembic-Enum-Migration-Overhead entsteht
- `matched_transaction_id` nullable FK mit `ON DELETE SET NULL` (wenn Transaktion gelöscht wird, kehrt Eintrag zu `pending` zurück — siehe Edge Case d)

### 4.2 Neues User-Setting: `dividend_withholding_default`

Erweiterung der bestehenden `User`-Tabelle (oder `UserSettings`, je nach bestehender Implementierung — prüfen ob `User`-Model direkt oder separates Settings-Model existiert):

```sql
ALTER TABLE users
    ADD COLUMN dividend_withholding_default NUMERIC(5, 4) NOT NULL DEFAULT 0.3500;
-- Wertebereich 0.0000 – 1.0000, repr. 0% – 100%
-- Default 0.35 = 35% (Schweizer Verrechnungssteuer)
```

Alembic-Migration: `057_add_pending_dividends.py`

---

## 5. API-Endpunkte

Neuer Router: `backend/api/dividends.py`  
Prefix: `/api/dividends`  
Eingebunden in `main.py` via `app.include_router(dividends.router)`

### 5.1 GET `/api/dividends/pending`

Gibt alle offenen Pending-Dividenden des eingeloggten Users zurück.

**Query-Parameter:**
- `status: str = "pending"` — erlaubte Werte: `pending`, `confirmed`, `dismissed`
- `limit: int = 50` (max 200)

**Response-Schema:**
```python
class PendingDividendItem(BaseModel):
    id: uuid.UUID
    position_id: uuid.UUID
    ticker: str           # Join auf positions.ticker
    position_name: str    # Join auf positions.name
    ex_date: date
    dividend_per_share: float
    currency: str
    shares_at_ex_date: float
    expected_gross_chf: float
    expected_net_chf: float   # server-side: gross * (1 - user.dividend_withholding_default)
    status: str
    matched_transaction_id: uuid.UUID | None
    created_at: datetime

class PendingDividendsResponse(BaseModel):
    items: list[PendingDividendItem]
    total: int
    withholding_default_pct: float  # z.B. 35.0 — für UI-Anzeige
```

**Implementierungshinweis:** Join `pending_dividends` mit `positions` auf `position_id`, gefiltert auf `user_id = current_user.id` und `status = ?`. `expected_net_chf` wird serverseitig berechnet, nie persistiert (leitet sich aus `withholding_default` ab, die der User jederzeit ändern kann).

---

### 5.2 POST `/api/dividends/{id}/confirm`

Legt eine `dividend`-Transaktion an und markiert den Pending-Eintrag als `confirmed`.

**Path-Parameter:** `id: uuid.UUID` — ID des Pending-Eintrags

**Request-Schema:**
```python
class ConfirmDividendRequest(BaseModel):
    date: date                          # Default: ex_date des Eintrags
    total_chf: float                    # Nettobetrag (nach Quellensteuer), Pflicht
    gross_amount: float | None = None   # Optional: Bruttobetrag CHF
    currency: str                       # Default: currency des Eintrags
    fx_rate_to_chf: float = 1.0
    notes: str | None = Field(default=None, max_length=2000)
```

**Verhalten:**
1. Pending-Eintrag laden, Ownership prüfen (`user_id == current_user.id`), Status muss `pending` sein (sonst 409 Conflict mit Meldung "Bereits erfasst oder ignoriert")
2. `Transaction` anlegen:
   - `type = TransactionType.dividend`
   - `position_id` aus Pending-Eintrag
   - `user_id = current_user.id`
   - `shares = 0` (Dividenden ändern den Bestand nicht)
   - `price_per_share = 0`
   - `total_chf = request.total_chf`
   - `gross_amount = request.gross_amount` (falls angegeben)
   - `tax_amount = gross_amount - total_chf` (falls beide vorhanden)
   - restliche Felder aus Request
3. Pending-Eintrag updaten: `status = 'confirmed'`, `matched_transaction_id = txn.id`, `updated_at = now()`
4. `invalidate_portfolio_cache(user_id)` aufrufen
5. `trigger_snapshot_regen(user_id, date)` aufrufen (damit XIRR/Total-Return aktualisiert wird)

**Response:** 201, Objekt mit `transaction_id: uuid`, `pending_id: uuid`, `status: "confirmed"`

**Fehler:**
- 404: Eintrag nicht gefunden oder gehört anderem User
- 409: Status ist nicht `pending`

---

### 5.3 POST `/api/dividends/{id}/dismiss`

Markiert einen Pending-Eintrag dauerhaft als ignoriert.

**Path-Parameter:** `id: uuid.UUID`

**Request-Schema:**
```python
class DismissDividendRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    # Optionales Freitext-Feld, wird in notes persistiert (verschlüsselt)
```

**Verhalten:**
1. Ownership prüfen, Status muss `pending` sein (sonst 409)
2. `status = 'dismissed'`, `updated_at = now()`
3. Falls `reason` angegeben: in einem separaten `notes`-Feld auf dem Pending-Eintrag speichern (verschlüsselt via `encrypt_field`, analog `transaction.notes`)
   - Hinweis: Dafür muss das `pending_dividends`-Schema ein optionales `notes TEXT`-Feld erhalten
4. Kein Portfolio-Cache-Invalidierung nötig (keine Transaktion angelegt)

**Response:** 200, `{"status": "dismissed", "id": "..."}`

---

### 5.4 GET `/api/dividends/count` (für Badge)

Schneller Endpunkt für den Badge-Counter — kein Join, nur COUNT.

**Response:**
```python
class DividendCountResponse(BaseModel):
    pending_count: int
```

Filterung: `user_id = current_user.id AND status = 'pending'`

Dieser Endpunkt wird vom Frontend regelmässig gepollt (alle 5 Minuten) oder nach jeder confirm/dismiss-Aktion neu aufgerufen.

---

### 5.5 Erweiterung: Settings-Endpunkt

Der bestehende `PUT /api/settings` (in `backend/api/settings.py`) erhält ein neues optionales Feld in `SettingsUpdate`:

```python
dividend_withholding_default: Optional[float] = Field(default=None, ge=0.0, le=1.0)
```

Der entsprechende Service-Layer in `settings_service.py` persistiert den Wert auf `users.dividend_withholding_default`.

---

## 6. Worker-Job

### 6.1 Neue Funktion in `worker.py`

```python
async def _check_pending_dividends():
    """Täglich: Dividenden-Ex-Dates gegen erfasste Transaktionen prüfen."""
    try:
        from services.pending_dividend_service import run_dividend_detection
        async with async_session() as db:
            result = await run_dividend_detection(db)
            logger.info(
                "Dividend detection: created=%s matched=%s skipped=%s errors=%s",
                result.get("created"),
                result.get("matched"),
                result.get("skipped"),
                result.get("errors"),
            )
    except Exception:
        logger.exception("Dividend detection failed")
```

### 6.2 Scheduler-Eintrag (in `main()`)

```python
# Dividenden-Detection täglich 09:30 CET (nach daily_refresh 07:00, 
# nach 13F-Refresh 08:00 — FX-Rates aus Cache sind frisch)
scheduler.add_job(
    _check_pending_dividends,
    CronTrigger(hour=9, minute=30, timezone="Europe/Zurich"),
    id="dividend_detection",
)
```

**Begründung 09:30 CET:** Daily refresh (inkl. FX-Rates, Price-Cache) läuft um 07:00. 13F läuft um 08:00. Um 09:30 sind FX-Rates frisch, die für `expected_gross_chf`-Berechnung gebraucht werden.

---

### 6.3 Neuer Service: `backend/services/pending_dividend_service.py`

#### Pseudocode: `run_dividend_detection(db)`

```
FUNKTION run_dividend_detection(db):
    stats = {created: 0, matched: 0, skipped: 0, errors: 0}

    # Schritt 1: Alle aktiven User laden (multi-user: pro User separat)
    users = SELECT DISTINCT user_id 
            FROM positions 
            WHERE is_active = TRUE AND type IN ('stock', 'etf') AND shares > 0

    FÜR JEDEN user_id IN users:
        TRY:
            await _detect_for_user(db, user_id, stats)
        EXCEPT:
            stats.errors += 1
            logger.warning(...)

    RETURN stats


FUNKTION _detect_for_user(db, user_id, stats):
    # Aktive stock/ETF-Positionen dieses Users
    positions = SELECT * FROM positions 
                WHERE user_id = user_id 
                  AND type IN ('stock', 'etf') 
                  AND is_active = TRUE 
                  AND shares > 0

    # Lookback bestimmen
    # Initial-Seeding: wenn der User noch keinen Pending-Eintrag hat → 90 Tage
    # Sonst: letzte 35 Tage (Rolling, um Ex-Dates kurz nach Monatswechsel abzudecken)
    has_any_pending = COUNT(*) > 0 FROM pending_dividends WHERE user_id = user_id
    lookback_days = 90 IF NOT has_any_pending ELSE 35
    since_date = today - lookback_days

    # Concurrency-Semaphore: max 3 gleichzeitige yfinance-Calls pro User
    # (Rate-Limiting-Schutz)
    sem = asyncio.Semaphore(3)

    PARALLEL FÜR JEDE position IN positions:
        await _detect_for_position(db, user_id, position, since_date, sem, stats)


FUNKTION _detect_for_position(db, user_id, position, since_date, sem, stats):
    ASYNC WITH sem:
        ticker = position.yfinance_ticker OR position.ticker

        # yfinance NUR via asyncio.to_thread + yf_download-Pattern (Heilige Regel #7)
        # WICHTIG: yf.Ticker().dividends ist KEIN Download-Call, sondern ein
        # Property-Zugriff. Trotzdem muss er in asyncio.to_thread() gewrappt werden,
        # da er synchron HTTP macht. yf_download() deckt nur OHLCV ab.
        # Lösung: asyncio.to_thread(lambda: yf.Ticker(ticker).dividends)
        # Dies ist der einzig korrekte Weg für dividend-Data. Kein direkter 
        # async-Aufruf.
        divs = await asyncio.to_thread(lambda: yf.Ticker(ticker).dividends)

        WENN divs leer oder None:
            stats.skipped += 1
            RETURN

        # Filtern auf since_date bis heute
        divs = divs[divs.index.date >= since_date]

        FÜR JEDES (ex_date, div_per_share) IN divs:
            # Prüfen ob bereits Eintrag (UNIQUE verhindert Duplikat, aber vorher prüfen)
            existing = SELECT id, status FROM pending_dividends
                       WHERE user_id = user_id 
                         AND position_id = position.id 
                         AND ex_date = ex_date

            WENN existing:
                # Bereits bekannt — nichts tun (dismissed bleibt dismissed)
                CONTINUE

            # shares_at_ex_date: aus Transaktionshistorie rekonstruieren
            # (analog _calculate_position_values aus recalculate_service.py)
            shares_at_date = _reconstruct_shares_at_date(
                transactions_of_position, ex_date
            )

            WENN shares_at_date <= 0:
                # User hatte die Position am Ex-Date nicht (oder bereits verkauft)
                stats.skipped += 1
                CONTINUE

            # FX-Rate für Umrechnung in CHF (via get_fx_rate aus services/utils.py)
            div_currency = _get_ticker_currency(ticker)  # aus yf.fast_info oder Position.currency
            fx = get_fx_rate(div_currency, "CHF")

            expected_gross_chf = round(shares_at_date * float(div_per_share) * fx, 2)

            WENN expected_gross_chf <= 0:
                stats.skipped += 1
                CONTINUE

            # Auto-Match: existiert bereits eine dividend-Transaktion für diese 
            # Position nahe diesem Ex-Date?
            match_window_start = ex_date - 60 Tage
            match_window_end   = ex_date + 60 Tage

            existing_txn = SELECT id FROM transactions
                           WHERE position_id = position.id
                             AND user_id = user_id
                             AND type = 'dividend'
                             AND date BETWEEN match_window_start AND match_window_end
                           LIMIT 1

            WENN existing_txn:
                # Auto-Match: sofort als confirmed anlegen
                INSERT INTO pending_dividends (..., status='confirmed', 
                    matched_transaction_id=existing_txn.id)
                stats.matched += 1
            SONST:
                INSERT INTO pending_dividends (..., status='pending')
                stats.created += 1

    await db.commit()
```

#### Hilfsfunktion: `_reconstruct_shares_at_date(transactions, target_date)`

Diese Funktion verwendet die gleiche Logik wie `_calculate_position_values` aus `recalculate_service.py`, bricht aber ab sobald `target_date` überschritten wird. Sie darf `recalculate_service._calculate_position_values` **nicht** aufrufen (Heilige Regel #1), sondern repliziert die Shares-Zählung als read-only Berechnung ohne Position-Mutation:

```
shares = 0.0
FÜR JEDE txn IN transactions (aufsteigend nach date, created_at):
    WENN txn.date > target_date: BREAK
    WENN txn.type IN (buy, delivery_in): shares += txn.shares
    WENN txn.type IN (sell, delivery_out): shares = max(0, shares - txn.shares)
RETURN shares
```

**Wichtig:** Diese Funktion ist read-only und berührt weder `position.shares` noch `position.cost_basis_chf` — Heilige Regel #1 bleibt gewahrt.

---

## 7. Auto-Match-Hook

### Wo wird gehookt?

Der Auto-Match muss an **zwei Stellen** ausgelöst werden:

#### Hook 1: Manuelles Erfassen via `POST /api/transactions`

In `backend/api/transactions.py`, Funktion `create_transaction`, **nach** `await db.commit()` und **nach** `trigger_snapshot_regen`:

```python
# Dividenden-Auto-Match (non-blocking, best-effort)
if data.type == TransactionType.dividend:
    try:
        from services.pending_dividend_service import try_auto_match_transaction
        await try_auto_match_transaction(db, txn, user.id)
    except Exception as e:
        logger.warning(f"Dividend auto-match failed for txn {txn.id}: {e}")
```

#### Hook 2: CSV-Import via `POST /api/import/confirm`

In `backend/services/import_service.py`, Funktion `confirm_import`, nach dem Bulk-Insert aller Transaktionen und `recalculate_all_positions`, analog Hook 1:

```python
# Dividenden-Auto-Match für alle importierten dividend-Transaktionen
dividend_txns = [t for t in created_transactions if t.type == TransactionType.dividend]
if dividend_txns:
    try:
        from services.pending_dividend_service import try_auto_match_transactions_bulk
        await try_auto_match_transactions_bulk(db, dividend_txns, user_id)
    except Exception as e:
        logger.warning(f"Dividend bulk auto-match failed: {e}")
```

#### Hook 3: Transaction-Delete (Rückwärts-Hook)

In `backend/api/transactions.py`, Funktion `delete_transaction`, **vor** `await db.delete(txn)`:

```python
# Wenn gelöschte Transaktion eine gematchte Pending-Dividende hat → zurücksetzen
if txn.type == TransactionType.dividend:
    try:
        from services.pending_dividend_service import unmatch_on_transaction_delete
        await unmatch_on_transaction_delete(db, txn.id, txn.user_id)
    except Exception as e:
        logger.warning(f"Dividend unmatch failed for txn {txn.id}: {e}")
```

### Service-Funktion: `try_auto_match_transaction`

```
FUNKTION try_auto_match_transaction(db, txn, user_id):
    window_start = txn.date - 60 Tage
    window_end   = txn.date + 60 Tage

    pending = SELECT * FROM pending_dividends
              WHERE position_id = txn.position_id
                AND user_id = user_id
                AND status = 'pending'
                AND ex_date BETWEEN window_start AND window_end
              ORDER BY ABS(ex_date - txn.date) ASC  -- nächstes Ex-Date zuerst
              LIMIT 1

    WENN pending:
        pending.status = 'confirmed'
        pending.matched_transaction_id = txn.id
        pending.updated_at = now()
        await db.commit()
```

### Service-Funktion: `unmatch_on_transaction_delete`

```
FUNKTION unmatch_on_transaction_delete(db, txn_id, user_id):
    # Wegen ON DELETE SET NULL setzt PG den FK automatisch auf NULL.
    # Zusätzlich: Status zurück auf 'pending' setzen.
    pending = SELECT * FROM pending_dividends
              WHERE matched_transaction_id = txn_id
                AND user_id = user_id

    WENN pending:
        pending.status = 'pending'
        pending.updated_at = now()
        # matched_transaction_id wird durch ON DELETE SET NULL auf NULL gesetzt
        await db.commit()
```

**Hinweis:** Da `ON DELETE SET NULL` auf DB-Ebene ausgeführt wird, muss der Status-Reset explizit im Hook erfolgen, da der DB-Trigger keine Applikationslogik auslöst.

---

## 8. UI-Design

### 8.1 Top-Bar-Badge

Das Badge wird im bestehenden `AlertsBanner`-System **nicht** eingebunden (andere Semantik). Stattdessen erhält der Sidebar-Navigationseintrag "Portfolio" ein zweites Badge-Indikator neben dem bestehenden `AlertBadge`.

Alternativ — und bevorzugt wegen Einfachheit — wird ein neuer Badge auf dem Navigationseintrag "Transaktionen" angezeigt:

```
Transaktionen  [●3]
```

Das Badge zeigt die Zahl der `pending`-Einträge. Es ist ein oranges Pip (Tailwind: `bg-warning`) mit weisser Zahl, analog zum bestehenden `AlertBadge`-Muster in `Sidebar.jsx`.

**Neue Komponente:** `DividendBadge` — pollt `/api/dividends/count` beim Mount und nach jeder Confirm/Dismiss-Aktion. Kein globales Polling (Performance), stattdessen Refresh bei:
- Komponenten-Mount
- Nach `/confirm` oder `/dismiss` API-Call
- Optional: nach `window.focus`-Event (Tab-Wechsel)

---

### 8.2 Dashboard-Widget "Offene Dividenden"

**Datei:** `frontend/src/components/PendingDividendsWidget.jsx`

Das Widget erscheint **nur** wenn `pending_count > 0`. Es wird in `Dashboard.jsx` nach `UpcomingEarningsBanner` eingebunden, analog dessen Muster (fetch, null-render wenn leer).

**ASCII-Mockup:**

```
┌─────────────────────────────────────────────────────────────────────┐
│  💰  Offene Dividenden  ●3                                          │
│─────────────────────────────────────────────────────────────────────│
│  AAPL   Apple Inc.          Ex-Date 07.02.2026   ~ CHF 62.50       │
│  [Erfassen]  [Ignorieren]                                           │
│─────────────────────────────────────────────────────────────────────│
│  NESN   Nestlé SA           Ex-Date 15.04.2026   ~ CHF 340.00      │
│  [Erfassen]  [Ignorieren]                                           │
│─────────────────────────────────────────────────────────────────────│
│  VWRL   Vanguard FTSE All-W Ex-Date 30.03.2026   ~ CHF 18.40       │
│  [Erfassen]  [Ignorieren]                                           │
└─────────────────────────────────────────────────────────────────────┘
```

**Detaillierte Feldanzeige pro Zeile:**
- Ticker (Monospace, fett) + Positionsname (gedimmt)
- Ex-Date (formatiert via `formatDate`)
- `~ CHF {expected_gross_chf}` (Tilde als Hinweis auf Schätzwert)
- Button "Erfassen" (primäre Aktion, `bg-primary`)
- Button "Ignorieren" (sekundäre Aktion, `text-text-muted`, kein Fill)

**Keine Pagination** im Widget selbst. Wenn mehr als 5 Einträge: "... und X weitere" mit Link zur Transaktionsseite (Where-Design noch offen — siehe Offene Fragen).

**WCAG 2.2 AA:**
- Beide Buttons haben explizite `aria-label` mit Ticker: `aria-label="Dividende AAPL erfassen"` / `aria-label="Dividende AAPL ignorieren"`
- Fokus-Reihenfolge: Erfassen → Ignorieren → nächste Zeile
- Kontrast: primärer Button Weiss auf `bg-primary` (#3B82F6) = 4.5:1 erfüllt
- `role="list"` auf dem Container, `role="listitem"` pro Eintrag

---

### 8.3 Confirm-Modal

Das Modal wird **nicht** als neuer `TransactionCreateModal` implementiert, sondern ist ein dediziertes `ConfirmDividendModal.jsx`. Begründung: Die vorausgefüllten Felder und das reduzierte Formular (kein Ticker-Autocomplete, keine Shares) rechtfertigen eine eigene Komponente.

**Felder (alle editierbar ausser Position):**

```
┌──────────────────────────────────────────────────────────┐
│  Dividende erfassen                                    [X]│
│──────────────────────────────────────────────────────────│
│  Position        AAPL — Apple Inc.        [nicht editierb]│
│  Ex-Date         [07.02.2026          ]                   │
│  Datum           [07.02.2026          ]  (= Buchungsdatum)│
│  Währung         [USD               ▾]                    │
│  Bruttobetrag    [USD    ] [  62.50  ] CHF                │
│  Quellensteuer   [35 %   ] → CHF 21.88 automatisch        │
│  Nettobetrag     [CHF    ] [  40.62  ]  ← editierbar      │
│  Notizen         [                   ]  optional          │
│──────────────────────────────────────────────────────────│
│  [Abbrechen]                         [Transaktion anlegen]│
└──────────────────────────────────────────────────────────┘
```

**Berechungslogik im Modal (clientseitig):**
- Wenn User Bruttobetrag ändert → Nettobetrag = Brutto * (1 - withholding_pct/100) automatisch aktualisieren
- Wenn User Quellensteuer-% ändert → Nettobetrag automatisch aktualisieren
- Wenn User Nettobetrag direkt ändert → Brutto und % bleiben, keine Rückrechnung (einfachste Implementierung)
- Nettobetrag wird als `total_chf` an `/confirm` gesendet
- Bruttobetrag wird als `gross_amount` gesendet

**WCAG:**
- `aria-describedby` auf Nettobetrag-Feld verweist auf Hinweistext "Betrag nach Quellensteuer"
- Modal mit `useFocusTrap`, Escape-Close via `useEscClose` (bestehende Hooks)
- Erster Fokus: Datum-Feld (bereits vorausgefüllt, aber typischster Korrekturpunkt)

---

### 8.4 Dismiss-Bestätigungs-Dialog

Verwendet das bestehende `DeleteConfirm.jsx`-Muster (falls generisch genug) oder inline-Confirm direkt in der Widget-Zeile.

Text:
> "Offene Dividende für AAPL vom 07.02.2026 wird nicht mehr angezeigt. Die Dividende kann weiterhin manuell als Transaktion erfasst werden."

Zwei Buttons: "Abbrechen" + "Ausblenden" (nicht "Löschen" — semantisch korrekt, da Datensatz erhalten bleibt).

---

### 8.5 Nielsen-Heuristiken Checkliste

| Heuristik | Umsetzung |
|---|---|
| 1. Sichtbarkeit des Systemstatus | Badge-Counter zeigt sofort aktuelle Zahl; nach Confirm/Dismiss sofortige UI-Aktualisierung ohne Page-Reload |
| 2. Übereinstimmung mit der realen Welt | "Ex-Datum", "Quellensteuer", "Bruttobetrag / Nettobetrag" — Finanzfachbegriffe die CH-Investoren kennen |
| 3. Benutzerkontrolle | Dismiss mit Bestätigung; dismissed Einträge können durch manuelle Transaktion trotzdem erfasst werden |
| 4. Konsistenz und Standards | Button-Styles, Modal-Patterns, DateInput-Komponente identisch zu bestehenden Modals |
| 5. Fehlerprävention | Nettobetrag kann nicht grösser als Bruttobetrag sein (clientseitige Validierung) |
| 6. Wiedererkennung statt Erinnern | Ticker + Positionsname immer sichtbar, kein Lookup nötig |
| 7. Flexibilität | Alle Felder editierbar trotz Vorausfüllung |
| 8. Ästhetik | Widget nur sichtbar wenn Einträge vorhanden — kein leerer Kasten |
| 9. Fehlerbehandlung | API-Fehler zeigen deutschen Text; 409-Conflict → "Bereits erfasst oder ignoriert" |
| 10. Hilfe und Dokumentation | Tilde (~) vor CHF-Betrag signalisiert Schätzwert; Tooltip erklärbar via bestehenden `GlossarTooltip` |

---

## 9. Edge Cases

### (a) yfinance gibt leere Dividenden zurück

**Situation:** `yf.Ticker(ticker).dividends` ist leer oder `None` für eine Position.

**Verhalten:**
- `_detect_for_position` gibt frühzeitig `return` zurück, kein Eintrag wird erstellt
- `stats.skipped += 1`
- Kein Error-Log, nur Debug-Log: `logger.debug("No dividends from yfinance for %s", ticker)`
- Begründung: ETFs können keine Dividenden ausschütten, frisch gelistete Aktien haben keine Historie — leere Rückgabe ist normaler Zustand

### (b) User hat Position vor Ex-Date verkauft (`shares_at_ex_date = 0`)

**Situation:** `_reconstruct_shares_at_date` gibt 0.0 oder einen negativen Wert zurück.

**Verhalten:**
- Pending-Eintrag wird **nicht** erstellt (`CONTINUE` im Loop)
- Kein Eintrag in `pending_dividends`
- `stats.skipped += 1`
- Wichtig: Dies muss korrekt behandelt werden wenn User Position teilweise verkauft hat — `shares_at_ex_date` ist der korrekt rekonstruierte Bestand, nicht `position.shares` heute

### (c) Gematchte Transaktion wird gelöscht

**Situation:** User löscht die `dividend`-Transaktion, die einen `confirmed`-Eintrag gemacht hatte.

**Verhalten:**
1. DB-seitig: `ON DELETE SET NULL` auf `matched_transaction_id` — FK wird NULL
2. Applikations-seitig: Hook `unmatch_on_transaction_delete` setzt `status = 'pending'` zurück
3. Eintrag erscheint wieder im Widget mit Badge-Counter +1
4. User erhält keinen automatischen Toast — der Badge-Counter signalisiert die Änderung beim nächsten Seitenaufruf
5. `invalidate_portfolio_cache` wird vom `delete_transaction`-Endpunkt bereits aufgerufen

**Sonderfalls:** Wenn der Pending-Eintrag zum Zeitpunkt des Transaktions-Deletes `dismissed` ist (theoretisch nicht möglich über normalen Flow, da confirm und dismiss mutual exclusiv sind — aber bei direkter DB-Manipulation möglich). Dann bleibt er `dismissed`, kein Reset.

### (d) User dismisst eine real ausgezahlte Dividende

**Situation:** User klickt auf "Ignorieren" für eine echte Dividende — bewusst oder aus Versehen.

**Verhalten:**
- Status wird `dismissed`, Eintrag aus Widget entfernt
- Der Worker erstellt beim nächsten Lauf **keinen** neuen Eintrag (UNIQUE-Constraint + Prüfung auf bestehende Einträge unabhängig vom Status)
- User kann die Dividende trotzdem manuell als Transaktion via "Neue Transaktion" erfassen — der Auto-Match würde dann einen **neuen** Pending-Eintrag finden und matchen. Weil ein `dismissed`-Eintrag existiert, aber der manuelle `try_auto_match_transaction`-Hook sucht nach `status = 'pending'`-Einträgen, gibt es keinen Konflikt
- Kein Recovery-Flow im MVP (bewusste Entscheidung: Komplexität vs. Nutzen). User muss manuell handeln
- Dismiss-Dialog kommuniziert dies neutral: "Die Dividende kann weiterhin manuell als Transaktion erfasst werden"

---

## 10. Bestehender Code: Refactor `dividend_service.py`

Der bestehende `backend/services/dividend_service.py` verletzt Heilige Regel #7 (direkte `yf.Ticker()`-Nutzung in synchronem Kontext). Da der neue `pending_dividend_service.py` die Dividenden-Logik eigenständig implementiert, wird `dividend_service.py` wie folgt refactored:

**Vorher (verletzt Regel #7):**
```python
t = yf.Ticker(ticker)
divs = t.dividends
```

**Nachher (konform mit Regel #7):**
```python
divs = await asyncio.to_thread(lambda: yf.Ticker(ticker).dividends)
```

Die gesamte `fetch_dividends`-Funktion muss von sync zu `async def` umgebaut werden, da sie `asyncio.to_thread` verwendet. Alle bestehenden Aufrufer von `fetch_dividends` müssen mit `await` ergänzt werden.

**Achtung:** Der Fixer-Agent muss alle Stellen suchen, die `from services.dividend_service import fetch_dividends` importieren, und prüfen, ob diese in async-Contexten aufgerufen werden. Falls nicht, muss der Call-Site ebenfalls angepasst werden.

---

## 11. Alembic-Migration

**Datei:** `backend/alembic/versions/057_add_pending_dividends.py`

Die Migration enthält:
1. `CREATE TABLE pending_dividends` mit allen Feldern, Constraints und Indizes
2. `ALTER TABLE users ADD COLUMN dividend_withholding_default NUMERIC(5,4) NOT NULL DEFAULT 0.3500`
3. Optional: `notes TEXT` auf `pending_dividends` (für Dismiss-Reason)

**Rollback (downgrade):**
1. `DROP TABLE pending_dividends`
2. `ALTER TABLE users DROP COLUMN dividend_withholding_default`

---

## 12. Tests

**Datei:** `backend/tests/test_pending_dividend_service.py`

Mindest-Testfälle:
- `test_reconstruct_shares_at_date_buy_only`: 100 Aktien gekauft → shares_at_date = 100
- `test_reconstruct_shares_at_date_partial_sell`: 100 gekauft, 40 verkauft → shares_at_date = 60
- `test_reconstruct_shares_at_date_zero_at_exdate`: Position nach Ex-Date gekauft → 0
- `test_reconstruct_shares_at_date_fully_sold`: Position vor Ex-Date vollständig verkauft → 0
- `test_auto_match_on_transaction_create`: dividend-Transaktion innerhalb ±60d → pending auf confirmed
- `test_unmatch_on_transaction_delete`: Transaction gelöscht → pending zurück auf pending
- `test_no_duplicate_on_dismissed`: dismissed Eintrag → Worker erstellt keinen neuen

---

## 13. Offene Fragen für den Maintainer

1. **`dividend_service.py` Aufrufer:** Wird `fetch_dividends` aktuell ausserhalb des Workers oder intern aufgerufen (z.B. in der Stock-Detail-API)? Falls ja, welche Signatur soll die refactored Funktion haben (sync/async), damit keine Breaking Changes entstehen?

2. **User-Model oder separates Settings-Model?** Das `users`-Model in `backend/models/user.py` ist nicht vollständig in der Spec gelesen. Falls `dividend_withholding_default` auf ein separates `UserSettings`-Model gehört (wie bei anderen Settings), bitte confirmen — sonst landet es direkt in `users`.

3. **Widget-Platzierung:** Soll das "Offene Dividenden"-Widget nur auf dem Dashboard erscheinen, oder auch auf der Portfolio-Seite? Und falls beides: gleiche Komponente, oder auf Portfolio nur ein kompakter Badge-Link ohne die volle Liste?

4. **Badge-Placement im Sidebar:** Soll der Counter am Eintrag "Transaktionen" erscheinen, oder am Eintrag "Portfolio"? Oder soll ein ganz neuer Sidebar-Eintrag "Dividenden" geschaffen werden? Empfehlung wäre "Transaktionen", da Dividenden semantisch Transaktionen sind.

5. **Confirm-Modal Buchungsdatum vs. Ex-Date:** In der Spec ist "Datum" = Buchungsdatum vorausgefüllt mit Ex-Date. In der Praxis ist das Pay-Date 1-4 Wochen nach Ex-Date das korrekte Buchungsdatum. Da Pay-Date nicht getrackt wird — ist Ex-Date als Default OK, oder soll der User explizit auf die Diskrepanz hingewiesen werden (Tooltip / Hinweistext)?

6. **shares_at_ex_date bei Fractional Shares:** Die `_reconstruct_shares_at_date`-Logik arbeitet mit `NUMERIC(20,8)`. Gibt es in der Praxis Positionen mit Bruchteilen (Fractional Shares via Swissquote oder Saxo)? Falls ja, muss `expected_gross_chf` entsprechend gerundet werden — mit wie vielen Dezimalstellen?

7. **Rate-Limiting für yfinance:** Der Worker iteriert über alle User und alle deren Positionen. Bei einer grossen Instanz (z.B. 50 User × 20 Positionen = 1000 API-Calls) könnte yfinance Rate-Limiting auslösen. Soll ein globales Semaphore (z.B. max 10 concurrent) eingebaut werden, oder reicht der per-User-Semaphore von 3?

---

## 14. RICE-Score (Priorisierung)

```
Reach:      Alle User mit stock/ETF-Positionen = ~100% aktiver Users  → 10
Impact:     Direkte Auswirkung auf XIRR-Korrektheit (User beschweren sich)  → 8
Confidence: Klarer Scope, bestehende Infra, eine Unbekannte (yfinance-Rate-Limits)  → 0.8
Effort:     ~8 Story Points (2-3 Tage für Fixer-Agent):
            - DB-Migration: 0.5h
            - Model + Service: 3h
            - API-Endpunkte: 2h
            - Worker-Integration: 1h
            - Auto-Match-Hooks: 1.5h
            - Frontend-Widget + Modal: 4h
            - Tests: 2h
            Total: ~14h = Effort 14

RICE = (10 × 8 × 0.8) / 14 = 4.57
```

Zum Vergleich: Feature mit viel Impact aber unklarem Scope hätte Confidence 0.4 und damit Score ~2.3. Dieser Feature liegt deutlich darüber — klare Priorität.

---

## 15. Reversibilität

**Einbahn-Tür:** Das neue Datenmodell (`pending_dividends`) ist additiv und nicht-destruktiv. Rollback via Alembic-Downgrade entfernt die Tabelle, ohne bestehende Daten zu beschädigen. Die Hooks in `transactions.py` und `import_service.py` sind try/except-gewrappt — sie degradieren silent wenn der Service nicht verfügbar ist.

Die Entscheidung für Ex-Date (statt Pay-Date) ist eine **Einbahn-Tür**: wenn Pay-Date-Tracking später gewünscht wird, muss das Schema erweitert werden. Innerhalb des aktuellen Scopes ist sie aber klar und ausreichend begründet.
