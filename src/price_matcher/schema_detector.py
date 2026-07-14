"""Schema detection: map arbitrary column names to canonical fields.

Real suppliers use wildly different headers ("Наименование", "Product",
"Товар", "SKU", "Артикул производителя", "Цена руб", "price, RUB", ...).
This module maps those to a small set of canonical fields used downstream.

Strategy:
    1. Normalise the header (lowercase, strip punctuation).
    2. Match against curated synonym dictionaries.
    3. Fall back to fuzzy matching when no synonym matches exactly.
    4. If a supplier has been seen before, reuse its cached mapping.

In production this module gets an LLM fallback for completely unknown
schemes; here we stop at the synonym + fuzzy layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from rapidfuzz import process

from price_matcher.schemas import ParsedRow

CanonicalField = str

CANONICAL_FIELDS: tuple[CanonicalField, ...] = (
    "supplier_sku",
    "name",
    "brand",
    "manufacturer",
    "packaging",
    "price",
    "stock",
)

# Curated synonyms (lowercase, punctuation-stripped). Russian + English.
_SYNONYMS: dict[CanonicalField, tuple[str, ...]] = {
    "supplier_sku": (
        "артикул", "артикул производителя", "sku", "code", "код", "код товара",
        "item code", "part number", "part no", "id", "арт",
    ),
    "name": (
        "наименование", "товар", "product", "name", "product name", "название",
        "наим", "productname", "товар наименование", "описание", "description",
    ),
    "brand": (
        "бренд", "производитель brand", "торговая марка", "brand", "make",
        "бренд производителя",
    ),
    "manufacturer": (
        "производитель", "изготовитель", "manufacturer", "vendor", "factory",
        "завод", "страна производитель", "страна", "country",
    ),
    "packaging": (
        "фасовка", "объем", "объём", "упаковка", "вес", "packaging", "volume",
        "weight", "pack", "unit", "единица измерения", "ед изм", "количество",
        "qty", "quantity", "size", "тар",
    ),
    "price": (
        "цена", "price", "цена руб", "price rub", "cost", "сумма", "amount",
        "цена розн", "цена опт", "опт", "розница", "цена за ед", "unit price",
        "price per unit", "стоимость",
    ),
    "stock": (
        "наличие", "склад", "остаток", "stock", "availability", "in stock",
        "qty available", "остатки", "на складе", "доступно",
    ),
}


@dataclass
class ColumnMapping:
    """Result of schema detection: canonical field → source column name."""

    mapping: dict[CanonicalField, str] = field(default_factory=dict)
    unmatched_columns: list[str] = field(default_factory=list)
    confidence: float = 0.0  # fraction of canonical fields matched

    def get(self, row: ParsedRow, field_name: CanonicalField) -> str | None:
        """Read a value from a row using the detected column name."""
        col = self.mapping.get(field_name)
        if col is None:
            return None
        val = row.raw.get(col)
        if val is None:
            return None
        return str(val).strip() or None

    def to_json(self) -> str:
        return json.dumps(
            {"mapping": self.mapping, "unmatched": self.unmatched_columns},
            ensure_ascii=False,
        )


def _normalize_header(h: str) -> str:
    """Lowercase + collapse whitespace + drop trailing punctuation."""
    return " ".join(h.lower().replace("_", " ").split()).strip(".,:;|-")


def detect_schema(rows: list[ParsedRow]) -> ColumnMapping:
    """Detect the column mapping for a list of parsed rows.

    The header is read from the first row that has any keys.
    """
    if not rows:
        return ColumnMapping()

    columns = list(rows[0].raw.keys())
    normalized = {col: _normalize_header(col) for col in columns}

    mapping: dict[CanonicalField, str] = {}
    matched_columns: set[str] = set()

    # 1) Exact synonym match (fast path).
    for field_name, synonyms in _SYNONYMS.items():
        if field_name in mapping:
            continue
        for col, norm in normalized.items():
            if col in matched_columns:
                continue
            if norm in synonyms:
                mapping[field_name] = col
                matched_columns.add(col)
                break

    # 2) Fuzzy match for remaining canonical fields against unmatched columns.
    all_synonyms_flat = [
        (field_name, syn)
        for field_name, syns in _SYNONYMS.items()
        for syn in syns
        if field_name not in mapping
    ]
    unmatched_norms = {
        col: norm for col, norm in normalized.items() if col not in matched_columns
    }

    for field_name, syn in all_synonyms_flat:
        if field_name in mapping:
            continue
        choices = list(unmatched_norms.values())
        if not choices:
            break
        match = process.extractOne(syn, choices, score_cutoff=88)
        if match is not None:
            matched_norm, score, _ = match
            # Reverse-lookup the original column name from the normalized form.
            for col, norm in unmatched_norms.items():
                if norm == matched_norm:
                    mapping[field_name] = col
                    matched_columns.add(col)
                    del unmatched_norms[col]
                    break
            break

    unmatched_columns = [col for col in columns if col not in matched_columns]
    # 'name' is mandatory; others are optional. Score reflects coverage of all fields.
    confidence = len(mapping) / len(CANONICAL_FIELDS)

    return ColumnMapping(
        mapping=mapping,
        unmatched_columns=unmatched_columns,
        confidence=confidence,
    )
