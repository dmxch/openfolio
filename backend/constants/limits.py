"""Centralized per-user resource limits."""

MAX_POSITIONS_PER_USER = 500
MAX_TRANSACTIONS_PER_USER = 10000
MAX_PRECIOUS_METAL_ITEMS_PER_USER = 200
MAX_PRECIOUS_METAL_EXPENSES_PER_USER = 500
MAX_PROPERTIES_PER_USER = 20
MAX_MORTGAGES_PER_PROPERTY = 10
MAX_EXPENSES_PER_PROPERTY = 500
MAX_INCOME_PER_PROPERTY = 500
MAX_WATCHLIST_PER_USER = 200
MAX_WATCHLIST_TAGS_PER_USER = 50
MAX_IMPORT_PROFILES_PER_USER = 20
MAX_PE_HOLDINGS_PER_USER = 20
MAX_PE_VALUATIONS_PER_HOLDING = 50
MAX_PE_DIVIDENDS_PER_HOLDING = 50
MAX_PENDING_ORDERS_PER_USER = 100
# Sammelloeschung von Transaktionen: ein Import-Stapel liegt typisch bei
# einigen hundert Zeilen; die Obergrenze deckelt Laufzeit und Payload einer
# einzelnen Anfrage, ohne den Normalfall zu behindern.
MAX_BULK_DELETE_TRANSACTIONS = 500
# Import: Zeilen je Datei und Fremdwährungen je Import (je Währung ein Kursabruf).
MAX_IMPORT_ROWS = 20_000
MAX_IMPORT_FX_CURRENCIES = 10
# Zählt ALLE Preis-Alarme eines Nutzers, auch ausgelöste und inaktive.
MAX_PRICE_ALERTS_PER_USER = 500
# Längste Zeitspanne einer Snapshot-Regeneration in Tagen (rund 68 Jahre).
MAX_REGEN_SPAN_DAYS = 25_000

# --- Rate-Limits (slowapi) ---
#
# Der Limiter zählt je Client und Endpunkt-Funktion (key_style="endpoint"): alle
# Werte eines Pfadparameters teilen sich einen Zähler. Eine Route, die das
# Frontend je Ticker oder je Position in einer Schleife aufruft, braucht deshalb
# RL_TICKER_READ statt RL_READ.
RL_DEFAULT = "240/minute"  # Routen ohne eigenes @limiter.limit
RL_READ = "120/minute"
RL_TICKER_READ = "300/minute"
RL_WRITE = "30/minute"
RL_HEAVY = "5/minute"
RL_REFRESH = "2/minute"
RL_SEARCH = "60/minute"
