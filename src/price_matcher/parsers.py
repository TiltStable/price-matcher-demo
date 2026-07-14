"""Price-list file parsers.

Each parser returns a list of raw row dicts: {column_name: cell_value}.
No schema guessing happens here — that is the job of schema_detector.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pandas as pd

from price_matcher.schemas import ParsedRow

ParserFn = Callable[[Path], list[ParsedRow]]


def parse_excel(path: Path) -> list[ParsedRow]:
    """Parse .xlsx / .xls. Reads the first sheet, keeps all columns as-is."""
    df = pd.read_excel(path, sheet_name=0, dtype=object)
    return [_dataframe_row_to_parsed(row) for _, row in df.iterrows()]


def parse_csv(path: Path) -> list[ParsedRow]:
    """Parse .csv. Auto-detects delimiter and encoding via pandas heuristics."""
    # sep=None + engine='python' makes pandas sniff the delimiter.
    df = pd.read_csv(path, sep=None, engine="python", dtype=object, encoding="utf-8")
    return [_dataframe_row_to_parsed(row) for _, row in df.iterrows()]


def _dataframe_row_to_parsed(row: pd.Series) -> ParsedRow:
    cleaned: dict[str, str | float | None] = {}
    for col, val in row.items():
        col_name = "" if col is None else str(col).strip()
        if col_name == "":
            continue
        # pandas uses float NaN for empty cells — normalize to None.
        if isinstance(val, float) and pd.isna(val):
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
