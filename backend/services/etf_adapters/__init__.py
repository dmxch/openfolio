"""ETF-Holdings-Adapter-Registry (Multi-Issuer-Look-Through).

Jeder Adapter deckt den keylosen Holdings-Kanal EINES Anbieters ab und
registriert sich beim Import via services.etf_adapters.base.register(). Dieses
Package importiert alle Adapter-Module defensiv (ein kaputtes/fehlendes Modul
darf den Refresh-Service NICHT lahmlegen — die uebrigen Adapter laufen weiter).

Reihenfolge = Prioritaet in get_adapter(); iShares zuerst (dominanter CH-Bestand).
"""
from __future__ import annotations

import importlib
import logging

from services.etf_adapters.base import (  # noqa: F401
    REGISTRY,
    EtfAdapter,
    EtfRef,
    get_adapter,
    make_holding_row,
    name_contains,
)

logger = logging.getLogger(__name__)

# Modul-Namen in Prioritaetsreihenfolge. Jedes Modul ruft am Ende register() auf.
_ADAPTER_MODULES = [
    "ishares",
    "xtrackers",
    "spdr",
    "amundi",
    "jpmorgan",
    "hsbc",
    "fidelity",
]


def _load_adapters() -> None:
    for mod in _ADAPTER_MODULES:
        try:
            importlib.import_module(f"services.etf_adapters.{mod}")
        except Exception:
            logger.exception("etf_adapters: Modul %s konnte nicht geladen werden", mod)


_load_adapters()
