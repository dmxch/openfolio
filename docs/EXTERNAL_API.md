# OpenFolio External REST API (v1)

Versionierte, read-only REST-API fuer externe Konsumenten (z.B. eine andere
Claude-Code-Instanz, eigene Skripte, Reporting-Tools).

- **Base URL:** `http://localhost:8000/api/v1/external`
- **Auth:** `X-API-Key: ofk_...` Header
- **Read-only:** keine Schreibzugriffe ueber diese API
- **Rate-Limit:** `30/minute` pro IP (bitte cachen)
- **CORS:** nicht aktiv (nicht fuer Browser-Aufrufe gedacht)

## Token-Management

Tokens werden in der OpenFolio-UI verwaltet (Einstellungen -> API-Tokens) oder
ueber die JWT-geschuetzten Endpoints unter `/api/settings/api-tokens`.

### Token erstellen

```bash
curl -X POST http://localhost:8000/api/settings/api-tokens \
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
curl http://localhost:8000/api/settings/api-tokens \
  -H "Authorization: Bearer <jwt>"
```

### Token widerrufen

```bash
curl -X DELETE http://localhost:8000/api/settings/api-tokens/<token-id> \
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
