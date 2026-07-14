"""Soll-Matrix: jeder AssetType muss sich zu JEDER zentralen Typ-Liste erklaeren.

Warum es diese Datei gibt
-------------------------
Die Asset-Typ-Zugehoerigkeit ist im Backend auf ein Dutzend Allow-/Deny-Listen
verteilt (``TRADABLE_TYPES``, ``_SKIP_TYPES``, ``_NON_YAHOO_TYPES`` …). Bisher
gab es keine Mechanik, die einen NEUEN Enum-Wert zwingt, sich zu diesen Listen
zu verhalten: ein neuer Typ rutschte still in jede Deny-Liste hinein bzw. aus
jeder Allow-Liste heraus — ohne einen einzigen roten Test. Genau dieser stille
Default ist die teure Stelle: er faellt erst auf, wenn eine Position in einer
Auswertung fehlt, und dann ist die Zahl schon eine Weile falsch.

Dieser Test dreht den Default um: ``_SOLL`` ist die EXPLIZITE Vertrags-Matrix.
Ein Enum-Wert ohne Zeile in ``_SOLL`` (oder eine Zeile ohne alle Spalten) macht
den Test rot — Weglassen ist keine Option mehr, der naechste Typ muss die
Entscheidung pro Liste bewusst treffen und hinschreiben.

Der Test pinnt die INTENTION, nicht den Ist-Zustand. Wo Ist und Intention heute
auseinanderlaufen, steht das als Kommentar an der Zeile — nicht wegabstrahiert.

Nicht im Scope
--------------
Direktanleihen (Nominal, Prozent-Notierung, Stueckzinsen, Kupon, Verfall, YTM)
sind ein anderes Datenmodell und hier bewusst nicht abgebildet. ``bond`` meint
in dieser Matrix ausschliesslich boersengehandelte Bond-ETFs/-Fonds: Ticker,
yfinance-Stueckkurs, Ausschuettungen — mechanisch ein ETF, nur ohne Sektor und
ohne Aktien-Signale.
"""

from __future__ import annotations

import pytest

from models.position import AssetType
from services.allocation_service import EXCLUDE_LIQUID, TRADABLE_TYPES
from services.cache_service import _NON_YAHOO_TYPES
from services.correlation_service import _HHI_INVESTED_TYPES
from services.position_rebalancing_service import _TRADABLE
from services.price_staleness_service import _SKIP_TYPES
from services.snapshot_service import _LIQUID_ASSET_TYPES

# --- Spalten der Soll-Matrix -------------------------------------------------
#
# Jede Spalte ist als "gehoert dazu" formuliert (True = drin), auch wenn die
# zugrundeliegende Konstante eine Deny-Liste ist. Sonst muesste man beim Lesen
# der Matrix pro Spalte die Polaritaet mitdenken — genau da entstehen Fehler.
#
# liquid              nicht in EXCLUDE_LIQUID          -> zaehlt zur liquiden Performance (Invariante #2)
# core_satellite      in TRADABLE_TYPES                -> erscheint in der Core/Satellite-Aufteilung
# rebalancing         in _TRADABLE                     -> ist trimmbar (Positions-Rebalancing)
# hhi_invested        in _HHI_INVESTED_TYPES           -> zaehlt als investiertes Risiko-Kapital (HHI)
# yahoo_batch         NICHT in _NON_YAHOO_TYPES        -> laeuft im Yahoo-Kurs-Batch
# staleness           NICHT in _SKIP_TYPES             -> unterliegt dem Staleness-Guard
# snapshot_liquid     in _LIQUID_ASSET_TYPES           -> siehe Warnung bei test_snapshot_liquid_asset_types
_COLUMNS = frozenset(
    {
        "liquid",
        "core_satellite",
        "rebalancing",
        "hhi_invested",
        "yahoo_batch",
        "staleness",
        "snapshot_liquid",
    }
)

# --- Der Vertrag -------------------------------------------------------------
_SOLL: dict[str, dict[str, bool]] = {
    # Aktien/ETFs: der Vollausbau — handelbar, bepreist, ueberwacht.
    "stock": {
        "liquid": True,
        "core_satellite": True,
        "rebalancing": True,
        "hhi_invested": True,
        "yahoo_batch": True,
        "staleness": True,
        "snapshot_liquid": True,
    },
    "etf": {
        "liquid": True,
        "core_satellite": True,
        "rebalancing": True,
        "hhi_invested": True,
        "yahoo_batch": True,
        "staleness": True,
        "snapshot_liquid": True,
    },
    # Anleihen (Bond-ETFs): mechanisch wie ein ETF. Sie sind liquide, handelbar,
    # yahoo-bepreist und ueberwacht. Sektor-Aggregation, Aktien-Signale und
    # count_as_cash sind bewusst NICHT Teil dieser Matrix — dort ist bond raus,
    # das haengt aber an anderen Stellen als den hier gepinnten Listen.
    "bond": {
        "liquid": True,
        "core_satellite": True,
        "rebalancing": True,
        "hhi_invested": True,
        "yahoo_batch": True,
        "staleness": True,
        "snapshot_liquid": True,
    },
    # Crypto: liquide und trimmbar, aber kein Core/Satellite-Aktien-Exposure.
    # Bepreisung laeuft ueber CoinGecko — die Ausfilterung im Kurs-Batch haengt
    # am Feld ``coingecko_id``, nicht am Typ (darum yahoo_batch=True).
    "crypto": {
        "liquid": True,
        "core_satellite": False,
        "rebalancing": True,
        "hhi_invested": True,
        "yahoo_batch": True,
        "staleness": False,
        "snapshot_liquid": True,
    },
    # Commodity: wie crypto, aber ohne Typ-Skip im Staleness-Guard — Edelmetalle
    # werden dort ueber das Feld ``gold_org`` aussortiert, nicht ueber den Typ.
    "commodity": {
        "liquid": True,
        "core_satellite": False,
        "rebalancing": True,
        "hhi_invested": True,
        "yahoo_batch": True,
        "staleness": True,
        "snapshot_liquid": True,
    },
    # Cash: liquide (zaehlt zum liquiden Vermoegen), aber kein investiertes
    # Risiko-Kapital -> kein HHI, nicht trimmbar, kein Kurs.
    "cash": {
        "liquid": True,
        "core_satellite": False,
        "rebalancing": False,
        "hhi_invested": False,
        "yahoo_batch": False,
        "staleness": False,
        "snapshot_liquid": True,
    },
    # Vorsorge: aus der liquiden Performance ausgeschlossen (Invariante #2).
    # snapshot_liquid=True ist KEIN Widerspruch, sondern der Beleg dafuer, dass
    # _LIQUID_ASSET_TYPES nicht "liquide" im Sinne von Invariante #2 meint.
    "pension": {
        "liquid": False,
        "core_satellite": False,
        "rebalancing": False,
        "hhi_invested": False,
        "yahoo_batch": False,
        "staleness": False,
        "snapshot_liquid": True,
    },
    # Immobilien: illiquide (Invariante #2). hhi_invested=False aus demselben
    # Grund wie bei private_equity: der HHI-Input ist summary["positions"],
    # das RE-Positionen nie enthaelt — die fruehere Mitgliedschaft war toter
    # Vorsatz, docs/EXTERNAL_API.md dokumentiert den Ausschluss.
    # staleness=True ist eine Asymmetrie im Ist-Zustand: real_estate fehlt in
    # _SKIP_TYPES und wird nur dadurch nicht ueberwacht, dass diese Positionen
    # keinen Ticker haben (Feld-Guard statt Typ-Guard). Harmlos, aber fragil —
    # hier bewusst als Ist gepinnt, nicht stillschweigend "korrigiert".
    "real_estate": {
        "liquid": False,
        "core_satellite": False,
        "rebalancing": False,
        "hhi_invested": False,
        "yahoo_batch": False,
        "staleness": True,
        "snapshot_liquid": False,
    },
    # Private Equity: hhi_invested=False pinnt die dokumentierte Realität — der
    # HHI-Input ist summary["positions"], und das liquide Summary enthält nie
    # PE-Positionen (harter Filter in portfolio_service, Invariante #2). Die
    # frühere Mitgliedschaft in _HHI_INVESTED_TYPES war toter Vorsatz;
    # docs/EXTERNAL_API.md dokumentiert den Ausschluss (PE auch aus HHI raus).
    "private_equity": {
        "liquid": False,
        "core_satellite": False,
        "rebalancing": False,
        "hhi_invested": False,
        "yahoo_batch": False,
        "staleness": False,
        "snapshot_liquid": False,
    },
}


def _values(collection) -> set[str]:
    """Normalisiere eine Typ-Liste auf String-Values.

    Die Konstanten sind heterogen: manche halten AssetType-Member
    (``_SKIP_TYPES``), manche rohe Strings (``TRADABLE_TYPES``). Fuer den
    Vergleich zaehlt der Value, nicht die Repraesentation.
    """
    return {c.value if isinstance(c, AssetType) else str(c) for c in collection}


def _expect(asset_type: AssetType, column: str) -> bool:
    """Soll-Wert lesen — fehlender Eintrag ist ein Testfehler, kein Default.

    Das ist der Kern des Ganzen: ein neuer Enum-Wert ohne _SOLL-Zeile faellt
    hier hart durch, statt sich lautlos einen Default abzuholen.
    """
    row = _SOLL.get(asset_type.value)
    if row is None:
        pytest.fail(
            f"AssetType.{asset_type.value} hat keine Zeile in _SOLL. Ein neuer "
            f"Asset-Typ muss sich zu jeder Typ-Liste explizit erklaeren — trage "
            f"ihn mit allen Spalten {sorted(_COLUMNS)} in _SOLL ein."
        )
    if column not in row:
        pytest.fail(
            f"_SOLL['{asset_type.value}'] hat keine Spalte '{column}'. Zeile "
            f"vervollstaendigen — Weglassen ist keine Entscheidung."
        )
    return row[column]


# --- Vollstaendigkeit der Matrix selbst --------------------------------------


class TestMatrixCompleteness:
    """Die Matrix muss das Enum exakt abdecken — in beide Richtungen.

    Ohne diese Klasse waere die Matrix nur so gut wie die Disziplin, sie zu
    pflegen: ein neuer Enum-Wert wuerde von den parametrisierten Tests zwar
    erfasst, ein VERGESSENER Eintrag aber erst bei der ersten Assertion
    auffallen. Hier faellt er zentral und mit klarer Ansage auf.
    """

    def test_every_asset_type_has_a_row(self):
        """Jeder AssetType steht in _SOLL — neue Typen rutschen nicht durch."""
        missing = {t.value for t in AssetType} - set(_SOLL)
        assert not missing, (
            f"Neue AssetTypes ohne Soll-Zeile: {sorted(missing)}. Bitte in _SOLL "
            f"eintragen und pro Spalte bewusst entscheiden, statt den stillen "
            f"Default (aus jeder Allow-Liste raus) zu erben."
        )

    def test_no_stale_rows(self):
        """_SOLL enthaelt keine Karteileichen entfernter Enum-Werte."""
        stale = set(_SOLL) - {t.value for t in AssetType}
        assert not stale, (
            f"_SOLL kennt Typen, die es im Enum nicht gibt: {sorted(stale)}. Entweder "
            f"wurde der Typ aus AssetType entfernt (dann die Zeile hier loeschen) — "
            f"oder der Enum-Wert ist noch nicht gelandet. Im zweiten Fall ist die Zeile "
            f"RICHTIG und der Enum-Eintrag fehlt: nicht die Soll-Zeile wegwerfen."
        )

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    def test_row_is_complete(self, asset_type: AssetType):
        """Jede Zeile deklariert jede Spalte — keine impliziten Luecken."""
        row = _SOLL.get(asset_type.value)
        assert row is not None, f"AssetType.{asset_type.value} fehlt in _SOLL"
        assert set(row) == set(_COLUMNS), (
            f"_SOLL['{asset_type.value}']: fehlende Spalten "
            f"{sorted(_COLUMNS - set(row))}, unbekannte Spalten "
            f"{sorted(set(row) - _COLUMNS)}"
        )


# --- Die einzelnen Listen gegen den Vertrag ----------------------------------


class TestLiquidityExclusion:
    """Invariante #2: nur Immobilien, Vorsorge und PE sind aus der liquiden
    Performance ausgeschlossen. Alles andere — inkl. Anleihen — zaehlt mit."""

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    def test_exclude_liquid(self, asset_type: AssetType):
        should_be_liquid = _expect(asset_type, "liquid")
        is_excluded = asset_type.value in _values(EXCLUDE_LIQUID)
        assert is_excluded is not should_be_liquid, (
            f"allocation_service.EXCLUDE_LIQUID: {asset_type.value} ist "
            f"{'ausgeschlossen' if is_excluded else 'enthalten'}, Soll ist "
            f"{'liquide' if should_be_liquid else 'ausgeschlossen'}."
        )

    def test_exclusion_set_is_exactly_the_invariant(self):
        """Mengengleichheit statt Membership: faengt auch das HINZUFUEGEN eines
        Typs zur Ausschlussliste — das waere eine stille Aenderung von
        Invariante #2 und damit ein Bruch der historischen Vergleichbarkeit."""
        assert _values(EXCLUDE_LIQUID) == {"pension", "real_estate", "private_equity"}


class TestCoreSatellite:
    """allocation_service.TRADABLE_TYPES steuert die Core/Satellite-Aufteilung.

    Bond-ETFs gehoeren hier hinein: sie sind eine bewusst gehaltene, handelbare
    Allokation und keine Restgroesse. (Ob eine EINZELNE Position als Cash zaehlt,
    entscheidet weiterhin count_as_cash — ein Flag auf der Position, nicht der
    Typ. Anleihen tragen es nie.)
    """

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    def test_tradable_types(self, asset_type: AssetType):
        expected = _expect(asset_type, "core_satellite")
        actual = asset_type.value in _values(TRADABLE_TYPES)
        assert actual is expected, (
            f"allocation_service.TRADABLE_TYPES: {asset_type.value} "
            f"{'fehlt' if expected else 'ist drin, sollte aber raus'}."
        )


class TestRebalancing:
    """position_rebalancing_service._TRADABLE: was ist trimmbar.

    Ein Bond-Sleeve ist trimmbar wie jede andere Boersenposition — er darf im
    Rebalancing nicht als unantastbar behandelt werden.
    """

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    def test_tradable(self, asset_type: AssetType):
        expected = _expect(asset_type, "rebalancing")
        actual = asset_type.value in _values(_TRADABLE)
        assert actual is expected, (
            f"position_rebalancing_service._TRADABLE: {asset_type.value} "
            f"{'fehlt' if expected else 'ist drin, sollte aber raus'}."
        )


class TestHHIInvested:
    """correlation_service._HHI_INVESTED_TYPES: investiertes Risiko-Kapital.

    Anleihen sind investiertes Kapital (kein Dry Powder) und gehoeren in den
    HHI-Nenner. Fehlten sie, wuerde jede Aufstockung des Bond-Sleeves die
    gemessene Konzentration der Aktien still nach OBEN treiben, obwohl das
    Portfolio breiter geworden ist.
    """

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    def test_hhi_invested_types(self, asset_type: AssetType):
        expected = _expect(asset_type, "hhi_invested")
        actual = asset_type.value in _values(_HHI_INVESTED_TYPES)
        assert actual is expected, (
            f"correlation_service._HHI_INVESTED_TYPES: {asset_type.value} "
            f"{'fehlt' if expected else 'ist drin, sollte aber raus'}."
        )


class TestYahooPricing:
    """cache_service._NON_YAHOO_TYPES: wer NICHT in den Yahoo-Batch geht.

    Bond-ETFs haben einen Ticker und einen Stueckkurs (IB01.L) — sie muessen
    bepreist werden. Landeten sie in dieser Deny-Liste, blieben sie dauerhaft
    auf ihrem Einstandskurs stehen, ohne Fehlermeldung.
    """

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    def test_non_yahoo_types(self, asset_type: AssetType):
        should_be_priced = _expect(asset_type, "yahoo_batch")
        is_excluded = asset_type.value in _values(_NON_YAHOO_TYPES)
        assert is_excluded is not should_be_priced, (
            f"cache_service._NON_YAHOO_TYPES: {asset_type.value} ist "
            f"{'ausgeschlossen' if is_excluded else 'im Batch'}, Soll ist "
            f"{'bepreist' if should_be_priced else 'ausgeschlossen'}."
        )


class TestStalenessGuard:
    """price_staleness_service._SKIP_TYPES: wer vom Staleness-Guard ausgenommen ist.

    Bond-ETFs laufen durch den Yahoo-Refresh und brauchen den Guard: ein toter
    Feed friert sonst still den Kurs ein (der ROG.SW-Fall, der den Guard
    ueberhaupt ausgeloest hat).
    """

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    def test_skip_types(self, asset_type: AssetType):
        should_be_monitored = _expect(asset_type, "staleness")
        is_skipped = asset_type.value in _values(_SKIP_TYPES)
        assert is_skipped is not should_be_monitored, (
            f"price_staleness_service._SKIP_TYPES: {asset_type.value} ist "
            f"{'uebersprungen' if is_skipped else 'ueberwacht'}, Soll ist "
            f"{'ueberwacht' if should_be_monitored else 'uebersprungen'}."
        )


class TestSnapshotLiquidAssetTypes:
    """snapshot_service._LIQUID_ASSET_TYPES — ACHTUNG: TOTE KONSTANTE.

    Diese Konstante hat KEINEN Consumer. Verifiziert per grep ueber das ganze
    Backend: die einzigen Referenzen ausserhalb ihrer Definition
    (snapshot_service.py:220) sind Tests — der Golden-Master-Pin
    ``test_liquid_asset_types_exact`` und dieser Test. Kein Produktionscode
    liest sie; die tatsaechliche Snapshot-Filterung passiert woanders.

    Daraus folgt zweierlei, und beides ist wichtig:

    1. Aus der Gruenfaerbung dieses Tests (und des Golden-Masters) darf NIEMAND
       ableiten, dass ein Typ wirklich in den Snapshots landet. Diese Konstante
       beweist genau gar nichts ueber das Laufzeitverhalten. Wer Snapshot-
       Zugehoerigkeit absichern will, testet _calc_portfolio_value_fast.
    2. Sie ist trotzdem gefaehrlich, nicht bloss nutzlos: ihr Name lockt dazu,
       sie irgendwann zu verdrahten. Passiert das, waehrend ein Typ fehlt, faellt
       dieser Typ in dem Moment still aus den Snapshots. Darum wird sie hier
       gegen den Vertrag geprueft und nicht ihrem Schicksal ueberlassen.

    Ihr Name ist ausserdem irrefuehrend: sie enthaelt ``pension``, das nach
    Invariante #2 gerade NICHT liquide ist. "Liquid" meint hier "flow't in den
    Liquid-Default-Bucket", nicht "zaehlt zur liquiden Performance". Deshalb hat
    die Matrix dafuer eine eigene Spalte (``snapshot_liquid``) statt sie mit
    ``liquid`` zu verheiraten.

    Entfernt wird sie hier nicht — fremde Datei. Der saubere Zug waere: loeschen
    (samt Golden-Master-Pin) oder verdrahten.
    """

    @pytest.mark.parametrize("asset_type", list(AssetType), ids=lambda t: t.value)
    def test_liquid_asset_types(self, asset_type: AssetType):
        expected = _expect(asset_type, "snapshot_liquid")
        actual = asset_type.value in _values(_LIQUID_ASSET_TYPES)
        assert actual is expected, (
            f"snapshot_service._LIQUID_ASSET_TYPES: {asset_type.value} "
            f"{'fehlt' if expected else 'ist drin, sollte aber raus'}. "
            f"Hinweis: diese Konstante ist tot (kein Consumer) und wird zusaetzlich "
            f"vom Golden-Master exakt gepinnt (test_golden_master_calculations.py: "
            f"test_liquid_asset_types_exact) — eine Aenderung hier muss dort "
            f"nachgezogen werden, sonst kippt der Golden-Master."
        )
