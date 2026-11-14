"""Vollreview 11/2026, Welle 4: letzte Übergaben.

- K023: ch_macro_service übergibt seine Symbole als Liste. yf_download teilt
  eine Zeichenkette nicht mehr; zwei Symbole in einer Zeichenkette fielen weg.
- X35: Die externe Report-Suche behandelt % und _ wörtlich, wie die interne.
- PurchaseDate hat eine Definition (api/validation.py).

Netzfrei: yf.download ist ersetzt.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import api.external_v1_schemas as ext_schemas
import api.precious_metals as precious_metals
import api.private_equity as private_equity
import api.real_estate as real_estate
import api.validation as validation
import services.ch_macro_service as ch_macro
import yf_patch
from tests.test_vr11_reports import _login, _upload, _write_key

# --- K023: zwei Symbole als Liste -----------------------------------------------


class _Download:
    """yf.download-Ersatz: Close-Spalten (Price, Ticker) für jedes angefragte Symbol."""

    def __init__(self):
        self.calls: list[object] = []

    def __call__(self, tickers, **kwargs):
        self.calls.append(tickers)
        index = pd.date_range(end=pd.Timestamp(date.today()), periods=45, freq="D")
        columns = pd.MultiIndex.from_product([["Close"], list(tickers)])
        rows = [[1.0 + day / 100 for _ in tickers] for day in range(len(index))]
        return pd.DataFrame(rows, index=index, columns=columns)


@pytest.fixture
def download(monkeypatch):
    fake = _Download()
    monkeypatch.setattr(yf_patch.yf, "download", fake)
    return fake


class TestChMacroSymbolLists:
    async def test_fx_pairs_reach_yahoo_as_two_symbols(self, download):
        result = await ch_macro._fetch_fx_pairs()
        assert download.calls == [["EURCHF=X", "USDCHF=X"]]
        assert result["warnings"] == []
        assert result["data"]["chf_eur"]["rate"] > 0
        assert result["data"]["chf_usd"]["rate"] > 0

    async def test_smi_vs_sp500_reaches_yahoo_as_two_symbols(self, download):
        result = await ch_macro._fetch_smi_vs_sp500()
        assert download.calls == [["^SSMI", "^GSPC"]]
        assert result["warnings"] == []
        assert result["data"]["relative_pct"] == 0.0


# --- X35: externe Report-Suche --------------------------------------------------


class TestExternalReportSearchIsLiteral:
    async def _seed(self, client) -> dict:
        key = await _write_key(client, await _login(client, "w4-x35@test.local"))
        await _upload(client, key, title="Prozent", body="Rendite 100% sicher")
        await _upload(client, key, title="Punkte", body="Rendite 100 Punkte")
        await _upload(client, key, title="Regel", body="der stop_loss greift")
        await _upload(client, key, title="Tippfehler", body="der stopXloss greift")
        await _upload(client, key, title="Pfad C:\\temp", body="ohne Sonderzeichen")
        return key

    async def _titles(self, client, key: dict, q: str) -> set[str]:
        res = await client.get("/api/v1/external/reports", params={"q": q}, headers=key)
        assert res.status_code == 200, res.text
        assert res.json()["total"] == len(res.json()["results"])
        return {r["title"] for r in res.json()["results"]}

    async def test_percent_underscore_and_backslash_are_literal(self, client):
        """q=_ traf jeden Report, q=100% suchte nach «100» (X35)."""
        key = await self._seed(client)
        assert await self._titles(client, key, "100%") == {"Prozent"}
        assert await self._titles(client, key, "stop_loss") == {"Regel"}
        assert await self._titles(client, key, "_") == {"Regel"}
        assert await self._titles(client, key, "%") == {"Prozent"}
        assert await self._titles(client, key, "C:\\temp") == {"Pfad C:\\temp"}

    async def test_substring_and_case_insensitive_search_stay(self, client):
        key = await self._seed(client)
        assert await self._titles(client, key, "RENDITE") == {"Prozent", "Punkte"}
        assert await self._titles(client, key, "greift") == {"Regel", "Tippfehler"}
        assert await self._titles(client, key, "pfad") == {"Pfad C:\\temp"}


# --- PurchaseDate: eine Definition ------------------------------------------------


class TestPurchaseDateHasOneDefinition:
    @pytest.mark.parametrize(
        "module", [real_estate, ext_schemas, precious_metals, private_equity],
        ids=lambda m: m.__name__,
    )
    def test_modules_share_the_type_from_validation(self, module):
        assert module.PurchaseDate is validation.PurchaseDate

    @pytest.mark.parametrize("module", [real_estate, ext_schemas], ids=lambda m: m.__name__)
    def test_bound_and_error_text_are_not_copied(self, module):
        assert module.MIN_PURCHASE_DATE is validation.MIN_PURCHASE_DATE
        assert module.PURCHASE_DATE_ERROR is validation.PURCHASE_DATE_ERROR

    def test_real_estate_keeps_the_validator_name(self):
        assert real_estate.check_purchase_date is validation.check_purchase_date
        assert not hasattr(ext_schemas, "_check_purchase_date")
