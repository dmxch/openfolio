"""Structured JSON logging configuration.

Sets up JSON-formatted log output with consistent fields for all loggers.
Supports request_id correlation when available.
"""

import logging
import os
import re
import sys

from pythonjsonlogger.json import JsonFormatter

# FMP, FRED und Finnhub nehmen den API-Key als Query-Parameter. httpx schreibt
# die volle URL in seine Fehlertexte; ohne Maskierung stünden die in der DB
# verschlüsselten Keys der Nutzer im Klartext im Log (K096, X39).
# Der Backslash beendet den Wert: so bleibt ein JSON-Escape (\" oder \n)
# direkt hinter dem Wert unangetastet.
_SECRET_QUERY_PARAM_RE = re.compile(
    r"""([?&](?:apikey|api_key|token|key)=)[^&\s"'<>#\\]+""",
    re.IGNORECASE,
)


def mask_secrets(text: str) -> str:
    """Replace the values of the query parameters apikey, api_key, token and key with ***."""
    return _SECRET_QUERY_PARAM_RE.sub(r"\1***", text)


class OpenFolioFormatter(JsonFormatter):
    """JSON formatter with OpenFolio-specific defaults."""

    def format(self, record: logging.LogRecord) -> str:
        # Auf der fertigen Zeile: deckt Meldung, Traceback und extra-Felder ab.
        return mask_secrets(super().format(record))

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record["level"] = record.levelname.lower()
        log_record["logger"] = record.name
        log_record["service"] = os.environ.get("SERVICE_NAME", "backend")
        # Remove redundant default fields
        log_record.pop("levelname", None)
        log_record.pop("name", None)


def setup_logging(service_name: str = "backend"):
    """Configure all loggers to output structured JSON."""
    os.environ["SERVICE_NAME"] = service_name

    formatter = OpenFolioFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "message": "msg"},
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    # Configure root logger
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
