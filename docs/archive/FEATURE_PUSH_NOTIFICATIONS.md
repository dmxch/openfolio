# Feature Spec: Push-Benachrichtigungen via ntfy

**Status:** Draft  
**Datum:** 2026-05-08  
**Autor:** Design-Agent  
**Fixer-Referenz:** openfolio-fixer

---

## 1. Problemstellung

OpenFolio erzeugt bereits reiche Alert-Daten (portfolio-rule alerts, price alerts, breakout alerts, ETF-200-DMA, pending dividends). Diese sind heute nur via In-App-Ansicht und optionalem E-Mail-Digest erreichbar. Ein Investor, der nicht aktiv im Browser ist, verpasst zeitkritische Ereignisse (Stop-Loss erreicht, Breakout, Preis-Alarm). E-Mail ist zu langsam und zu unflexibel für mobile Situationen.

**Personas:**
- **Self-Hosted-Investor (Maintainer):** Einzelperson, eigene Docker-Instanz, Android-Phone, möchte Echtzeit-Push ohne Account bei Drittanbietern.
- **Power-User (Multi-User-Instanz):** Konfiguriert eigenen ntfy-Topic pro User. Versteht Self-Hosting.
- **Einsteiger:** Nutzt public ntfy.sh mit privatem Topic-Namen als shared secret. Kein eigenes Server-Setup nötig — auf Android kostenlos; iOS-User benötigen die ntfy-App aus dem App Store, die für Pushes von self-hosted Servern ntfy Pro voraussetzt (public ntfy.sh funktioniert kostenlos auch auf iOS).

**Dringlichkeit:** Stop-Loss-Alerts und Preis-Alarme sind zeitkritisch (innerhalb Minuten relevant). E-Mail-Digest löst das nicht.

---

## 2. Bestehende Notification-Architektur (Code-Analyse)

### 2.1 Dispatch-Muster heute

Es gibt **keine zentrale Dispatcher-Abstraktion**. Stattdessen rufen mehrere Services direkt `email_service.send_email()` auf:

| Service | Quelle | Dispatch-Methode |
|---|---|---|
| `rule_alert_service.py` | `generate_alerts()` (täglicher Digest) | `send_email()` direkt |
| `price_alert_service.py` | Preis-Alarme (alle 60s via Worker) | `send_email()` direkt |
| `breakout_alert_service.py` | Donchian Breakout (Watchlist) | `send_email()` direkt |
| `etf_200dma_alert_service.py` | ETF unter 200-DMA | `send_email()` direkt |
| `pending_dividend_service.py` | Dividend-Digest (So 09:00) | `send_email()` direkt |

### 2.2 AlertPreference-Modell (bestehendes Schema)

```python
# models/alert_preference.py — heutige Spalten
class AlertPreference(Base):
    user_id: UUID
    category: str          # z.B. "price_alert", "breakout", "etf_200dma_buy"
    is_enabled: bool
    notify_in_app: bool
    notify_email: bool
    # notify_push fehlt noch
```

### 2.3 Bestehende Notification-Kategorien (AlertsTab.jsx)

18 Kategorien sind bereits definiert und per `AlertPreference` pro User konfigurierbar:
`stop_missing`, `stop_unconfirmed`, `stop_proximity`, `stop_review`, `ma_critical`, `ma_warning`, `position_limit`, `sector_limit`, `loss`, `market_climate`, `vix`, `earnings`, `allocation`, `position_type_missing`, `etf_200dma_buy`, `price_alert`, `breakout`, `pending_dividend`

### 2.4 Architektur-Entscheid: Dispatcher-Abstraktion

**Empfehlung:** Neues Modul `services/ntfy_service.py` als dünne Abstraktion, parallel zu `email_service.py`. Die bestehenden 5 Service-Dateien werden jeweils um einen ntfy-Call ergänzt — **kein** Refactoring der Email-Logik, da das Risiko zu gross ist (Heilige Regel #1 tangiert `rule_alert_service` indirekt via Portfolioberechnung).

Begründung: Die Services sind klein (60-130 Zeilen), der ntfy-Call ist ein einzeiliger `asyncio.create_task(ntfy_service.send_push_aggregated(...))`. Ein vollständiges Dispatcher-Pattern wäre eine Einbahn-Tür-Entscheidung — besser jetzt die Zwei-Wege-Tür wählen und den Dispatcher später einführen wenn ein dritter Kanal (z.B. Gotify) kommt.

---

## 3. User Stories

### Story 1: ntfy konfigurieren

**Als** aktiver Investor (Multi-User-fähig)  
**möchte ich** meinen eigenen ntfy-Server und Topic in den Einstellungen hinterlegen  
**damit** ich Push-Benachrichtigungen auf meinem Smartphone erhalte, ohne einen Account bei Dritten zu benötigen.

#### Acceptance Criteria

**AC-1: Konfiguration speichern**
- Given: Ich bin auf Einstellungen > Integrationen
- When: Ich trage Server-URL (`https://ntfy.sh`), Topic-Name und optionalen Access-Token ein und klicke "Speichern"
- Then: Die Konfiguration wird user-scoped gespeichert; der Topic wird im UI klar angezeigt (kein Maskieren — siehe Issue 4-Entscheid in Section 5.1)

**AC-2: Validierung Server-URL**
- Given: Ich gebe eine ungültige URL ein (kein `http://` oder `https://`)
- When: Ich klicke "Speichern"
- Then: Fehlermeldung "Ungültige Server-URL — muss mit http:// oder https:// beginnen" erscheint, kein Save

**AC-3: Konfiguration löschen**
- Given: ntfy ist konfiguriert
- When: Ich klicke "Entfernen"
- Then: Alle ntfy-Felder dieses Users werden gelöscht, keine weiteren Push-Notifications

**AC-4: Access-Token optional**
- Given: Ich nutze public ntfy.sh mit privatem Topic (kein Auth nötig)
- When: Ich lasse das Token-Feld leer
- Then: Speichern funktioniert, HTTP-Calls gehen ohne `Authorization`-Header raus

---

### Story 2: Test-Push senden

**Als** Investor  
**möchte ich** einen Test-Push auslösen  
**damit** ich verifizieren kann, dass mein ntfy-Setup funktioniert, bevor ich mich auf echte Alerts verlasse.

#### Acceptance Criteria

**AC-1: Test-Button**
- Given: ntfy ist konfiguriert
- When: Ich klicke "Test-Push senden"
- Then: Innerhalb von 5s erscheint eine Notification auf meinem Gerät mit Titel "OpenFolio Test" und Body "Test-Push von OpenFolio — wenn du das siehst, funktioniert's."; der gesendete Push verwendet Severity `high` (ntfy-Tag: `chart_with_upwards_trend`, Priority 4)

**AC-2: Fehler-Feedback**
- Given: ntfy-Server ist nicht erreichbar (falscher Host, Token fehlt)
- When: Ich klicke "Test-Push senden"
- Then: UI zeigt rote Fehlermeldung mit HTTP-Statuscode (z.B. "403 Forbidden — Access-Token prüfen")

**AC-3: Loading-State**
- Given: Test-Anfrage läuft
- When: HTTP-Call dauert > 300ms
- Then: Button zeigt Spinner, ist disabled bis Antwort eintrifft

---

### Story 3: Push-Kategorien pro User konfigurieren

**Als** Investor  
**möchte ich** pro Alert-Kategorie entscheiden, ob ich einen Push erhalte  
**damit** ich nicht für jede "Branche nicht zugewiesen"-Warnung mein Handy vibrieren lasse.

#### Acceptance Criteria

**AC-1: Push-Spalte in AlertsTab**
- Given: ntfy ist für meinen Account konfiguriert
- When: Ich öffne Einstellungen > Alerts
- Then: Neben "In-App" und "E-Mail" erscheint eine Spalte "Push" mit Checkboxen

**AC-2: Push-Spalte ausgeblendet wenn kein ntfy**
- Given: Kein ntfy konfiguriert
- When: Ich öffne Einstellungen > Alerts
- Then: Die "Push"-Spalte ist nicht sichtbar; stattdessen erscheint ein Hinweis "Push-Benachrichtigungen konfigurieren →" als Link zu Integrationen

**AC-3: Default-Wert**
- Given: ntfy wird neu konfiguriert
- When: Die Push-Spalte erstmals erscheint
- Then: Alle Kategorien haben `notify_push = false` (opt-in, nicht opt-out) — kein Notification-Flood beim ersten Setup

**AC-4: Disabled-State**
- Given: Eine Kategorie hat `is_enabled = false`
- When: Ich schaue auf die Push-Checkbox dieser Kategorie
- Then: Checkbox ist disabled (identisches Verhalten wie notify_email heute)

---

### Story 4: Push-Notification bei zeitkritischen Events empfangen

**Als** Investor  
**möchte ich** sofort einen Push erhalten wenn ein Preis-Alarm, ein Stop-Loss-Erreichen oder ein Breakout ausgelöst wird  
**damit** ich ohne aktive App-Nutzung zeitnah reagieren kann.

#### Acceptance Criteria

**AC-1: Preis-Alarm Push**
- Given: `notify_push = true` für `price_alert`, ntfy konfiguriert
- When: Ein Preis-Alarm triggert (Worker-Zyklus ~60s)
- Then: Notification erscheint auf Gerät mit Titel "AAPL: Kurs über 210.00" und Body "Aktuell: 211.35 CHF"; Severity `high` (ntfy-Tag: `chart_with_upwards_trend`, Priority 4)

**AC-2: Fire-and-forget, keine Blockierung des Worker-Cycles**
- Given: ntfy-Server ist kurzzeitig nicht erreichbar
- When: Ein Alert triggert
- Then: Der Worker-Job schlägt NICHT fehl, Fehler wird nur geloggt (`logger.warning`), kein Retry-Loop; der 60s-Worker-Cycle wird nicht messbar verzögert (Test: ntfy auf `127.0.0.1:1` setzen — Cycle darf <2s zusätzlich brauchen).
- **Was dieser Test misst:** Spawn-Overhead von `asyncio.create_task()` und Bucket-Aufbau im Caller — explizit **nicht** die End-to-End-Push-Latenz. ntfy-Push-Latenz ist per Design ausserhalb des SLA (fire-and-forget): Der Test verifiziert, dass der Worker-Cycle vom ntfy-Zustand entkoppelt ist, nicht dass der Push schnell beim Gerät ankommt.

**AC-3: De-Duplizierung**
- Given: Redis-Cache enthält `ntfy_dedup:{user_id}:{category}:{ticker}` (TTL 24h) für einen bereits gesendeten Push
- When: Derselbe Alert im nächsten Worker-Zyklus erneut auftritt
- Then: Kein zweiter Push wird gesendet

**AC-4: Aggregierung bei Massen-Alerts (Must)**
- Given: Gleichzeitig triggern 3 oder mehr Preis-Alarme für einen User im selben Worker-Run
- When: Der Worker sendet Notifications
- Then: Ein aggregierter Push ("3 Alarme ausgelöst: AAPL, MSFT, ...") statt N Einzelnachrichten wird gesendet; bei 1-2 gleichzeitigen Alerts werden Einzel-Pushes gesendet

**AC-5: Aggregat-Dedup**
- Given: Redis-Cache enthält `ntfy_dedup_agg:{user_id}:{category}:{date}` für heutigen Tag
- When: Erneut ≥3 Alerts derselben Kategorie im nächsten Worker-Cycle triggern
- Then: Kein zweiter aggregierter Push für diese Kategorie heute

**AC-6: Push-Notifications pausieren**
- Given: ntfy ist konfiguriert und `is_enabled = true`
- When: Ich aktiviere den "Pausieren"-Toggle in Einstellungen > Integrationen
- Then: `is_enabled` wird auf `false` gesetzt; alle Worker-Pushes werden unterbunden; der Test-Push (Story 2) bleibt manuell auslösbar und ignoriert `is_enabled`; ein gelber Badge "Pausiert" erscheint im ntfy-Block

---

## 4. Scope (MoSCoW)

### Must (MVP)
- `NtfyConfig`-Modell: `user_id`, `server_url`, `topic`, `access_token_encrypted` (nullable), `is_enabled`
- `notify_push: bool` Spalte in `alert_preference` (Default `false`)
- `services/ntfy_service.py`: zwei öffentliche Funktionen (siehe Section 6.1):
  - `send_push_for_user(user_id, category, title, message)` — Einzel-Push mit Per-Alert-Dedup
  - `send_push_aggregated(user_id, category, alerts: list[dict])` — aggregiert ab `AGGREGATION_THRESHOLD`, sonst N Einzel-Pushes
  - Beide fire-and-forget via `asyncio.create_task()` mit Strong-Reference (siehe Section 6.1); Caller `await`et nicht
- Integration in `price_alert_service.py` und `breakout_alert_service.py` (die zeitkritischen Quellen)
- Aggregierung bei ≥ 3 gleichzeitigen Alerts derselben Kategorie (anti-flood, ab MVP — ohne dies droht Notification-Flood bei Watchlists mit 20+ Tickern, was Adoption direkt gefährdet)
- Settings API: `PUT /api/settings/ntfy`, `DELETE /api/settings/ntfy`, `POST /api/settings/ntfy/test`, `PATCH /api/settings/ntfy` (für `is_enabled`-Toggle)
- `AlertPrefUpdate` Pydantic-Schema: `notify_push` Feld ergänzen
- Frontend: ntfy-Konfigurationsblock in `IntegrationsTab.jsx` (analog SMTP-Block) **inkl. Pausieren/Aktivieren-Toggle**
- Frontend: Push-Spalte in `AlertsTab.jsx` (bedingt sichtbar wenn ntfy konfiguriert)
- Alembic-Migration: Tabelle `ntfy_config` + Spalte `alert_preferences.notify_push`

### Should (v1)
- Integration in `etf_200dma_alert_service.py` (zeitkritisch, Einzel-Push)
- Integration in `rule_alert_service.py` als Digest-Push (ein Push pro Tag, keine Einzel-Pushes)
- Integration in `pending_dividend_service.py` (Digest-Push analog Email)
- ntfy-Priority-Mapping nach Alert-Severity (`critical` → priority 5, `high` → 4, `medium` → 3, `info` → 2)
- ntfy-Tags nach Severity-Mapping (siehe Section 6.1)

### Could (Later)
- Gotify-Adapter als alternative Implementierung hinter einem `PushAdapter`-Interface (abstraktes Protocol, ntfy und Gotify als Implementierungen) — vorbereiten wenn ein zweiter Push-Kanal gewünscht wird
- Notification-History-Tabelle (gespeicherte gesendete Pushes, TTL 30 Tage) — zerstörungsfrei nachziehbar, da ntfy-Server bereits selbst Cache hält (cache.db bei self-hosted) und Android-App Verlauf anzeigt
- Deep-Link in Push-Notification (z.B. `openfolio://position/AAPL`)

### Won't (explizit ausgeschlossen)
- WebPush (Browser-native): erfordert Service Worker, VAPID-Keys, deutlich mehr Komplexität
- Firebase Cloud Messaging (FCM): Account-Pflicht, Vendor-Lock-in
- Gotify als MVP-Scope: komplexere Auth, zwingend self-hosted, kein Mehrwert vs. ntfy für den primären Use-Case
- Aggregations-Schwellenwert als User-Setting: fest verdrahtete Konstante `AGGREGATION_THRESHOLD = 3` reicht, weniger Komplexität

---

## 5. DB-Schema

### 5.1 Neue Tabelle: `ntfy_config`

```sql
CREATE TABLE ntfy_config (
    user_id         UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    server_url      VARCHAR(500) NOT NULL,          -- z.B. "https://ntfy.sh" oder "https://push.example.com"
    topic           VARCHAR(255) NOT NULL,           -- z.B. "openfolio-harry-7K3xQ9meinlangertopic"
    access_token_encrypted VARCHAR(500),             -- NULL = kein Auth (public ntfy.sh mit privatem Topic)
    is_enabled      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

**Anmerkungen zum Topic-Handling (Design-Entscheid):**

Topic ist **kein Secret im klassischen Sinne** — er ist der URL-Pfad des ntfy-Servers. Jeder Push-Empfänger der App sieht den Topic-Namen, und ntfy empfiehlt selbst, Unguessability statt Geheimhaltung als Schutz zu nutzen. Konsequenzen für das System:

- `topic` wird in GET-API-Responses **klar zurückgegeben** (nicht maskiert)
- Frontend prefilled das Topic-Feld beim Editieren mit dem gespeicherten Wert
- Speichern überschreibt nur wenn der Wert geändert wurde
- `access_token_encrypted` bleibt write-only: wird im GET-Response nie zurückgegeben; PUT/POST-Body nimmt den Klartext-Token entgegen
- Empfehlung im UI: Topic sollte ≥16 Zeichen mit Buchstaben und Ziffern enthalten ("wähle einen langen, zufälligen Namen — z.B. openfolio-harry-7K3xQ9meinlangertopic")
- Hilfetext: "Topic ist nicht geheim wie ein Passwort, aber wer den Namen kennt, sieht alle Pushes. Wähle einen langen, zufälligen Namen."

`access_token_encrypted` wird mit demselben `encrypt_value`/`decrypt_value`-Mechanismus gespeichert wie `smtp_config.password_encrypted`.

Kein separates `categories`-JSON in dieser Tabelle — die Kategorie-Granularität läuft über das bestehende `alert_preferences`-System.

### 5.2 Migration bestehende Tabelle: `alert_preferences`

```sql
ALTER TABLE alert_preferences
    ADD COLUMN notify_push BOOLEAN NOT NULL DEFAULT FALSE;
```

**Rationale:** `notify_push = false` als Default verhindert ungeplante Notification-Flut bei bestehenden Usern, die ntfy neu konfigurieren. Explizites Opt-in pro Kategorie.

---

## 6. Backend-Architektur

### 6.1 `services/ntfy_service.py`

**Severity-zu-Tag-Mapping (Konstante `_SEVERITY_TAGS` im Modul):**

| Severity | ntfy-Tag | Emoji | Kategorien (zur Orientierung — Fixer verifiziert echte Kategorie-Namen gegen Source) |
|---|---|---|---|
| `critical` | `rotating_light` | 🚨 | `stop_missing`, `ma_critical`, `loss`, `market_climate` |
| `high` | `chart_with_upwards_trend` | 📈 | `price_alert`, `breakout`, `ma_warning`, `vix` |
| `medium` | `bar_chart` | 📊 | `earnings`, `etf_200dma_buy`, `position_limit`, `sector_limit`, `allocation` |
| `info` | `moneybag` | 💰 | `pending_dividend`, `stop_review`, `stop_proximity`, `position_type_missing`, `stop_unconfirmed` |

**Hinweis an Fixer:** Die Kategorie-Namen in der Spalte "Kategorien" sind zur Orientierung aus `AlertsTab.jsx` entnommen. Beim Implementieren gegen die echten Kategorie-Strings in den 5 Email-Services verifizieren — massgeblich ist was die Services tatsächlich senden, nicht diese Tabelle.

**Deutsche Kategorie-Labels für Aggregat-Titel (Konstante `_CATEGORY_LABELS_DE` im Modul):**

| Kategorie-Key | Deutsches Label (Plural) |
|---|---|
| `price_alert` | Preis-Alarme |
| `breakout` | Breakouts |
| `earnings` | Earnings-Termine |
| `etf_200dma_buy` | ETF-200DMA-Signale |
| `pending_dividend` | ausstehende Dividenden |
| `rule_alert` | Portfolio-Regeln |
| `stop_review` | Stop-Reviews |
| `stop_missing` | fehlende Stops |
| `ma_critical` | MA-Krisen-Signale |
| `ma_warning` | MA-Warnungen |
| `vix` | VIX-Signale |
| `market_climate` | Markt-Klima-Wechsel |
| `loss` | Verlust-Alarme |
| `position_limit` | Positions-Limits |
| `sector_limit` | Sektor-Limits |
| `allocation` | Allokations-Hinweise |
| `stop_proximity` | Stop-Nähe-Warnungen |
| `stop_unconfirmed` | unbestätigte Stops |
| `position_type_missing` | fehlende Positions-Typen |

**Hinweis an Fixer:** Diese Kategorie-Keys müssen beim Implementieren gegen die echten Kategorie-Strings in den Email-Services (z.B. `price_alert_service.py`, `breakout_alert_service.py`) verifiziert werden — nie aus dem Spec übernehmen ohne Abgleich gegen die Live-Quellen. Massgeblich sind die tatsächlich gesendeten Strings, nicht diese Tabelle.

**Aggregations-Schwelle:** `AGGREGATION_THRESHOLD = 3` — fest verdrahtete Konstante im Modul, kein User-Setting. Bei 1-2 gleichzeitigen Alerts derselben Kategorie: Einzel-Pushes. Ab 3: ein zusammenfassender Push.

**Fire-and-forget-Pattern mit Strong-Reference (bewusste Entscheidung):**

Der 60s-Worker-Cycle ist eng. Ein ntfy-Server-Ausfall darf den Cycle nicht aufhalten. Deshalb wird jeder Push als detached `asyncio.Task` gestartet — der Caller `await`et den Push nicht. Die innere Funktion fängt alle Exceptions selbst ab (`logger.warning`) damit kein "Task exception was never retrieved"-Warning entsteht.

**Achtung GC-Footgun:** `asyncio.create_task()` ohne Strong-Reference kann vom Python-GC eingesammelt werden bevor der Task fertig läuft — das ergibt "Task was destroyed but it is pending"-Warnungen und verlorene Pushes unter Last (tritt im Test nicht auf, erst unter Concurrent-Load). Deshalb wird ein Modul-Level `_pending: set[asyncio.Task]` als Strong-Reference geführt. Siehe https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task — "Important: Save a reference to the result of this function".

**ntfy-Publish-Mode: JSON mit Topic im Body (nicht im URL-Pfad):**

ntfy unterstützt JSON-Publish-Mode: `POST https://server/` mit Body `{"topic": "...", "message": "...", "title": "...", "tags": [...], "priority": 4}`. Vorteil: Topic landet nicht im URL-Pfad und damit nicht in httpx-Default-Logs (httpx loggt Request-URLs auf DEBUG-Level). Die URL lautet immer `{server_url}/` ohne Topic-Suffix.

```python
"""ntfy push notification service.

Fire-and-forget: callers use send_push_for_user() / send_push_aggregated() which
internally spawn asyncio.create_task(_send_push_inner(...)). Each spawned task is
held in the module-level _pending set until completion — this prevents the Python
GC from collecting the task before it finishes (asyncio GC footgun).
The inner function handles all exceptions internally (logger.warning on failure).
This ensures ntfy outages never delay the 60s worker cycle.
Uses httpx (HEILIGE Regel #8), JSON publish mode (topic in body, not URL).
Redis calls use services/cache.py which is synchronous (no await needed) — see
Section 6.6.
"""
import asyncio
import logging
from typing import Literal

import httpx

from services.auth_service import decrypt_value

logger = logging.getLogger(__name__)

NtfyPriority = Literal[1, 2, 3, 4, 5]  # 1=min, 3=default, 5=urgent

# Aggregation threshold: send a single digest push instead of N individual pushes
# when N alerts of the same category trigger in the same worker run.
AGGREGATION_THRESHOLD = 3

SEVERITY_TO_PRIORITY: dict[str, NtfyPriority] = {
    "critical": 5,
    "high": 4,
    "medium": 3,
    "info": 2,
}

_SEVERITY_TAGS: dict[str, tuple[str, str]] = {
    # severity -> (ntfy_tag, emoji)
    "critical": ("rotating_light", "🚨"),
    "high": ("chart_with_upwards_trend", "📈"),
    "medium": ("bar_chart", "📊"),
    "info": ("moneybag", "💰"),
}

# German plural labels for aggregated push titles.
# FIXER: verify these keys against the actual category strings sent by the
# email services (price_alert_service.py etc.) before using — do not copy blindly.
_CATEGORY_LABELS_DE: dict[str, str] = {
    "price_alert": "Preis-Alarme",
    "breakout": "Breakouts",
    "earnings": "Earnings-Termine",
    "etf_200dma_buy": "ETF-200DMA-Signale",
    "pending_dividend": "ausstehende Dividenden",
    "rule_alert": "Portfolio-Regeln",
    "stop_review": "Stop-Reviews",
    "stop_missing": "fehlende Stops",
    "ma_critical": "MA-Krisen-Signale",
    "ma_warning": "MA-Warnungen",
    "vix": "VIX-Signale",
    "market_climate": "Markt-Klima-Wechsel",
    "loss": "Verlust-Alarme",
    "position_limit": "Positions-Limits",
    "sector_limit": "Sektor-Limits",
    "allocation": "Allokations-Hinweise",
    "stop_proximity": "Stop-Nähe-Warnungen",
    "stop_unconfirmed": "unbestätigte Stops",
    "position_type_missing": "fehlende Positions-Typen",
}

# Strong-reference set: prevents the Python GC from collecting pending asyncio
# Tasks before they finish. Each task removes itself via add_done_callback.
_pending: set[asyncio.Task] = set()


async def _send_push_inner(
    server_url: str,
    topic: str,
    title: str,
    message: str,
    access_token_encrypted: str | None = None,
    priority: NtfyPriority = 3,
    tags: list[str] | None = None,
) -> None:
    """Inner coroutine — never raises. Used as detached asyncio.Task."""
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if access_token_encrypted:
        token = decrypt_value(access_token_encrypted)
        headers["Authorization"] = f"Bearer {token}"

    payload: dict = {
        "topic": topic,
        "title": title,
        "message": message,
        "priority": priority,
    }
    if tags:
        payload["tags"] = tags

    url = server_url.rstrip("/") + "/"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        logger.info(f"ntfy push sent (server={server_url}, priority={priority})")
    except httpx.HTTPStatusError as e:
        logger.warning(f"ntfy push failed: HTTP {e.response.status_code} for {server_url}")
    except Exception as e:
        logger.warning(f"ntfy push failed: {e}")


def _spawn_task(**kwargs) -> None:
    """Create a fire-and-forget task with a strong reference to prevent GC collection."""
    task = asyncio.create_task(_send_push_inner(**kwargs))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


def send_push_for_user(
    ntfy_cfg,        # NtfyConfig model instance
    category: str,
    title: str,
    message: str,
    severity: str = "medium",
    redis_client=None,  # cache module passed by caller for dedup
) -> None:
    """Schedule a single push as detached fire-and-forget task.

    Applies per-alert dedup: ntfy_dedup:{user_id}:{category}:{ticker_or_title}
    with TTL 24h via Redis. Pass redis_client=None to skip dedup (e.g. test push).
    Caller must NOT await this function.

    redis_client is services/cache — its get()/set() are synchronous (no await).
    """
    if not ntfy_cfg or not ntfy_cfg.is_enabled:
        return
    # Dedup check — key contains category + title as proxy for ticker identity
    if redis_client is not None:
        dedup_key = f"ntfy_dedup:{ntfy_cfg.user_id}:{category}:{title}"
        if redis_client.get(dedup_key):
            return
        redis_client.set(dedup_key, "1", ex=86400)  # 24h TTL — sync, no await

    priority = SEVERITY_TO_PRIORITY.get(severity, 3)
    tag_info = _SEVERITY_TAGS.get(severity)
    tags = [tag_info[0]] if tag_info else None
    _spawn_task(
        server_url=ntfy_cfg.server_url,
        topic=ntfy_cfg.topic,
        title=title,
        message=message,
        access_token_encrypted=ntfy_cfg.access_token_encrypted,
        priority=priority,
        tags=tags,
    )


def send_push_aggregated(
    ntfy_cfg,        # NtfyConfig model instance
    category: str,
    alerts: list[dict],   # list of {"title": str, "message": str, "severity": str}
    redis_client=None,
) -> None:
    """Send push(es) for a batch of alerts of the same category in one worker run.

    If len(alerts) >= AGGREGATION_THRESHOLD: one aggregated push with per-day dedup.
    If len(alerts) < AGGREGATION_THRESHOLD: N individual pushes with per-alert dedup.
    Caller must NOT await this function.

    redis_client is services/cache — its get()/set() are synchronous (no await).
    """
    if not ntfy_cfg or not ntfy_cfg.is_enabled or not alerts:
        return

    if len(alerts) >= AGGREGATION_THRESHOLD:
        # One aggregated push per category per calendar day
        if redis_client is not None:
            from datetime import date
            agg_key = f"ntfy_dedup_agg:{ntfy_cfg.user_id}:{category}:{date.today().isoformat()}"
            if redis_client.get(agg_key):  # sync, no await
                return
            redis_client.set(agg_key, "1", ex=86400)  # sync, no await

        severity = alerts[0].get("severity", "medium")
        priority = SEVERITY_TO_PRIORITY.get(severity, 3)
        tag_info = _SEVERITY_TAGS.get(severity)
        tags = [tag_info[0]] if tag_info else None
        first_titles = [a["title"] for a in alerts[:3]]
        extra = len(alerts) - 3
        body = ", ".join(first_titles)
        if extra > 0:
            body += f" +{extra} weitere"
        label = _CATEGORY_LABELS_DE.get(category, category)
        _spawn_task(
            server_url=ntfy_cfg.server_url,
            topic=ntfy_cfg.topic,
            title=f"{len(alerts)} {label} ausgelöst",
            message=body,
            access_token_encrypted=ntfy_cfg.access_token_encrypted,
            priority=priority,
            tags=tags,
        )
    else:
        for alert in alerts:
            send_push_for_user(
                ntfy_cfg=ntfy_cfg,
                category=category,
                title=alert["title"],
                message=alert["message"],
                severity=alert.get("severity", "medium"),
                redis_client=redis_client,
            )


async def send_push_test(ntfy_cfg) -> tuple[bool, str]:
    """Synchronous test push — awaited by the API endpoint, NOT fire-and-forget.

    Returns (success: bool, error_message: str).
    Uses severity 'high' so the user sees the actual sound/vibration behaviour.
    Deliberately ignores ntfy_cfg.is_enabled — test push works even when paused.
    """
    if not ntfy_cfg:
        return False, "Keine ntfy-Konfiguration gefunden"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if ntfy_cfg.access_token_encrypted:
        token = decrypt_value(ntfy_cfg.access_token_encrypted)
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "topic": ntfy_cfg.topic,
        "title": "OpenFolio Test",
        "message": "Test-Push von OpenFolio — wenn du das siehst, funktioniert's.",
        "priority": 4,  # high
        "tags": ["chart_with_upwards_trend"],
    }
    url = ntfy_cfg.server_url.rstrip("/") + "/"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        return True, ""
    except httpx.HTTPStatusError as e:
        return False, f"{e.response.status_code} {e.response.reason_phrase}"
    except Exception as e:
        return False, str(e)
```

### 6.2 Integration in bestehende Services

**Zeitkritische Quellen (MVP):** `price_alert_service.py`, `breakout_alert_service.py`

**Nicht-zeitkritische Quellen (Should):** `rule_alert_service.py`, `pending_dividend_service.py`

**Zeitkritisch aber Should:** `etf_200dma_alert_service.py`

**Caller-Pattern für zeitkritische Services (Beispiel `price_alert_service.py`):**

Der Alert-Service sammelt alle getriggerten Alerts dieses Runs **pro `user_id`** in einem `dict[int, list[dict]]`-Bucket. Nach dem Email-Call übergibt er die Alert-Liste dieses Users einmalig an `send_push_aggregated()`. Die Aggregations-Entscheidung trifft `ntfy_service` — der Alert-Service ist dumm.

**Wichtig: Niemals Alerts verschiedener User im selben Bucket mischen.** `user_id` ist zwingend der Bucket-Key. Alerts von User A dürfen nie als Push an User B gesendet werden.

```python
# In price_alert_service.py — nach dem Email-Dispatch-Block

from collections import defaultdict
from models.ntfy_config import NtfyConfig
from services import cache as redis_cache
from services.ntfy_service import send_push_aggregated

# Alerts dieses Runs pro user_id sammeln — NIEMALS User mischen.
# Achtung: alert.pref muss is_enabled UND notify_push prüfen — eine deaktivierte
# Kategorie (is_enabled=false) darf weder Email noch Push auslösen, identisch
# zum Email-Pfad. Reihenfolge: pref existiert → is_enabled → notify_push.
buckets: dict[int, list[dict]] = defaultdict(list)
for user_id, alerts_for_user in triggered_alerts_by_user.items():
    for alert in alerts_for_user:
        if alert.pref and alert.pref.is_enabled and alert.pref.notify_push:
            buckets[user_id].append({
                "title": f"Preis-Alarm: {alert.ticker}",
                "message": f"Kurs {alert.current_price:.2f} {alert.currency} hat Ziel {alert.target_value:.2f} erreicht",
                "severity": "high",
            })

for user_id, alerts in buckets.items():
    ntfy_cfg = await db.get(NtfyConfig, user_id)
    if ntfy_cfg:
        # fire-and-forget — nicht awaiten
        send_push_aggregated(
            ntfy_cfg=ntfy_cfg,
            category="price_alert",
            alerts=alerts,
            redis_client=redis_cache,
        )
```

Der ntfy-Call kommt **nach** dem Email-Call — nie davor. Fehler im ntfy-Call (bereits intern abgefangen) dürfen den Email-Pfad nicht unterbrechen.

**Muster für Digest-Push** (`rule_alert_service.py`, Should):

```python
# Konsistent mit dem Email-Digest: ein Push pro Tag, kein Einzel-Push je Alert.
# is_enabled muss vor notify_push geprüft werden — analog zum zeitkritischen Caller oben.
if ntfy_cfg and pref and pref.is_enabled and pref.notify_push and len(triggered_alerts) > 0:
    send_push_aggregated(
        ntfy_cfg=ntfy_cfg,
        category="rule_alert",
        alerts=[{"title": a.title, "message": a.body, "severity": "medium"} for a in triggered_alerts],
        redis_client=redis_cache,
    )
```

### 6.3 API-Endpoints

Neue Routen in `api/settings.py`:

```
PUT    /api/settings/ntfy          → NtfyConfig speichern/aktualisieren
DELETE /api/settings/ntfy          → NtfyConfig löschen
GET    /api/settings/ntfy          → Konfigurationsstatus zurückgeben (topic klar, token nie)
POST   /api/settings/ntfy/test     → Test-Push senden, synchron (5s Timeout), awaited
PATCH  /api/settings/ntfy          → is_enabled togglen ({"is_enabled": false/true})
```

Pydantic-Schemas:

```python
class NtfyConfigCreate(BaseModel):
    server_url: str = Field(min_length=7, max_length=500)  # muss http(s):// enthalten
    topic: str = Field(min_length=1, max_length=255)
    access_token: Optional[str] = Field(default=None, max_length=500)

class NtfyConfigPatch(BaseModel):
    is_enabled: bool  # für den Pausieren/Aktivieren-Toggle

class NtfyConfigResponse(BaseModel):
    configured: bool
    server_url: str | None
    topic: str | None         # Klar zurückgegeben — kein Maskieren (topic ist kein klassisches Secret)
    is_enabled: bool
    # access_token wird NIE zurückgegeben (write-only)

# AlertPrefUpdate ergänzen:
class AlertPrefUpdate(BaseModel):
    category: str
    is_enabled: Optional[bool] = None
    notify_in_app: Optional[bool] = None
    notify_email: Optional[bool] = None
    notify_push: Optional[bool] = None   # NEU
```

**Token-Update-Semantik (PUT-Verhalten — analog SMTP-Pattern):**

| `access_token` im PUT-Body | Backend-Verhalten |
|---|---|
| Feld nicht gesendet (Key fehlt) | Bestehender `access_token_encrypted` bleibt **unverändert** |
| Leerer String `""` | Bestehender `access_token_encrypted` bleibt **unverändert** (UI-Pattern: User hat das Feld nicht angefasst) |
| Nicht-leerer String | `access_token_encrypted` wird auf den neuen verschlüsselten Wert gesetzt |
| Explizit `null` (JSON `null`) | `access_token_encrypted` wird auf `NULL` gesetzt (Token entfernen) |

Das deckt den UI-Workflow "(unverändert — nur ausfüllen zum Ändern)" ab: Frontend sendet bei nicht-angefasstem Feld einen leeren String, was das Backend als "behalten" interpretiert. Identisch wie `smtp_config.password_encrypted`.

### 6.4 Retry-Strategie

**Keine Retries.** Fire-and-forget mit `logger.warning` bei Fehler. Begründung:

- ntfy-Server-Ausfälle sind kurzfristig (Netz, Sleep) — ein Retry nach 30s würde die Alert-Semantik verzerren ("Stop-Loss vor 30min erreicht")
- Der Worker läuft alle 60s ohnehin erneut — De-Duplizierung via Redis verhindert Doppel-Push im Erfolgsfall
- Kein Retry-Loop blockiert den Worker-Thread

### 6.5 Aggregierung bei Massen-Alerts

**Schwelle:** `AGGREGATION_THRESHOLD = 3` (Konstante in `ntfy_service.py`, kein User-Setting).

Verhalten:
- 1-2 Alerts derselben Kategorie im selben Worker-Run → Einzel-Pushes (jeweils mit Per-Alert-Dedup)
- Ab 3 Alerts derselben Kategorie im selben Worker-Run → ein zusammenfassender Push (mit Per-Tag-Dedup)

Gilt primär für `price_alert_service.py`, wo viele Alerts gleichzeitig triggern können.

Aggregierter Push-Format:
- Titel: `f"{len(alerts)} {_CATEGORY_LABELS_DE.get(category, category)} ausgelöst"` — z.B. "5 Preis-Alarme ausgelöst"
- Body: erste 3 Ticker mit Wert, dann "+2 weitere"

Die Aggregationslogik liegt vollständig in `ntfy_service.send_push_aggregated()` — der Caller sammelt nur die Alert-Liste und übergibt sie (Section 6.2).

### 6.6 De-Duplizierung

Beide ntfy-Dedup-Keys verwenden den bestehenden Redis-Cache (`services/cache.py`). Das ist bewusst von der Email-Dedup getrennt (unterschiedliche TTL-Semantik, andere Schlüssel-Präfixe) — aber der Mechanismus (Redis `GET`/`SET` mit `ex=`) ist identisch. Bestehende Email-Dedup-Keys (z.B. `breakout_email:{user_id}:{ticker}`, `etf_200dma_email:{user_id}:{ticker}`) bleiben unverändert; ntfy-Keys bekommen eigene Präfixe.

**Sync-Redis-Klarstellung:** `services/cache.py` nutzt das synchrone `redis`-Paket (nicht `redis.asyncio` / aioredis) — `cache.get()` und `cache.set()` sind reguläre Sync-Funktionen und werden **ohne `await`** aufgerufen, auch innerhalb der detached async-Tasks (`_send_push_inner` ruft diese nicht auf; die Dedup-Checks laufen in den sync `send_push_for_user`/`send_push_aggregated`-Funktionen vor dem Task-Spawn). Falls je auf aioredis migriert wird, muss `ntfy_service.py` mit umgestellt werden.

**Per-Alert-Dedup (Einzel-Pushes):**
- Key: `ntfy_dedup:{user_id}:{category}:{title}` (title dient als Proxy für Ticker + Bedingung)
- TTL: 86400s (24h)
- Gesetzt in `send_push_for_user()` vor dem Task-Create

**Per-Aggregat-Dedup (aggregierte Pushes):**
- Key: `ntfy_dedup_agg:{user_id}:{category}:{date}` (z.B. `ntfy_dedup_agg:abc-123:price_alert:2026-05-08`)
- TTL: 86400s (bis max. nächsten Tag)
- Semantik: ein aggregierter Push pro Kategorie pro Kalendertag, nicht pro Cycle
- Gesetzt in `send_push_aggregated()` vor dem Task-Create

**Hinweis an Fixer:** `price_alert_service.py` hat keine eigene Email-Dedup-Logik (nutzt Price-Cache als Proxy). `breakout_alert_service.py` und `etf_200dma_alert_service.py` haben eigene Email-Dedup-Keys. Die ntfy-Dedup-Keys laufen parallel dazu — kein Piggyback auf Email-Keys.

---

## 7. Frontend-Spezifikation

### 7.1 IntegrationsTab.jsx — neuer ntfy-Block

**Position:** Nach dem SMTP-Block, vor dem Ende der Seite. Eigener `<Section title="Push-Benachrichtigungen (ntfy)">`.

**Pausieren/Aktivieren-Toggle:** Am oberen Rand des ntfy-Blocks (wenn konfiguriert) erscheint ein Switch mit Label "Push-Benachrichtigungen aktiv". Zeigt den aktuellen `is_enabled`-Status; Toggle ruft `PATCH /api/settings/ntfy` mit `{"is_enabled": !current}` auf. Bei `is_enabled = false` erscheint ein gelber Badge "Pausiert" neben dem Block-Titel. Test-Push bleibt auch im Pausiert-Zustand auslösbar (ignoriert `is_enabled` — der Test dient zur Verifikation des Setups).

**Formular:** Einheitliches Formular für public ntfy.sh und self-hosted — kein Mode-Switch. Token-Feld ist optional. Direkt unter dem Token-Feld erscheint eine Hinweis-Box:

```
Topic ist nicht geheim wie ein Passwort, aber wer den Namen kennt, sieht alle Pushes.
Wähle einen langen, zufälligen Namen (z.B. openfolio-harry-7K3xQ9meinlangertopic, ≥16 Zeichen).
Self-hosted: Token zusätzlich empfohlen.
```

Diese Box ist permanent sichtbar (kein Tooltip, kein Akkordeon), gestylt als `bg-card-alt border border-border rounded p-3 text-sm text-text-secondary`.

**Inhalt (konfiguriert, aktiv):**

```
[grüner Badge] ntfy konfiguriert (ntfy.sh / topic: openfolio-harry-7K3xQ9...)

[Switch: AN] Push-Benachrichtigungen aktiv

Server-URL:  [https://ntfy.sh____________________]
Topic:       [openfolio-harry-7K3xQ9meinlangert_]   ← klar sichtbar, prefilled
Access-Token (optional): [••••••••••••••••_______]   ← "(unverändert — nur ausfüllen zum Ändern)"

[Hinweis-Box: "Topic ist nicht geheim wie ein Passwort..."]

[Speichern]  [Test-Push senden ▷]  [Entfernen]

✓ Test-Push gesendet — Notification sollte auf deinem Gerät erscheinen
```

**Inhalt (konfiguriert, pausiert):**

```
[gelber Badge] ntfy pausiert (ntfy.sh / topic: openfolio-harry-7K3xQ9...)

[Switch: AUS] Push-Benachrichtigungen aktiv

Server-URL:  [https://ntfy.sh____________________]
...

[Speichern]  [Test-Push senden ▷]  [Entfernen]
```

**Inhalt (unkonfiguriert-Zustand):**

```
Erhalte Push-Benachrichtigungen auf Android oder iOS ohne Account.
Einrichten mit ntfy.sh (kostenlos) oder self-hosted.

ntfy.sh öffnen →

Server-URL:  [https://ntfy.sh____________________]
Topic:       [________________________________]
Access-Token (optional): [________________________________]

[Hinweis-Box: "Topic ist nicht geheim wie ein Passwort..."]

[Speichern]
```

**iOS-Hinweis** (direkt unter dem gesamten Setup-Block, einzeilig, grauer Hilfetext `text-xs text-text-secondary`):

```
Android: ntfy-App in F-Droid oder Play Store (kostenlos). iOS: App Store, Push für self-hosted Server erfordert ntfy-Pro-Tier (public ntfy.sh funktioniert kostenlos).
```

**Verhaltensnoten:**
- Topic-Feld: reguläres `type="text"` (kein `type="password"` — Topic ist kein Secret, Maskierung beim Tippen wäre irreführend). Das Eingabefeld wird mit dem gespeicherten Topic-Wert aus der API prefilled (GET Response liefert `topic` klar).
- Access-Token: `type="password"`, beim Edit des bestehenden Configs Platzhalter "(unverändert — nur ausfüllen zum Ändern)" analog SMTP
- Server-URL-Validierung client-seitig: muss `/^https?:\/\/.+/.test(url)` bestehen
- Test-Button nur sichtbar wenn konfiguriert; Test-Push funktioniert auch wenn `is_enabled = false` (Pausiert-Zustand)
- Pausieren/Aktivieren-Toggle: `aria-label="Push-Benachrichtigungen pausieren"` / `"Push-Benachrichtigungen aktivieren"` je nach aktuellem Zustand

### 7.2 AlertsTab.jsx — Push-Spalte

**Nur sichtbar wenn `ntfyConfigured === true`** (State aus separatem `GET /api/settings/ntfy`-Call im `useEffect`).

Aktuelles Grid-Layout: `grid-cols-[1fr,60px,60px,60px]` (Aktiv / In-App / E-Mail)  
Neues Layout: `grid-cols-[1fr,60px,60px,60px,60px]` (Aktiv / In-App / E-Mail / Push)

**Header-Zeile:** `<Smartphone size={12} />  Push` (Lucide `Smartphone`-Icon)

**Hinweis-Banner (wenn kein ntfy konfiguriert):**

```jsx
<div className="flex items-center gap-2 p-3 bg-card-alt border border-border rounded-lg mb-4 text-sm text-text-secondary">
  <Smartphone size={14} />
  <span>Push-Benachrichtigungen nicht konfiguriert.</span>
  <button onClick={() => onNavigate('integrations')} className="text-primary hover:underline ml-1">
    Jetzt einrichten →
  </button>
</div>
```

Hierfür muss `Settings.jsx` einen `onTabChange`-Callback an `AlertsTab` übergeben (oder via `setActiveTab` aus dem Parent-Context).

### 7.3 WCAG 2.2 AA Checkliste

- Topic-Feld: `aria-label="ntfy Topic"` + `aria-describedby` auf den Hinweistext
- Access-Token: `aria-label="ntfy Access-Token (optional)"` + `aria-describedby` auf Hinweistext
- Test-Button während Loading: `aria-disabled="true"` + `aria-busy="true"`
- Spinner: `aria-label="Sende Test-Push..."` auf dem Loader2-Icon
- Erfolgs-/Fehlermeldung: `role="status"` (Erfolg) / `role="alert"` (Fehler) für Screen-Reader-Ankündigung
- Kontrast: Bestehende `text-success`/`text-danger`-Klassen sind WCAG-konform (>4.5:1 im Dark Theme — analog SMTP-Feedback-Pattern)
- Fokus-Management: Nach Test-Button-Klick bleibt Fokus auf Button (kein unerwünschtes Fokus-Springen)
- Hinweis-Box: `role="note"` damit Screen-Reader sie als informativen Hinweis ankündigt
- Pausieren/Aktivieren-Toggle: `role="switch"` + `aria-checked={is_enabled}` + `aria-label` (siehe 7.1)

### 7.4 Nielsen-Heuristiken

| Heuristik | Umsetzung |
|---|---|
| Sichtbarkeit des Systemstatus | Spinner + Statusmeldung beim Test-Push; grüner Badge wenn konfiguriert; gelber Badge "Pausiert" wenn `is_enabled = false` |
| Match zwischen System und realer Welt | "Topic" als Begriff aus ntfy-Dokumentation übernehmen, kein Aliasing |
| Benutzerkontrolle | "Entfernen"-Button jederzeit zugänglich; Opt-in per Default; Pausieren ohne Konfigurationsverlust |
| Fehlervermeidung | URL-Validierung client-seitig; Hinweis-Box erklärt Topic-Charakter und empfiehlt ≥16 Zeichen |
| Fehlerdiagnose | HTTP-Statuscode in Fehlermeldung des Test-Buttons (z.B. "403 Forbidden") |
| Konsistenz | Identisches UX-Pattern wie SMTP-Block (Badge, Test-Button, Entfernen) |
| Flexibilität | Public ntfy.sh ohne Token und self-hosted mit Token beide im selben Formular unterstützt |

---

## 8. Docker Compose — optionaler ntfy-Service

In `docker-compose.yml` als auskommentierter optionaler Block:

```yaml
# --- OPTIONAL: self-hosted ntfy ---
# Entkommentieren um ntfy lokal zu betreiben statt public ntfy.sh zu nutzen.
# Danach in OpenFolio Einstellungen als Server-URL "http://ntfy:80" eintragen.
#
#  ntfy:
#    image: binwiederhier/ntfy:latest
#    container_name: openfolio-ntfy
#    command: serve
#    environment:
#      NTFY_BASE_URL: "http://localhost"
#      NTFY_CACHE_FILE: /var/cache/ntfy/cache.db
#      NTFY_AUTH_FILE: /var/lib/ntfy/auth.db
#    volumes:
#      - ntfy_cache:/var/cache/ntfy
#      - ntfy_data:/var/lib/ntfy
#    ports:
#      - "127.0.0.1:2586:80"   # nur lokal, nicht nach aussen exponieren
#    restart: unless-stopped
#    healthcheck:
#      test: ["CMD-SHELL", "wget -q --tries=1 http://localhost/v1/health -O - | grep -c healthy"]
#      interval: 60s
#      timeout: 10s
#      retries: 3
#
# Volumes (am Ende der volumes:-Sektion hinzufügen):
#  ntfy_cache: {}
#  ntfy_data: {}
```

**Sicherheitshinweis im Kommentar:** Der self-hosted ntfy-Service ist mit `127.0.0.1:2586:80` gebunden und nicht direkt nach aussen exponiert. Für externen Zugriff vom Smartphone muss ein Reverse-Proxy (Nginx/Caddy/Traefik) vorgeschaltet werden.

---

## 9. Sicherheitsüberlegungen

| Aspekt | Umsetzung |
|---|---|
| Topic — Unguessability statt Geheimhaltung | Topic ist kein klassisches Secret (jeder Push-Empfänger sieht ihn), wird im API-Response klar zurückgegeben und im UI prefilled. Schutz durch langen, zufälligen Namen (≥16 Zeichen empfohlen). Hinweistext im UI kommuniziert diesen Charakter explizit. |
| Access-Token | Verschlüsselt mit bestehendem `encrypt_value()` aus `auth_service.py`, identisch wie SMTP-Passwort. Wird niemals im GET-Response zurückgegeben (write-only). |
| Topic nicht in URL/Logs | JSON-Publish-Mode: Topic im Body, URL ist immer `{server_url}/`. httpx loggt Request-URLs auf DEBUG-Level — der Topic-Name landet damit nicht in den Logs. |
| Server-URL-Validierung | Nur `http://` oder `https://` erlaubt (kein `file://`, kein `javascript:`) |
| Self-Hosted-Isolation | ntfy-Container nur auf `127.0.0.1` gebunden, kein direktes Expose |
| Multi-User-Isolation | `user_id` als Primary Key in `ntfy_config` — kein User kann Config eines anderen sehen/überschreiben; Buckets im Caller immer per `user_id` getrennt (Section 6.2) |
| Keine Secrets im Notification-Text | Alert-Messages enthalten niemals Access-Token, Passwörter oder interne IDs |

---

## 10. RICE Score (Priorisierung im Backlog)

```
Reach:      3  (primär Maintainer + Power-User, Einsteiger sekundär)
Impact:     4  (zeitkritische Alerts heute komplett unbedient auf Mobile)
Confidence: 4  (ntfy-API ist trivial: ein HTTP-POST, kein SDK)
Effort:     2  (3-4 Arbeitstage: 1 Migration + Service + 3 API-Endpoints + 2 Frontend-Blöcke)

RICE = (3 × 4 × 4) / 2 = 24  → hohe Priorität
```

---

## 11. Alembic-Migration

**Migrationsnummer: NICHT im Spec hardcoden.** Beim Erstellen der Migrationsdatei die Nummer aus `alembic revision --autogenerate -m "add_ntfy_config_and_push_pref"` übernehmen. Die aktuelle höchste Nummer ist `059_...` — die nächste Nummer ergibt sich automatisch. Dateiname-Platzhalter: `XXX_add_ntfy_config_and_push_pref.py`.

```python
"""Add ntfy_config table and notify_push column to alert_preferences."""

def upgrade() -> None:
    op.create_table(
        "ntfy_config",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("server_url", sa.String(500), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("access_token_encrypted", sa.String(500), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.add_column(
        "alert_preferences",
        sa.Column("notify_push", sa.Boolean(), nullable=False, server_default="false"),
    )

def downgrade() -> None:
    op.drop_column("alert_preferences", "notify_push")
    op.drop_table("ntfy_config")
```

**Migrations-Hinweis:** Falls je auf aioredis migriert wird, muss `ntfy_service.py` (Dedup-Calls) gleichzeitig auf `await cache.get()` / `await cache.set()` umgestellt werden.

---

## 12. Decisions (OQ-1 bis OQ-9 resolved)

| # | Frage | Entscheidung |
|---|---|---|
| OQ-1 | Notification-History in DB? | **Nein.** ntfy-Server hält selbst Cache (cache.db bei self-hosted), Android-App zeigt Verlauf. Debug via `logger.warning`-Logs. Als `Could`-Item zerstörungsfrei nachziehbar. |
| OQ-2 | UI: Mode-Switch oder einheitliches Formular? | **Einheitliches Formular.** Token optional (TextInput). Hinweis-Box unter Token-Feld erklärt Topic-Charakter (Section 7.1). |
| OQ-3 | Aggregations-Schwelle konfigurierbar? | **Nein, fest verdrahtet.** `AGGREGATION_THRESHOLD = 3` als Konstante in `ntfy_service.py`. 1-2 Alerts → Einzel-Pushes. Ab 3 Alerts derselben Kategorie im selben Worker-Run → ein zusammenfassender Push. |
| OQ-4 | Tags: pro Kategorie oder severity-basiert? | **Severity-basiert.** 4 Severity-Stufen mit je eigenem Tag/Emoji (siehe Section 6.1, `_SEVERITY_TAGS`-Konstante). Fixer verifiziert Kategorie→Severity-Zuordnung gegen echte Service-Kategorie-Namen. |
| OQ-5 | `rule_alert_service`: Digest-Push oder Einzel-Pushes? | **Digest-Push.** Ein Push pro Tag ("X Portfolio-Regeln getriggert — öffnen →"). Zeitkritische Quellen (`price_alert`, `breakout`, `etf_200dma_buy`, `stop_missing`/`ma_critical`) bleiben Einzel-Pushes. |
| OQ-6 | iOS-Hinweis im UI? | **Ja, einzeilig.** Direkt unter dem Setup-Block als `text-xs text-text-secondary` (siehe Section 7.1 "iOS-Hinweis"). |
| OQ-7 | Topic maskieren im API-Response? | **Nein.** Topic ist kein klassisches Secret (Unguessability-Schutz, nicht Geheimhaltung). GET-Response liefert Topic klar, Frontend prefilled das Eingabefeld. Access-Token bleibt write-only. |
| OQ-8 | ntfy-Publish-Mode: Topic in URL oder Body? | **Body (JSON-Publish-Mode).** POST gegen `{server_url}/` mit JSON-Body inkl. `topic`-Feld. Vorteil: Topic landet nicht in httpx-URL-Logs. |
| OQ-9 | Fire-and-forget: asyncio.shield oder create_task? | **asyncio.create_task() mit Strong-Reference.** Detached Task in `_pending`-Set bis zum Abschluss; Caller awaitet nicht. Inner-Funktion fängt alle Exceptions selbst ab. Strong-Reference verhindert GC-Footgun (verlorene Pushes unter Last). |

---

## 13. Dateiübersicht — was der Fixer erstellen/ändern muss

### Neue Dateien
- `backend/models/ntfy_config.py` — SQLAlchemy-Model
- `backend/services/ntfy_service.py` — HTTP-Push-Service (inkl. `AGGREGATION_THRESHOLD`, `_SEVERITY_TAGS`, `_CATEGORY_LABELS_DE`, `SEVERITY_TO_PRIORITY`, `_pending`, `_spawn_task`, `send_push_for_user`, `send_push_aggregated`, `send_push_test`)
- `backend/alembic/versions/XXX_add_ntfy_config_and_push_pref.py` — Migration (Nummer via `alembic revision` generieren, nicht hardcoden)

### Geänderte Dateien
- `backend/models/__init__.py` — `NtfyConfig` importieren
- `backend/models/alert_preference.py` — `notify_push: Mapped[bool]` Spalte
- `backend/api/settings.py` — 5 neue Endpoints + Pydantic-Schemas (`NtfyConfigCreate`, `NtfyConfigPatch`, `NtfyConfigResponse` mit klarem `topic`-Feld)
- `backend/services/price_alert_service.py` — ntfy-Call nach Email-Call (Bucket per `user_id` via `defaultdict`, `send_push_aggregated`, Severity `high`)
- `backend/services/breakout_alert_service.py` — ntfy-Call nach Email-Call (Einzel-Push via `send_push_aggregated`, Severity `high`)
- `backend/services/etf_200dma_alert_service.py` — ntfy-Call nach Email-Call (Einzel-Push, Severity `medium`) (Should)
- `backend/services/rule_alert_service.py` — Digest-Push via `send_push_aggregated`, ein Push pro Tag (Should)
- `backend/services/pending_dividend_service.py` — Digest-Push analog Email (Should)
- `frontend/src/pages/settings/IntegrationsTab.jsx` — ntfy-Konfigurationsblock (Topic als `type="text"`, prefilled aus API, Hinweis-Box mit Topic-Charakter-Erklärung, iOS-Hinweis, Pausieren/Aktivieren-Toggle mit `role="switch"`)
- `frontend/src/pages/settings/AlertsTab.jsx` — Push-Spalte + Hinweis-Banner
- `frontend/src/pages/Settings.jsx` — Tab-Change-Callback an AlertsTab
- `docker-compose.yml` — auskommentierter ntfy-Service-Block
