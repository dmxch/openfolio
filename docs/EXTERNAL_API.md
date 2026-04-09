# OpenFolio External REST API (v1)

Versionierte, read-only REST-API fuer externe Konsumenten (z.B. eine andere
Claude-Code-Instanz, eigene Skripte, Reporting-Tools).

- **Base URL:** `https://<deine-openfolio-instanz>/api/v1/external`
  (Beispiel: `https://openfolio.cc/api/v1/external`)
- **Auth:** `X-API-Key: ofk_...` Header
- **Read-only:** keine Schreibzugriffe ueber diese API
- **Rate-Limit:** `30/minute` pro API-Key (Backend) + `60/minute` pro IP (nginx, Burst 60)
- **CORS:** nicht aktiv (nicht fuer Browser-Aufrufe gedacht)

## Deployment

Die External API teilt sich Domain und nginx-Reverse-Proxy mit dem Frontend.
Wenn deine OpenFolio-Instanz bereits oeffentlich erreichbar ist (via
Cloudflare Tunnel, nginx/Caddy mit Let's Encrypt, Traefik o.ae.), ist
`/api/v1/external/*` **automatisch mit freigegeben** — keine zusaetzliche
Konfiguration noetig. `frontend/nginx.conf` proxyt `location /api/` an den
Backend-Container weiter.

**Nur lokal**: Bei einem reinen Localhost-Setup ohne Public Ingress laeuft
die API unter `http://localhost:8000/api/v1/external` auf demselben Host wie
OpenFolio. Fuer LAN-Zugriff einen SSH-Tunnel verwenden:

```bash
ssh -L 8000:127.0.0.1:8000 <user>@<openfolio-host>
```

**Sicherheits-Hinweis**: Der `X-API-Key` Header wird im Klartext gesendet.
Niemals ueber unverschluesseltes HTTP im Internet freigeben — immer TLS
(HTTPS) verwenden.

## Token-Management

Tokens werden in der OpenFolio-UI verwaltet (Einstellungen -> API-Tokens) oder
ueber die JWT-geschuetzten Endpoints unter `/api/settings/api-tokens`.

In den Beispielen steht `$OPENFOLIO_HOST` als Platzhalter — setze ihn auf
deine Instanz, z.B. `export OPENFOLIO_HOST=https://openfolio.cc` oder
`export OPENFOLIO_HOST=http://localhost:8000` fuer lokale Entwicklung.

### Token erstellen

```bash
curl -X POST $OPENFOLIO_HOST/api/settings/api-tokens \
  -H "Authorization: Bearer <jwt>" \
  -H "Content-Type: application/json" \
  -d '{"name":"Claude Code Laptop","expires_in_days":90}'
```

Response (Klartext-Token wird **nur einmal** zurueckgegeben):

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

Bei fehlendem, ungueltigem, abgelaufenem oder widerrufenem Token wird ein
generischer **401 Unauthorized** zurueckgegeben.

## Endpoints

| Method | Pfad | Beschreibung |
|---|---|---|
| GET | `/health` | Liveness-Probe (keine Auth) |
| GET | `/portfolio/summary` | Totale, Allokationen, Positionsliste |
| GET | `/positions` | Liste aller aktiven Positionen |
| GET | `/positions/{ticker}` | Einzelposition |
| GET | `/performance/history?period=1m\|3m\|ytd\|1y\|all&benchmark=^GSPC` | Snapshots-History |
| GET | `/performance/monthly-returns` | Modified-Dietz Monatsrenditen |
| GET | `/performance/total-return` | XIRR-basierte Total Return |
| GET | `/performance/realized-gains` | Realisierte Gewinne |
| GET | `/performance/daily-change` | Tagesveraenderung |
| GET | `/analysis/score/{ticker}` | Setup-Score (score/max_score, typ. max 18) |
| GET | `/analysis/mrs/{ticker}?period=1y` | Mansfield Relative Strength History |
| GET | `/analysis/levels/{ticker}` | Support / Resistance Levels |
| GET | `/analysis/reversal/{ticker}` | 3-Punkt-Reversal-Signal |
| GET | `/analysis/correlation-matrix?period=30d\|90d\|180d\|1y` | Korrelations-Matrix + HHI-Konzentration (24h gecacht) |
| GET | `/macro/ch` | Schweizer Makro-Snapshot (SNB, SARON, FX, CPI, 10Y, SMI-vs-SP500), 6h gecacht |
| GET | `/screening/latest?min_score=1` | Letzte Screening-Ergebnisse |
| GET | `/immobilien` | Alle Immobilien inkl. Hypotheken (gefiltert) und Totals |
| GET | `/immobilien/{property_id}` | Detailansicht einer einzelnen Immobilie |
| GET | `/immobilien/{property_id}/hypotheken` | Hypotheken einer Immobilie |
| GET | `/vorsorge` | Alle Vorsorge-Konten (Saeule 3a) |
| GET | `/vorsorge/{position_id}` | Detailansicht eines Vorsorge-Kontos |

> **Hinweis:** Immobilien (HEILIGE Regel 4) und Vorsorge (HEILIGE Regel 5)
> haben bewusst eigene Namespaces. Sie sind **nicht** Teil der liquiden
> Portfolio-Performance unter `/portfolio/*` und `/performance/*` und werden
> dort niemals eingerechnet. Aggregierte Werte (`total_value_chf`, `equity`,
> `current_mortgage`) gelten ausschliesslich innerhalb dieser Namespaces.

## Beispiel-Responses

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
    "by_type": [...],
    "by_sector": [...],
    "by_currency": [...]
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
      "name": "Testhaus Zuerich",
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

### `GET /analysis/correlation-matrix`

Paarweise Pearson-Korrelation der taeglichen simple returns aller aktiven
Positionen plus HHI-basierte Konzentrations-Metriken. Reine pandas-Berechnung
auf yfinance-Daten, 24h Redis-Cache pro (User, Period, Flag-Combo).

**Query-Parameter:**

| Parameter | Default | Werte | Beschreibung |
|---|---|---|---|
| `period` | `90d` | `30d` / `90d` / `180d` / `1y` | Lookback-Fenster |
| `include_cash` | `false` | bool | Cash-Positionen in Matrix aufnehmen |
| `include_pension` | `false` | bool | Vorsorge (Saeule 3a) in Matrix aufnehmen |
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

Klassifikation HHI (CFA-Konvention): `< 0.10` low, `0.10–0.18` moderate,
`> 0.18` high.

### `GET /macro/ch`

CH-Makro-Kontext in einem Call: SNB-Leitzins (inkl. naechstem geplanten
Meeting), SARON mit 30d-Delta, CHF/EUR + CHF/USD aus Schweizer Sicht
(positives Delta = CHF staerker), CH-Inflation (Headline + Core),
CH-10Y-Rendite und 30d-Performance SMI vs S&P 500. Datenquellen: SNB
Data Portal (Policy Rate + SARON), Eurostat HICP (CPI Headline + Core,
kein API-Key noetig), FRED (10Y-Rendite), yfinance (FX + Indizes).
6h Redis-Cache, partial-failure-tolerant.

**Verhalten bei Teilausfaellen:** Jede nicht erreichbare Quelle landet als
maschinenlesbarer String in `warnings[]` (z.B. `fx_unavailable`,
`ch_cpi_unavailable`, `fred_no_api_key`, `snb_policy_rate_fallback_used`);
der Endpoint liefert trotzdem `200` mit dem, was verfuegbar ist. Nur wenn
der Orchestrator selbst wirft, kommt ein `503` mit
`detail: "ch_macro_unavailable"`.

```json
{
  "as_of": "2026-04-08T12:00:00",
  "snb": {
    "policy_rate_pct": 0.5,
    "policy_rate_changed_on": "2025-12-12",
    "next_meeting": "2026-06-19"
  },
  "saron": {
    "current_pct": 0.45,
    "as_of": "2026-04-08",
    "delta_30d_bps": -2.0,
    "trend": "stable"
  },
  "fx": {
    "chf_eur": {"rate": 1.0512, "as_of": "2026-04-08", "delta_30d_pct": 0.4, "trend": "chf_stronger"},
    "chf_usd": {"rate": 1.1234, "as_of": "2026-04-08", "delta_30d_pct": -0.1, "trend": "stable"}
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
    "smi_return_pct": 2.1,
    "sp500_return_pct": 1.4,
    "relative_pct": 0.7
  },
  "warnings": []
}
```

FX-Rates sind in der Konvention `1 CHF = X Fremdwaehrung` (umgedreht
gegenueber Yahoo Finance). `delta_30d_bps` sind Basispunkte (1 bp = 0.01%).
CPI-Daten kommen von Eurostat HICP (CH als EFTA-Land, monatliche YoY-Rate,
COICOP `CP00` fuer Headline und `TOT_X_NRG_FOOD` fuer Core). `cpi_as_of` ist
im Format `YYYY-MM` und hinkt typisch 1-2 Monate hinter dem aktuellen
Datum her (Eurostat publiziert ~4 Wochen nach Monatsende). Ohne
konfigurierten FRED-API-Key ist `ch_rates` leer + `fred_no_api_key` warning;
`ch_inflation` funktioniert ohne API-Key.

### `GET /screening/latest`

```json
{
  "scan_id": "uuid",
  "scanned_at": "2026-04-08T08:30:00",
  "total": 12,
  "results": [
    {
      "ticker": "NVDA",
      "name": "NVIDIA Corp",
      "sector": "Technology",
      "score": 9,
      "signals": {"insider_buying": true, "ark_holdings": true},
      "price_usd": 925.50
    }
  ]
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
