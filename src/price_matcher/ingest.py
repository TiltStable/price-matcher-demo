"""Ingestion pipeline: file → parsed rows → normalized offers → DB.

This module wires together parsers, schema detection, and unit normalization
into the SupplierOffer / Product tables.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_matcher.models import Supplier, SupplierOffer
from price_matcher.parsers import parse_price_list
from price_matcher.schemas import NormalizedOffer
from price_matcher.schema_detector import detect_schema
from price_matcher.unit_normalizer import normalize_packaging


def ingest_price_list(
    session: Session,
    supplier_name: str,
    file_path: str | Path,
) -> tuple[int, int, str]:
    """Ingest one price list into the DB.

    Replaces the supplier's existing offers, keeps the supplier record.
    Caches the detected column mapping on the supplier for reuse.

    Returns:
        (rows_loaded, offers_inserted, mapping_json)
    """
    rows = parse_price_list(file_path)
    if not rows:
        return 0, 0, "{}"

    mapping = detect_schema(rows)
    if "name" not in mapping.mapping:
        raise ValueError(
            f"Could not detect a product-name column in {file_path}. "
            f"Detected: {mapping.mapping}; unmatched: {mapping.unmatched_columns}"
        )
    if "price" not in mapping.mapping:
        raise ValueError(
            f"Could not detect a price column in {file_path}. "
            f"Detected: {mapping.mapping}"
        )

    # Get or create the supplier, cache the schema mapping.
    supplier = session.execute(
        select(Supplier).where(Supplier.name == supplier_name)
    ).scalar_one_or_none()
    if supplier is None:
        supplier = Supplier(name=supplier_name, column_mapping_json=mapping.to_json())
        session.add(supplier)
    else:
        supplier.column_mapping_json = mapping.to_json()
        # Drop previous offers — we reload the whole list each time.
        session.execute(
            SupplierOffer.__table__.delete().where(
                SupplierOffer.supplier_id == supplier.id
            )
        )
    session.flush()

    offers: list[NormalizedOffer] = []
    for row in rows:
        offer = _row_to_offer(supplier_name, row, mapping)
        if offer is None:
            continue
        offers.append(offer)

    inserted = 0
    for offer in offers:
        session.add(
            SupplierOffer(
                supplier_id=supplier.id,
                supplier_sku=offer.supplier_sku,
                raw_name=offer.raw_name,
                raw_brand=offer.raw_brand,
                raw_packaging=offer.raw_packaging,
                price=offer.price,
                stock=offer.stock,
                quantity_base=offer.quantity_base,
                unit_base=offer.unit_base,
                match_method="none",
                match_confidence=0.0,
            )
        )
        inserted += 1

    session.commit()
    return len(rows), inserted, mapping.to_json()


def _row_to_offer(
    supplier_name: str,
    row,
    mapping,
) -> NormalizedOffer | None:
    """Build a NormalizedOffer from a parsed row + detected mapping."""
    name = mapping.get(row, "name")
    if not name:
        return None
    price_raw = mapping.get(row, "price")
    price = _parse_price(price_raw)
    if price is None or price <= 0:
        return None

    packaging_raw = mapping.get(row, "packaging")
    norm = normalize_packaging(packaging_raw)

    return NormalizedOffer(
        supplier_name=supplier_name,
        supplier_sku=mapping.get(row, "supplier_sku"),
        raw_name=name,
        raw_brand=mapping.get(row, "brand"),
        raw_packaging=packaging_raw,
        price=price,
        stock=mapping.get(row, "stock"),
        quantity_base=norm.quantity_base if norm else None,
        unit_base=norm.unit_base if norm else None,
    )


def _parse_price(value: str | None) -> float | None:
    """Coerce a price cell into float. Handles "1 234,56 руб" style strings."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Strip currency symbols and spaces used as thousands separators.
    s = (
        s.replace("руб", "")
        .replace("rub", "")
        .replace("р.", "")
        .replace("₽", "")
        .replace("\xa0", " ")
        .replace(" ", "")
    )
    # Decimal comma → dot (only if there's no dot already).
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    elif "," in s and "." in s:
        # Likely "1.234,56" — drop the thousands dot, swap comma to dot.
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None
