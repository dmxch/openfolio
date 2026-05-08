"""ISIN-Country → Quellensteuer-Vorbelegung fuer den Dividenden-Tracker.

Multi-User-Caveat: Die Defaults gehen davon aus, dass der eingeloggte User
ein **CH-Resident** ist und der Broker (z.B. Swissquote, IBKR) DBA-Saetze
korrekt anwendet (W-8BEN o.ä. fuer US-Quellensteuer auf File). Nicht-CH-
Residents passen den Default global ueber

    user_settings.dividend_withholding_default

an, oder pro Position via

    positions.dividend_withholding_pct

(Sticky-Override, das Confirm-Modal persistiert User-Edits dort).

Aufloesungsreihenfolge im Service:
    1. position.dividend_withholding_pct (User-Override)
    2. ISIN-Country-Map (dieses Dict, gekey'd via isin[:2].upper())
    3. user_settings.dividend_withholding_default (User-Fallback)
"""

# Statutory CH-Residenten-DBA-Sätze (vereinfacht). Quelle: ESTV/SIF DBA-Liste.
# Werte als float (0.0 ≤ rate ≤ 1.0); werden in `pending_dividend_service`
# auf NUMERIC(5,4) gerundet bevor sie persistiert werden.
WITHHOLDING_BY_COUNTRY: dict[str, float] = {
    "CH": 0.3500,   # Verrechnungssteuer (rueckforderbar via Wertschriftenverzeichnis)
    "US": 0.1500,   # DBA-Satz mit W-8BEN
    "DE": 0.1500,   # DBA-Satz (Statutory waere 26.375% inkl. Soli)
    "AT": 0.1500,   # DBA-Satz (Statutory KESt waere 27.5%)
    "FR": 0.1500,   # DBA-Satz
    "NL": 0.1500,   # DBA-Satz
    "GB": 0.0000,   # keine WHT auf UK-Dividenden
    "IE": 0.0000,   # UCITS-ETFs in IE → keine Investor-Level-WHT
    "LU": 0.0000,   # UCITS-ETFs in LU → keine Investor-Level-WHT
}
