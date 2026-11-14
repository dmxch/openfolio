"""Gemeinsame Eingabeprüfung für interne und externe API-Routen.

Bewusst ohne Importe aus ``services/`` oder ``models/``: das Modul wird von
Schemas und Routern gleichermassen geladen und darf keine Importzyklen öffnen.
"""

import re
from datetime import date, datetime, timedelta
from typing import Annotated

from pydantic import AfterValidator, StringConstraints

from constants.currencies import ISO_4217_CODES
from dateutils import utcnow

# --- Buchungsdatum ---

MIN_BOOKING_DATE = date(1970, 1, 1)
BOOKING_DATE_ERROR = "Datum muss zwischen 01.01.1970 und morgen liegen"


def check_booking_date(d: date) -> date:
    """Lehnt Daten vor MIN_BOOKING_DATE und nach morgen mit ValueError ab.

    «Morgen» statt «heute»: der Server rechnet in UTC, ein Nutzer östlich davon
    bucht nach Mitternacht Ortszeit schon den nächsten Kalendertag.
    """
    # datetime ist eine Unterklasse von date, lässt sich aber nicht mit date vergleichen.
    day = d.date() if isinstance(d, datetime) else d
    if day < MIN_BOOKING_DATE or day > utcnow().date() + timedelta(days=1):
        raise ValueError(BOOKING_DATE_ERROR)
    return d


BookingDate = Annotated[date, AfterValidator(check_booking_date)]

# --- Kaufdatum ---

# Kaufdatum von Immobilien, Edelmetallen und Beteiligungen. Bewusst weiter als
# BookingDate: ein geerbtes Haus oder ein alter Barren wurde vor 1970 gekauft.
MIN_PURCHASE_DATE = date(1900, 1, 1)
PURCHASE_DATE_ERROR = "Datum muss zwischen 01.01.1900 und morgen liegen"


def check_purchase_date(d: date) -> date:
    """Lehnt Kaufdaten vor MIN_PURCHASE_DATE und nach morgen (UTC) mit ValueError ab."""
    day = d.date() if isinstance(d, datetime) else d
    if day < MIN_PURCHASE_DATE or day > utcnow().date() + timedelta(days=1):
        raise ValueError(PURCHASE_DATE_ERROR)
    return d


PurchaseDate = Annotated[date, AfterValidator(check_purchase_date)]

# --- Ticker ---

MARKET_TICKER_PATTERN = r"^[A-Za-z0-9.^=&_-]{1,30}$"
_MARKET_TICKER_RE = re.compile(MARKET_TICKER_PATTERN)

MarketTicker = Annotated[str, StringConstraints(pattern=MARKET_TICKER_PATTERN)]


def is_market_ticker(value: str) -> bool:
    """True, wenn value ein Ticker nach MARKET_TICKER_PATTERN ist."""
    # fullmatch statt match: «$» akzeptiert in Python sonst ein Zeilenende am Schluss.
    return isinstance(value, str) and _MARKET_TICKER_RE.fullmatch(value) is not None


# --- Währung ---

# Das Muster lässt beide Schreibweisen zu, weil Pydantic es VOR to_upper prüft.
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z]{3}$", to_upper=True)]


def is_iso_currency(code: str) -> bool:
    """True, wenn code (Gross- oder Kleinbuchstaben) in ISO_4217_CODES steht."""
    return isinstance(code, str) and code.upper() in ISO_4217_CODES


# --- LIKE ---


def escape_like(value: str) -> str:
    """Escapt Backslash, Prozent und Unterstrich für LIKE/ILIKE mit escape="\\\\"."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
