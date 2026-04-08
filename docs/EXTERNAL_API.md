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
| GET | `/analysis/score/{ticker}` | Setup-Score 0-10 |
| GET | `/analysis/mrs/{ticker}?period=1y` | Mansfield Relative Strength History |
| GET | `/analysis/levels/{ticker}` | Support / Resistance Levels |
| GET | `/analysis/reversal/{ticker}` | 3-Punkt-Reversal-Signal |
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
