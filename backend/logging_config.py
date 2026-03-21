"""Structured JSON logging configuration.

Sets up JSON-formatted log output with consistent fields for all loggers.
Supports request_id correlation when available.
"""

import logging
import os
import sys

from pythonjsonlogger.json import JsonFormatter


class OpenFolioFormatter(JsonFormatter):
    """JSON formatter with OpenFolio-specific defaults."""

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
