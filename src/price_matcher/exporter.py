"""Export the best-price snapshot to Excel / CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from price_matcher.schemas import BestPriceRecord

# Column order in the exported "mother table".
EXPORT_COLUMNS = [
    "sku",
    "name",
    "brand",
    "best_price",
    "best_supplier",
    "alternatives_count",
    "updated_at",
    "best_offer_id",
    "source",
    "check_status",
]


def export_records(records: list[BestPriceRecord], out_path: str | Path) -> Path:
    """Write the best-price snapshot to .xlsx or .csv (by extension)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = [r.model_dump() for r in records]
    df = pd.DataFrame(rows, columns=EXPORT_COLUMNS)
    # Excel does not support timezone-aware datetimes — strip tz before write.
    df["updated_at"] = pd.to_datetime(df["updated_at"], utc=True).dt.tz_localize(None)

    ext = out.suffix.lower()
    if ext == ".xlsx":
        df.to_excel(out, index=False, sheet_name="best_prices")
    elif ext == ".csv":
        df.to_csv(out, index=False, encoding="utf-8")
    else:
        raise ValueError(f"Unsupported export format: {ext} (use .xlsx or .csv)")
    return out
