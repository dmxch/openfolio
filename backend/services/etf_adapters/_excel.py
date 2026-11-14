"""Geteilte Excel-Reader fuer ETF-Holdings-Adapter.

SPDR/Fidelity liefern modernes .xlsx (OOXML) -> openpyxl.
HSBC liefert legacy .xls (BIFF/OLE2)          -> xlrd.
Beide geben Zeilen als list[list[str]] zurueck (Zellen zu getrimmten Strings
normalisiert), damit die Adapter-Parser rein string-basiert arbeiten koennen.
"""
from __future__ import annotations

import io
import logging
import zipfile

logger = logging.getLogger(__name__)

# Backstops gegen Dekompressionsbomben. Ein .xlsx ist ein ZIP: der Download-Cap
# (_http.DEFAULT_MAX_BYTES) zaehlt nur die gepackten Bytes. Reale Holdings-Feeds
# haben unter 20'000 Zeilen und entpackt wenige Dutzend MiB.
MAX_XLSX_UNZIPPED_BYTES: int = 256 * 1024 * 1024
MAX_XLSX_ROWS: int = 100_000
MAX_XLSX_CELLS: int = 5_000_000


def _cell_to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        # Ganzzahlige Floats ohne ".0" (Excel liefert oft 5.0 fuer 5).
        return str(int(v)) if v.is_integer() else repr(v)
    return str(v).strip()


def _xlsx_unzipped_size(content: bytes) -> int | None:
    """Summe der entpackten Groessen laut ZIP-Verzeichnis, None wenn kein ZIP."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            return sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile:
        return None


def read_xlsx(content: bytes) -> list[list[str]]:
    """Erstes Worksheet eines .xlsx (OOXML) -> Liste von String-Zeilen. [] bei Fehler.

    Ueberschreitet die Datei eine der MAX_XLSX_*-Grenzen, kommt [] zurueck und
    nicht ein abgeschnittener Teil: ein Teil-Fetch saehe fuer den Aufrufer wie ein
    vollstaendiges Holdings-Verzeichnis aus.
    """
    try:
        import openpyxl  # pure-Python, lazy import
    except ImportError:  # pragma: no cover
        logger.error("read_xlsx: openpyxl nicht installiert")
        return []
    unzipped = _xlsx_unzipped_size(content)
    if unzipped is not None and unzipped > MAX_XLSX_UNZIPPED_BYTES:
        logger.warning(
            "read_xlsx: workbook unpacks to %s bytes, cap is %s (rejected)",
            unzipped, MAX_XLSX_UNZIPPED_BYTES,
        )
        return []
    try:
        wb = openpyxl.load_workbook(
            io.BytesIO(content), read_only=True, data_only=True
        )
    except Exception as e:
        logger.warning("read_xlsx: load_workbook fehlgeschlagen: %s", e)
        return []
    try:
        ws = wb[wb.sheetnames[0]]
        rows: list[list[str]] = []
        cells = 0
        for row in ws.iter_rows(values_only=True):
            cells += len(row)
            if len(rows) >= MAX_XLSX_ROWS or cells > MAX_XLSX_CELLS:
                logger.warning(
                    "read_xlsx: sheet exceeds %s rows or %s cells (rejected)",
                    MAX_XLSX_ROWS, MAX_XLSX_CELLS,
                )
                return []
            rows.append([_cell_to_str(c) for c in row])
        return rows
    except Exception as e:
        logger.warning("read_xlsx: iter_rows fehlgeschlagen: %s", e)
        return []
    finally:
        try:
            wb.close()
        except Exception:
            pass


def read_xls(content: bytes) -> list[list[str]]:
    """Erstes Sheet eines legacy .xls (BIFF/OLE2) -> String-Zeilen. [] bei Fehler."""
    try:
        import xlrd  # pure-Python, lazy import
    except ImportError:  # pragma: no cover
        logger.error("read_xls: xlrd nicht installiert")
        return []
    try:
        book = xlrd.open_workbook(file_contents=content)
        sheet = book.sheet_by_index(0)
        return [
            [_cell_to_str(sheet.cell_value(r, c)) for c in range(sheet.ncols)]
            for r in range(sheet.nrows)
        ]
    except Exception as e:
        logger.warning("read_xls: open/parse fehlgeschlagen: %s", e)
        return []
