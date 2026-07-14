"""Price-list file parsers.

Each parser returns a list of raw row dicts: {column_name: cell_value}.
No schema guessing happens here — that is the job of schema_detector.py.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import pandas as pd

from price_matcher.schemas import ParsedRow

logger = logging.getLogger(__name__)

ParserFn = Callable[[Path], list[ParsedRow]]

# Encodings to try in order. Russian supplier CSVs from 1C/Excel are commonly
# cp1251 (windows-1251); utf-8 (with or without BOM) is the modern default;
# latin-1 is the ultimate fallback that never raises (every byte maps).
_CSV_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "cp1251", "latin-1")


def parse_excel(path: Path) -> list[ParsedRow]:
    """Parse .xlsx / .xls. Reads the first sheet, keeps all columns as-is."""
    df = pd.read_excel(path, sheet_name=0, dtype=object)
    return [_dataframe_row_to_parsed(row) for _, row in df.iterrows()]


def parse_csv(path: Path) -> list[ParsedRow]:
    """Parse .csv with delimiter sniffing and encoding fallback.

    Tries utf-8-sig → cp1251 → latin-1 in order (Russian supplier files from
    1C/Excel are commonly Windows-1251). Delimiter is auto-detected by pandas.
    Logs the encoding that succeeded; latin-1 (the never-fail fallback) is
    logged at WARNING because it can mask mojibake for genuinely unknown
    encodings (cp866, koi8-r, etc.).
    """
    df, used_encoding = _read_csv_robust(path)
    if used_encoding == "latin-1":
        logger.warning(
            "Parsed CSV %s with encoding=latin-1 (fallback) — verify the result: "
            "latin-1 never fails, so mojibake is possible for cp866/koi8-r files.",
            path,
        )
    else:
        logger.info("Parsed CSV %s with encoding=%s", path, used_encoding)
    return [_dataframe_row_to_parsed(row) for _, row in df.iterrows()]


def _read_csv_robust(path: Path) -> tuple[pd.DataFrame, str]:
    """Read a CSV trying multiple encodings; return (df, encoding_that_worked)."""
    last_error: Exception | None = None
    for enc in _CSV_ENCODINGS:
        try:
            # sep=None + engine='python' makes pandas sniff the delimiter.
            df = pd.read_csv(path, sep=None, engine="python", dtype=object, encoding=enc)
            return df, enc
        except UnicodeDecodeError as e:
            last_error = e
            continue
    # latin-1 cannot raise UnicodeDecodeError, so this line is unreachable
    # in practice — kept as a defensive guard.
    raise ValueError(
        f"Could not decode CSV {path} with any of {_CSV_ENCODINGS}: {last_error}"
    )


def _dataframe_row_to_parsed(row: pd.Series) -> ParsedRow:
    cleaned: dict[str, str | float | None] = {}
    for col, val in row.items():
        col_name = "" if col is None else str(col).strip()
        if col_name == "":
            continue
        # pd.isna() covers float NaN, np.float64 NaN, pd.NA, and NaT — broader
        # than the old isinstance(float) check, which missed pd.NA/NaT.
        try:
            is_missing = pd.isna(val)
        except (TypeError, ValueError):
            is_missing = False
        if is_missing:
            cleaned[col_name] = None
        else:
            cleaned[col_name] = val
    return ParsedRow(raw=cleaned)


_PARSERS: dict[str, ParserFn] = {
    ".xlsx": parse_excel,
    ".xls": parse_excel,
    ".csv": parse_csv,
}


def parse_price_list(path: str | Path) -> list[ParsedRow]:
    """Dispatch to the right parser by file extension.

    Raises:
        ValueError: if the extension is not supported.
    """
    p = Path(path)
    ext = p.suffix.lower()
    parser = _PARSERS.get(ext)
    if parser is None:
        raise ValueError(
            f"Unsupported price-list format: {ext}. "
            f"Supported: {', '.join(sorted(_PARSERS))}"
        )
    return parser(p)
