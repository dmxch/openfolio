# OpenFolio External REST API (v1)

Versionierte, read-only REST-API für externe Konsumenten (z.B. eine andere
Claude-Code-Instanz, eigene Skripte, Reporting-Tools).

- **Base URL:** `https://<deine-openfolio-instanz>/api/v1/external`
  (Beispiel: `https://openfolio.cc/api/v1/external`)
- **Auth:** `X-API-Key: ofk_...` Header
- **Read-only:** keine Schreibzugriffe über diese API
- **Rate-Limit:** `30/minute` pro API-Key (Backend) + `60/minute` pro IP (nginx, Burst 60)
- **CORS:** nicht aktiv (nicht für Browser-Aufrufe gedacht)

## Deployment

Die External API teilt sich Domain und nginx-Reverse-Proxy mit dem Frontend.
Wenn deine OpenFolio-Instanz bereits öffentlich erreichbar ist (via
Cloudflare Tunnel, nginx/Caddy mit Let's Encrypt, Traefik o.ä.), ist
`/api/v1/external/*` **automatisch mit freigegeben** — keine zusätzliche
Konfiguration nötig. `frontend/nginx.conf` proxyt `location /api/` an den
Backend-Container weiter.

**Nur lokal**: Bei einem reinen Localhost-Setup ohne Public Ingress läuft
die API unter `http://localhost:8000/api/v1/external` auf demselben Host wie
OpenFolio. Für LAN-Zugriff einen SSH-Tunnel verwenden:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<openfolio-host>
```

**Sicherheits-Hinweis**: Der `X-API-Key` Header wird im Klartext gesendet.
Niemals über unverschlüsseltes HTTP im Internet freigeben — immer TLS
(HTTPS) verwenden.

## Token-Management

Tokens werden in der OpenFolio-UI verwaltet (Einstellungen -> API-Tokens) oder
über die JWT-geschützten Endpoints unter `/api/settings/api-tokens`.

In den Beispielen steht `$OPENFOLIO_HOST` als Platzhalter — setze ihn auf
deine Instanz, z.B. `export OPENFOLIO_HOST=https://openfolio.cc` oder
`export OPENFOLIO_HOST=http://localhost:8000` für lokale Entwicklung.

### Token erstellen

```bash
curl -X POST $OPENFOLIO_HOST/api/settings/api-tokens \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Claude Code Laptop","expires_in_days":90}'
```

Response (Klartext-Token wird **nur einmal** zurückgegeben):

```json
{
  "id": "5f3b...",
  "name": "Claude Code Laptop",
  "prefix": "ofk_a1b2c3d4",
  "token": "ofk_a1b2c3d4e5f6...full-256-bit-token",
  "created_at": "2026-04-08T12:00:00",
  "expires_at": "2026-07-07T12:00:00"
}
```

Bewahre den Token sicher auf — er wird nicht erneut angezeigt.

### Tokens auflisten

```bash
curl $OPENFOLIO_HOST/api/settings/api-tokens \
  -H "Authorization: Bearer <jwt>"
```

### Token widerrufen

```bash
curl -X DELETE $OPENFOLIO_HOST/api/settings/api-tokens/<token-id> \
  -H "Authorization: Bearer <jwt>"
```

## Authentifizierung

Alle externen Endpoints (ausser `/health`) erwarten den Header:

```
X-API-Key: ofk_<token>
```

Bei fehlendem, ungültigem, abgelaufenem oder widerrufenem Token wird ein
generischer **401 Unauthorized** zurückgegeben.

## Endpoints

| Method | Pfad | Beschreibung |
|---|---|---|
| GET | `/health` | Liveness-Probe (keine Auth) |
| GET | `/portfolio/summary` | Totale, Allokationen, Positionsliste |
| GET | `/portfolio/upcoming-earnings?days=N&include_etfs=bool` | Nächste Earnings-Termine der Portfolio-Positionen (Finnhub, 12h gecacht) |
| GET | `/positions` | Liste aller aktiven Positionen |
| GET | `/positions/{ticker}` | Einzelposition |
| GET | `/performance/history?period=1m\|3m\|ytd\|1y\|all&benchmark=^GSPC` | Snapshots-History |
| GET | `/performance/monthly-returns` | Modified-Dietz Monatsrenditen |
| GET | `/performance/total-return` | XIRR-basierte Total Return |
| GET | `/performance/realized-gains` | Realisierte Gewinne |
| GET | `/performance/daily-change` | Tagesveränderung |
| GET | `/analysis/score/{ticker}` | Setup-Score (score/max_score, typ. max 18) |
| GET | `/analysis/mrs/{ticker}?period=1y` | Mansfield Relative Strength History |
| GET | `/analysis/levels/{ticker}` | Support / Resistance Levels |
| GET | `/analysis/reversal/{ticker}` | 3-Punkt-Reversal-Signal |
| GET | `/analysis/correlation-matrix?period=30d\|90d\|180d\|1y` | Korrelations-Matrix + HHI-Konzentration (24h gecacht) |
| GET | `/macro/ch` | Schweizer Makro-Snapshot (SNB, SARON, FX, CPI, 10Y, SMI-vs-SP500), 6h gecacht |
| GET | `/watchlist` | Watchlist mit Preisen, Tags und Alert-Counts (ohne `notes`) |
| GET | `/screening/latest?min_score=1` | Letzte Screening-Ergebnisse |
| GET | `/screening/macro/cot` | CFTC COT Macro-Positionierung (5 Futures-Instrumente, 52w-Perzentile) |
| GET | `/immobilien` | Alle Immobilien inkl. Hypotheken (gefiltert) und Totals |
| GET | `/immobilien/{property_id}` | Detailansicht einer einzelnen Immobilie |
| GET | `/immobilien/{property_id}/hypotheken` | Hypotheken einer Immobilie |
| GET | `/vorsorge` | Alle Vorsorge-Konten (Säule 3a) |
| GET | `/vorsorge/{position_id}` | Detailansicht eines Vorsorge-Kontos |

> **Hinweis:** Immobilien (HEILIGE Regel 4) und Vorsorge (HEILIGE Regel 5)
> haben bewusst eigene Namespaces. Sie sind **nicht** Teil der liquiden
> Portfolio-Performance unter `/portfolio/*` und `/performance/*` und werden
> dort niemals eingerechnet. Aggregierte Werte (`total_value_chf`, `equity`,
> `current_mortgage`) gelten ausschliesslich innerhalb dieser Namespaces.

### Screening-Signale (Signal-Keys im `signals`-Objekt)

| Signal-Key | Quelle | Gewicht | Beschreibung |
|---|---|---|---|
| `insider_cluster` | OpenInsider (Form-4) | +3 | Mehrere Insider kaufen gleichzeitig |
| `superinvestor` | Dataroma | +2 | Superinvestor-Portfolio oder Realtime-Kauf |
| `superinvestor_13f_consensus` | SEC EDGAR 13F-HR | +3 | >=3 getrackte Fonds mit gleicher Q/Q-Aktion |
| `superinvestor_13f_single` | SEC EDGAR 13F-HR | +1 | 1-2 Fonds mit Q/Q-Aktion (informativ) |
| `six_insider` | SIX SER | +3 | Schweizer Management-Transaktion (Pflichtmeldung) |
| `activist` | SEC EDGAR 13D/13G | +2 | Aktivist-Position >5%, ggf. mit `letter_excerpt` und `purpose_tags` |
| `buyback` | SEC EDGAR | +2 | Aktienrückkauf-Ankündigung |
| `large_buy` | OpenInsider (Form-4) | +1 | Grosser Einzelkauf eines Insiders |
| `congressional` | Capitol Trades | +1 | Kongressmitglied-Kauf |
| `unusual_volume` | yfinance | 0 | Volumen >3x Durchschnitt (informativ) |
| `short_trend` | FINRA | -1 | Short-Ratio stark gestiegen |
| `ftd` | SEC | -1 | Hohe Fails-to-Deliver |
| `credit_stress` | -- | -- | Nicht implementiert (TRACE API erfordert Auth) |

## Beispiel-Responses

### `GET /watchlist`

```json
{
  "items": [
    {
      "id": "a1b2c3...",
      "ticker": "CRWD",
      "name": "CrowdStrike Holdings",
      "sector": "Technology",
      "manual_resistance": 425.00,
      "created_at": "2026-03-15T10:00:00",
      "price": 382.50,
      "currency": "USD",
      "change_pct": 1.85,
      "tags": [
        {"id": "t1...", "name": "Breakout-Kandidat", "color": "#22c55e"}
      ],
      "active_alerts": 2
    },
    {
      "id": "d4e5f6...",
      "ticker": "NESN.SW",
      "name": "Nestlé S.A.",
      "sector": "Consumer Staples",
      "manual_resistance": null,
      "created_at": "2026-01-20T14:30:00",
      "price": 87.20,
      "currency": "CHF",
      "change_pct": -0.34,
      "tags": [],
      "active_alerts": 0
    }
  ],
  "active_alerts_count": 2
}
```

Das Feld `notes` wird bewusst nicht ausgeliefert (persönliche Notizen,
serverseitig verschlüsselt).

### `GET /portfolio/summary`

```json
{
  "total_invested_chf": 125430.50,
  "total_market_value_chf": 138210.75,
  "total_pnl_chf": 12780.25,
  "total_pnl_pct": 10.19,
  "total_fees_chf": 245.30,
  "positions": [
    {
      "id": "abc-123",
      "ticker": "MSFT",
      "name": "Microsoft Corp",
      "type": "stock",
      "sector": "Technology",
      "currency": "USD",
      "shares": 25,
      "cost_basis_chf": 8200.00,
      "market_value_chf": 9850.00,
      "current_price": 412.50,
      "pnl_chf": 1650.00,
      "pnl_pct": 20.12,
      "weight_pct": 7.13,
      "position_type": "core",
      "style": "compounder",
      "mansfield_rs": 0.45,
      "ma_status": "GESUND",
      "buy_date": "2023-08-15",
      "is_etf": false
    }
  ],
  "allocations": {
    "by_type": [],
    "by_sector": [],
    "by_currency": []
  },
  "fx_rates": {"USD": 0.8821, "EUR": 0.9412}
}
```

### `GET /immobilien`

```json
{
  "total_value_chf": 1350000.00,
  "total_mortgage_chf": 795200.00,
  "total_equity_chf": 554800.00,
  "properties": [
    {
      "id": "f1e2d3...",
      "name": "Testhaus Zürich",
      "property_type": "efh",
      "purchase_date": "2020-06-01",
      "purchase_price": 1200000.00,
      "estimated_value": 1350000.00,
      "canton": "ZH",
      "current_mortgage": 795200.00,
      "equity": 554800.00,
      "equity_pct": 41.1,
      "ltv": 58.9,
      "ltv_status": "green",
      "annual_interest": 9600.00,
      "annual_amortization": 2400.00,
      "annual_expenses": 4800.00,
      "annual_income": 0.00,
      "total_annual_cost": 16800.00,
      "net_annual": -4800.00,
      "next_maturity": "2025-06-01",
      "days_until_maturity": 419,
      "unrealized_gain": 150000.00,
      "unrealized_gain_pct": 12.5,
      "mortgages": [
        {
          "id": "a1b2c3...",
          "property_id": "f1e2d3...",
          "name": "Tranche A",
          "type": "saron",
          "amount": 800000.00,
          "current_amount": 795200.00,
          "interest_rate": 1.2,
          "margin_rate": 0.85,
          "effective_rate": 1.05,
          "start_date": "2020-06-01",
          "end_date": "2025-06-01",
          "monthly_payment": 800.00,
          "monthly_total": 1000.00,
          "annual_payment": 9600.00,
          "amortization_monthly": 200.00,
          "amortization_annual": 2400.00,
          "is_active": true,
          "days_until_maturity": 419
        }
      ],
      "expenses": [],
      "income": []
    }
  ]
}
```

`effective_rate` ist bei SARON-Hypotheken dynamisch: `max(margin_rate,
margin_rate + saron_rate)`. Sensible Felder (`address`, `notes`, `bank`,
`tenant`) werden bewusst nicht ausgeliefert.

### `GET /vorsorge`

```json
{
  "total_value_chf": 25000.00,
  "accounts": [
    {
      "id": "v1w2x3...",
      "ticker": "VORSORGE-VIAC",
      "name": "VIAC 3a Konto",
      "type": "pension",
      "currency": "CHF",
      "cost_basis_chf": 25000.00,
      "market_value_chf": 25000.00,
      "buy_date": null,
      "is_active": true
    }
  ]
}
```

Vorsorge-Konten werden manuell gepflegt — `cost_basis_chf` entspricht stets
`market_value_chf`. `bank_name`, `iban` und `notes` werden nie ausgeliefert.

### `GET /portfolio/upcoming-earnings`

Liefert für jede aktive Stock/ETF-Position des Users den nächsten
Earnings-Termin im konfigurierbaren Fenster. Primärquelle ist
[Finnhub](https://finnhub.io) (strukturiert, `bmo`/`amc`/`dmh`, EPS- und
Revenue-Schätzungen, `is_confirmed`). Fällt Finnhub aus oder ist kein
`FINNHUB_API_KEY` gesetzt, wird auf yfinance zurückgefallen — dann ist
`earnings_time` immer `"unknown"` und `eps_estimate`/`revenue_estimate_usd`
sind `null`.

**Query-Parameter:**

- `days` (int, 1..60, default 7) — Lookahead-Fenster.
- `include_etfs` (bool, default true) — wenn false, werden ETFs ignoriert.

**Cache:** 12h pro `(user, days, include_etfs)`-Kombi (Response-Cache) plus
24h pro Ticker (Rich-Earnings-Cache).

```bash
curl $OPENFOLIO_HOST/api/v1/external/portfolio/upcoming-earnings?days=7 \
  -H "X-API-Key: $TOKEN"
```

```json
{
  "as_of": "2026-04-09T07:32:25+00:00",
  "lookahead_days": 7,
  "earnings": [
    {
      "ticker": "JNJ",
      "name": "JOHNSON & JOHNSON ORD",
      "type": "stock",
      "earnings_date": "2026-04-14",
      "days_until": 5,
      "earnings_time": "bmo",
      "earnings_time_label": "Before Market Open",
      "eps_estimate": 2.6999,
      "revenue_estimate_usd": 23862652556,
      "is_confirmed": true,
      "source": "finnhub"
    },
    {
      "ticker": "PEP",
      "name": "PEPSICO ORD",
      "type": "stock",
      "earnings_date": "2026-04-16",
      "days_until": 7,
      "earnings_time": "bmo",
      "earnings_time_label": "Before Market Open",
      "eps_estimate": 1.5661,
      "revenue_estimate_usd": 19120339461,
      "is_confirmed": true,
      "source": "finnhub"
    }
  ],
  "no_earnings_in_window": ["LHX", "OEF", "RSG", "WM"],
  "warnings": [
    "finnhub_no_coverage:CHSPI.SW",
    "finnhub_no_coverage:EIMI.L",
    "finnhub_no_coverage:NOVN.SW"
  ]
}
```

**Feld-Erklärung:**

- `earnings_time` — Raw-Wert von Finnhub: `bmo` (Before Market Open),
  `amc` (After Market Close), `dmh` (During Market Hours) oder `unknown`.
- `earnings_time_label` — Vorformatiertes Label für die UI.
- `days_until` — Tage bis zum Termin (0 = heute).
- `is_confirmed` — `true`, wenn Finnhub den Termin als bestätigt meldet.
  yfinance-Fallback-Einträge haben immer `false`.
- `source` — `"finnhub"` oder `"yfinance"` (Fallback).
- `no_earnings_in_window` — Tickers, die geprüft wurden und definitiv
  keinen Termin im angefragten Fenster haben. Positive Bestätigung, keine
  Lücke.
- `warnings` — Tickers, bei denen der Abruf nicht eindeutig geprüft
  werden konnte. Mögliche Prefixe:
    - `finnhub_no_coverage:<ticker>` — Finnhub's Plan (Free-Tier) deckt
      den Markt nicht ab (z.B. SIX-, LSE- oder andere Nicht-US-Listings).
      yfinance-Fallback hat ebenfalls kein Ergebnis geliefert. Die
      Information "Earnings im Fenster ja/nein" ist für diesen Ticker
      unbekannt — NICHT als "kein Termin" interpretieren.
    - `earnings_fetch_failed:<ticker>` — transienter Fehler (Netzwerk,
      Timeout, unerwartetes Exception). Kann beim nächsten Call nach
      Cache-Ablauf automatisch weg sein.

**Semantik-Regel:** Wenn ein Ticker weder in `earnings[]` noch in
`warnings[]` erscheint, ist er **definitiv** termin-frei im angefragten
Fenster. Stille Lücken gibt es nicht.

### `GET /analysis/correlation-matrix`

Paarweise Pearson-Korrelation der täglichen simple returns aller aktiven
Positionen plus HHI-basierte Konzentrations-Metriken. Reine pandas-Berechnung
auf yfinance-Daten, 24h Redis-Cache pro (User, Period, Flag-Combo).

**Query-Parameter:**

| Parameter | Default | Werte | Beschreibung |
|---|---|---|---|
| `period` | `90d` | `30d` / `90d` / `180d` / `1y` | Lookback-Fenster |
| `include_cash` | `false` | bool | Cash-Positionen in Matrix aufnehmen |
| `include_pension` | `false` | bool | Vorsorge (Säule 3a) in Matrix aufnehmen |
| `include_commodity` | `true` | bool | Rohstoffe (inkl. Gold `GC=F`) |
| `include_crypto` | `true` | bool | Krypto (BTC-USD etc.) |

Immobilien (HEILIGE Regel 4) und Private Equity (HEILIGE Regel 6) sind
**immer** ausgeschlossen — auch aus der HHI-Berechnung. Tickers mit weniger
als 20 gemeinsamen Handelstagen fallen aus der Matrix und erscheinen in
`warnings[]`.

```json
{
  "as_of": "2026-04-08T12:00:00",
  "period": "90d",
  "observations": 62,
  "filters": {
    "include_cash": false,
    "include_pension": false,
    "include_commodity": true,
    "include_crypto": true
  },
  "tickers": [
    {"yf_ticker": "MSFT", "ticker": "MSFT", "name": "Microsoft", "type": "stock", "sector": "Technology", "weight_pct": 7.13},
    {"yf_ticker": "RSG", "ticker": "RSG", "name": "Republic Services", "type": "stock", "sector": "Industrials", "weight_pct": 4.21}
  ],
  "matrix": [
    [1.0, 0.42],
    [0.42, 1.0]
  ],
  "high_correlations": [
    {
      "ticker_a": "RSG",
      "ticker_b": "WM",
      "correlation": 0.87,
      "interpretation": "gleicher Sektor (Industrials) — stark positiv korreliert"
    }
  ],
  "concentration": {
    "hhi": 0.0842,
    "effective_n": 11.88,
    "max_weight_ticker": "MSFT",
    "max_weight_pct": 7.13,
    "classification": "low"
  },
  "warnings": []
}
```

Klassifikation HHI (CFA-Konvention): `< 0.10` low, `0.10-0.18` moderate,
`> 0.18` high.

### `GET /macro/ch`

CH-Makro-Kontext in einem Call: SNB-Leitzins (inkl. nächstem geplanten
Meeting), SARON mit 30d-Delta, CHF/EUR + CHF/USD aus Schweizer Sicht
(positives Delta = CHF stärker), CH-Inflation (Headline + Core),
CH-10Y-Rendite und 30d-Performance SMI vs S&P 500. Datenquellen: SNB
Data Portal (Policy Rate + SARON), Eurostat HICP (CPI Headline + Core,
kein API-Key nötig), FRED (10Y-Rendite), yfinance (FX + Indizes).
6h Redis-Cache, partial-failure-tolerant.

**Verhalten bei Teilausfällen:** Jede nicht erreichbare Quelle landet als
maschinenlesbarer String in `warnings[]` (z.B. `fx_unavailable`,
`ch_cpi_unavailable`, `fred_no_api_key`, `snb_policy_rate_fallback_used`);
der Endpoint liefert trotzdem `200` mit dem, was verfügbar ist. Nur wenn
der Orchestrator selbst wirft, kommt ein `503` mit
`detail: "ch_macro_unavailable"`.

```json
{
  "as_of": "2026-04-09T07:06:06",
  "snb": {
    "policy_rate_pct": 0.0,
    "policy_rate_changed_on": "2025-06-20",
    "next_meeting": "2026-06-19"
  },
  "saron": {
    "current_pct": -0.04,
    "as_of": "2026-04-02",
    "delta_30d_bps": 2.0,
    "trend": "stable"
  },
  "fx": {
    "chf_eur": {"rate": 1.08361, "as_of": "2026-04-09", "delta_30d_pct": -2.082, "trend": "chf_weaker"},
    "chf_usd": {"rate": 1.26417, "as_of": "2026-04-09", "delta_30d_pct": -1.662, "trend": "chf_weaker"}
  },
  "ch_inflation": {
    "cpi_yoy_pct": 0.2,
    "cpi_as_of": "2025-12",
    "core_cpi_yoy_pct": 0.6
  },
  "ch_rates": {
    "eidg_10y_yield_pct": 0.25,
    "delta_30d_bps": -2.0,
    "trend": "stable"
  },
  "smi_vs_sp500_30d": {
    "smi_return_pct": -2.331,
    "sp500_return_pct": -1.827,
    "relative_pct": -0.504
  },
  "warnings": []
}
```

FX-Rates sind in der Konvention `1 CHF = X Fremdwährung` (umgedreht
gegenüber Yahoo Finance). `delta_30d_bps` sind Basispunkte (1 bp = 0.01%).
CPI-Daten kommen von Eurostat HICP (CH als EFTA-Land, monatliche YoY-Rate,
COICOP `CP00` für Headline und `TOT_X_NRG_FOOD` für Core). `cpi_as_of` ist
im Format `YYYY-MM` und hinkt typisch 1-2 Monate hinter dem aktuellen
Datum her (Eurostat publiziert ~4 Wochen nach Monatsende). Ohne
konfigurierten FRED-API-Key ist `ch_rates` leer + `fred_no_api_key` warning;
`ch_inflation` funktioniert ohne API-Key.

### `GET /screening/latest`

```json
{
  "scan_id": "uuid",
  "scanned_at": "2026-04-10T08:30:00",
  "total": 42,
  "results": [
    {
      "ticker": "GOOG",
      "name": "Alphabet Inc.",
      "sector": "Communication Services",
      "score": 7,
      "signals": {
        "superinvestor_13f_consensus": {
          "action": "new_position",
          "consensus_count": 4,
          "funds": [
            {"fund": "Scion Asset Management", "action": "new_position", "filing_date": "2026-02-14"},
            {"fund": "Pershing Square Capital", "action": "new_position", "filing_date": "2026-02-17"},
            {"fund": "Third Point LLC", "action": "new_position", "filing_date": "2026-02-17"},
            {"fund": "Appaloosa LP", "action": "new_position", "filing_date": "2026-02-17"}
          ],
          "quarter": "2025-Q4",
          "quarter_ready_date": "2026-03-16",
          "score_applied": 3
        },
        "insider_cluster": {
          "insider_count": 3,
          "total_value": 2500000,
          "trade_date": "2026-04-05"
        },
        "buyback": {
          "filing_date": "2026-03-15"
        }
      },
      "price_usd": 178.50
    },
    {
      "ticker": "NESN.SW",
      "name": "Nestle S.A.",
      "sector": "Consumer Staples",
      "score": 3,
      "signals": {
        "six_insider": {
          "transaction_count": 2,
          "total_amount_chf": 1150000,
          "latest_date": "2026-04-02",
          "obligor_functions": ["VR-Mitglied", "CEO"]
        }
      },
      "price_usd": null
    }
  ]
}
```

### `GET /screening/macro/cot`

CFTC COT Macro-Positionierung — isolierte Daten ohne Einfluss auf den
Equity-Screening-Score.

```json
{
  "instruments": [
    {
      "code": "GC",
      "name": "Gold (COMEX)",
      "report_date": "2026-03-31",
      "commercial_net": -201640,
      "commercial_net_pct_52w": 90.3,
      "mm_net": 92814,
      "mm_net_pct_52w": 1.7,
      "open_interest": 361409,
      "is_extreme_commercial": true,
      "is_extreme_mm": true,
      "history_weeks": 52
    }
  ],
  "updated_at": "2026-04-10T06:39:52"
}
```

## Sicherheits-Hinweise

- Sensible Felder wie `bank_name` und `iban` sind in Responses **nicht** enthalten —
  weder als Klartext noch maskiert.
- Tokens haben 256 Bit Entropie und werden serverseitig nur als sha256-Hash gespeichert.
- Bei Verdacht auf Kompromittierung: Token sofort widerrufen via UI oder
  `DELETE /api/settings/api-tokens/{id}`.
- Rate-Limit `30/minute` ist bewusst niedriger als die interne Frontend-API.
  Externe Konsumenten sollten cachen.

## Versionierung

Die API ist unter `/api/v1/external/*` gemounted. Breaking Changes erfolgen nur
unter einem neuen Versions-Prefix (`/api/v2/...`); v1 bleibt stabil.
