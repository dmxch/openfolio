"""Generator fuer das US-Aktienuniversum des EPS-Scanners (S&P Composite 1500).

Scrapt die drei Wikipedia-Konstituentenlisten (S&P 500 / 400 MidCap / 600 SmallCap),
normalisiert die Symbole (Punkt -> Bindestrich fuer yfinance/Finnhub) und emittiert das
Modul `backend/services/screening/us_equity_universe.py` nach stdout.

Listenpflege (Maintainer-TODO): bei Indexanpassungen (~4x/Jahr) neu generieren:

    docker compose exec -T backend python /app/../scripts/gen_us_universe.py \
        > backend/services/screening/us_equity_universe.py

(im Container ist das Repo unter /app gemountet; Pfad ggf. anpassen.)
"""
from __future__ import annotations

import json
from io import StringIO

import httpx
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (compatible; OpenFolio-UniverseGen/1.0)"}

# Reihenfolge = Prioritaet bei (theoretisch ausgeschlossenen) Mehrfach-Mitgliedschaften.
PAGES = [
    ("sp500", "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"),
    ("sp400", "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"),
    ("sp600", "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"),
]


def normalize(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def fetch_index(url: str) -> list[tuple[str, str, str]]:
    html = httpx.get(url, headers=UA, timeout=30, follow_redirects=True).text
    tables = pd.read_html(StringIO(html))
    cand = [
        t
        for t in tables
        if any("Symbol" in str(c) for c in t.columns)
        and any("Sector" in str(c) for c in t.columns)
    ]
    if not cand:
        raise RuntimeError(f"Keine Konstituenten-Tabelle gefunden: {url}")
    t = cand[0]
    sector_col = next(c for c in t.columns if "Sector" in str(c))
    name_col = "Security" if "Security" in t.columns else next(
        c for c in t.columns if c not in ("Symbol", sector_col)
    )
    out: list[tuple[str, str, str]] = []
    for _, row in t.iterrows():
        sym = normalize(str(row["Symbol"]))
        name = str(row[name_col]).strip()
        sector = str(row[sector_col]).strip()
        if sym and sym != "NAN":
            out.append((sym, name, sector))
    return out


def build() -> dict[str, dict[str, str]]:
    meta: dict[str, dict[str, str]] = {}
    for index_key, url in PAGES:
        for sym, name, sector in fetch_index(url):
            if sym in meta:
                continue  # erste Mitgliedschaft (hoehere Prioritaet) gewinnt
            meta[sym] = {"name": name, "sector": sector, "index": index_key}
    return meta


def emit(meta: dict[str, dict[str, str]]) -> str:
    counts: dict[str, int] = {}
    for m in meta.values():
        counts[m["index"]] = counts.get(m["index"], 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))

    lines: list[str] = []
    lines.append('"""Statisches US-Aktienuniversum (S&P Composite 1500) fuer den EPS-Scanner.')
    lines.append("")
    lines.append("Symbol -> {name, sector, index}. Eigenstaendiger Resolver — NICHT an")
    lines.append("`resolve_equity_universe()` gekoppelt.")
    lines.append("")
    lines.append("AUTO-GENERIERT von scripts/gen_us_universe.py aus den Wikipedia-")
    lines.append('Konstituentenlisten "List of S&P 500/400/600 companies".')
    lines.append(f"Stand-Mitgliederzahl: {summary} (gesamt {len(meta)}).")
    lines.append("Symbol-Normalisierung: Punkt -> Bindestrich (BRK.B -> BRK-B).")
    lines.append("")
    lines.append("Listenpflege (Maintainer-TODO): bei Indexanpassungen (~4x/Jahr) via")
    lines.append("scripts/gen_us_universe.py neu generieren.")
    lines.append('"""')
    lines.append("from __future__ import annotations")
    lines.append("")
    lines.append("UNIVERSE_META: dict[str, dict[str, str]] = {")
    for sym in sorted(meta):
        m = meta[sym]
        # json.dumps escaped Backslashes/Quotes/Steuerzeichen sauber (ASCII-safe).
        lines.append(f"    {json.dumps(sym)}: {{")
        lines.append(f'        "name": {json.dumps(m["name"])},')
        lines.append(f'        "sector": {json.dumps(m["sector"])},')
        lines.append(f'        "index": {json.dumps(m["index"])}')
        lines.append("    },")
    lines.append("}")
    lines.append("")
    lines.append("")
    lines.append("UNIVERSE_TICKERS: list[str] = sorted(UNIVERSE_META)")
    lines.append("")
    lines.append("")
    lines.append("def resolve_universe() -> list[str]:")
    lines.append('    """Liefert die statische US-Symbolliste (sortiert). Keine Netzabfrage."""')
    lines.append("    return sorted(UNIVERSE_META)")
    lines.append("")
    lines.append("")
    lines.append("def company_name(ticker: str) -> str | None:")
    lines.append('    """Firmenname zum Ticker, oder None wenn nicht im Universum."""')
    lines.append('    m = UNIVERSE_META.get((ticker or "").strip().upper())')
    lines.append('    return m["name"] if m else None')
    lines.append("")
    lines.append("")
    lines.append("def gics_sector(ticker: str) -> str | None:")
    lines.append('    """GICS-Sektor zum Ticker, oder None wenn nicht im Universum."""')
    lines.append('    m = UNIVERSE_META.get((ticker or "").strip().upper())')
    lines.append('    return m["sector"] if m else None')
    lines.append("")
    lines.append("")
    lines.append("def index_membership(ticker: str) -> str | None:")
    lines.append('    """Index-Zugehoerigkeit (sp500/sp400/sp600), oder None wenn unbekannt."""')
    lines.append('    m = UNIVERSE_META.get((ticker or "").strip().upper())')
    lines.append('    return m["index"] if m else None')
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    print(emit(build()), end="")
