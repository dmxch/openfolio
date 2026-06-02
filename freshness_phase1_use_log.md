# Freshness-Hebel — Phase-1 Use-Log (Kill-Gate)

**Zweck:** Trial-Beweis, ob die in Phase 0 angezeigten Signal-Alter-Badges (Smart-Money-Detail-Modal) eine konkrete Ticker-Bewertung verändern. Dieses Log entscheidet, ob Phase 1 (congressional-pubDate-Scraper + `max_signal_age_days`-Filter + Frontend-Slider) gebaut wird.

| | |
|---|---|
| **Phase 0 gebaut** | 2026-05-27 (Commit `c6b19eb`) |
| **Phase 0 deployed (VM220)** | _<Datum eintragen>_ |
| **Trial-Start** | = Deploy-Datum |
| **Gate-Stichtag** | **2026-06-17** |
| **Bar** | **≥ 2 dokumentierte Fälle** |
| **Verdikt** | `OFFEN` |

## Entscheidungsregel (hart)

- **≥ 2 Einträge** mit echtem Bewertungs-Einfluss bis 2026-06-17 → **Phase 1 freigegeben** (bauen).
- **< 2 Einträge** → **Phase 0 rausreissen, Phase 1 NICHT bauen.**
- Es zählt NUR ein Fall, in dem das **angezeigte Signal-Alter** die Bewertung tatsächlich gekippt hat — nicht „Badge gesehen, war nett". Beispiel-Qualität: „Signal sah stark aus, Badge zeigte >30d → Ticker zurückgestellt / nicht ins Trade-Plan genommen."
- **Hard-Boundary:** Freshness wirkt NUR auf Anzeige/Filter, **NIE automatisch auf den Composite-Score** (HEILIGE Regel 10 + backtest-Gate). Ein Score-Decay wäre ein separates Iteration-2.5-Item mit Forward-Return-Validation, kein Teil dieses Hebels.

## Fälle

| # | Datum | Ticker | Signal(e) | Angezeigtes Alter (Badge) | Bewertung OHNE Alter | Bewertung MIT Alter | Einfluss? (J/N) |
|---|-------|--------|-----------|---------------------------|----------------------|---------------------|-----------------|
| 1 |       |        |           |                           |                      |                     |                 |
| 2 |       |        |           |                           |                      |                     |                 |
| 3 |       |        |           |                           |                      |                     |                 |

> Datierte Signale mit Badge: `insider_cluster`/`large_buy` (trade_date), `buyback`/`activist` (filing_date), `six_insider` (latest_date), `superinvestor_13f_single` (jüngstes funds[].filing_date).
> Bewusst OHNE Badge (undatiert): `congressional`, `superinvestor` (dataroma), `short_trend`, `unusual_volume`, `ftd`.

## Notizen / Beobachtungen

- _(z. B. wiederkehrende Muster: welches Signal ist chronisch alt? Fehlt ein Badge, wo eines gebraucht würde? → fliesst in Phase-1-Spec.)_

---

## Auswertung am 2026-06-17

- **Gezählte Einfluss-Fälle:** _N_
- **Verdikt:** `GO` / `KILL`
- **Begründung:**
- **Nächster Schritt:** _(Phase 1 bauen / Phase 0 rückbauen)_
