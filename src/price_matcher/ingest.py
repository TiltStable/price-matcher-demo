"""Ingestion pipeline: file → parsed rows → normalized offers → DB.

This module wires together parsers, schema detection, and unit normalization
into the SupplierOffer / Product tables.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from price_matcher.models import Supplier, SupplierOffer
from price_matcher.parsers import parse_price_list
from price_matcher.schemas import NormalizedOffer
from price_matcher.schema_detector import detect_schema
from price_matcher.unit_normalizer import normalize_packaging

logger = logging.getLogger(__name__)

# Reasons a row can be skipped, surfaced to the caller via the return tuple.
SKIP_NO_NAME = "no_name"
SKIP_PRICE_UNPARSEABLE = "price_unparseable"
SKIP_PRICE_NONPOSITIVE = "price_nonpositive"
SKIP_PACKAGING_ZERO = "packaging_zero"  # quantity_base parsed as 0 — division hazard

# How many example rows to log per skip reason (avoid log flooding).
_MAX_LOGGED_EXAMPLES_PER_REASON = 3


def ingest_price_list(
    session: Session,
    supplier_name: str,
    file_path: str | Path,
) -> tuple[int, int, str, dict[str, int]]:
    """Ingest one price list into the DB.

    Replaces the supplier's existing offers, keeps the supplier record.
    Caches the detected column mapping on the supplier for reuse.

    Returns:
        (rows_loaded, offers_inserted, mapping_json, skipped_breakdown)
        where skipped_breakdown is {reason: count} for every row that was
        read but not inserted (no name / unparseable price / nonpositive price).
    """
    rows = parse_price_list(file_path)
    if not rows:
        logger.warning("Ingest %s: parser returned 0 rows — nothing to do.", file_path)
        return 0, 0, "{}", {}

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

    skipped: dict[str, int] = {}
    examples_logged: dict[str, int] = {}
    inserted = 0

    for i, row in enumerate(rows):
        offer, reason = _row_to_offer(supplier_name, row, mapping)
        if offer is None:
            assert reason is not None
            skipped[reason] = skipped.get(reason, 0) + 1
            # Log up to N examples per reason so operators can see what failed.
            if examples_logged.get(reason, 0) < _MAX_LOGGED_EXAMPLES_PER_REASON:
                logger.warning(
                    "Skipped row %d in %s (reason=%s): %r",
                    i, file_path, reason, row.raw,
                )
                examples_logged[reason] = examples_logged.get(reason, 0) + 1
            continue

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
                price_per_base_unit=offer.price_per_base_unit,
                match_method="none",
                match_confidence=0.0,
            )
        )
        inserted += 1

    # Summary log: total skipped + breakdown.
    total_skipped = sum(skipped.values())
    if total_skipped > 0:
        logger.warning(
            "Ingested %s: %d/%d rows inserted, %d skipped — breakdown: %s",
            file_path, inserted, len(rows), total_skipped, skipped,
        )
    else:
        logger.info(
            "Ingested %s: %d/%d rows inserted, none skipped.",
            file_path, inserted, len(rows),
        )

    # No commit here — the caller (session_scope in run_pipeline) owns the
    # transaction. Flushing makes the inserts visible within this session
    # without ending the transaction, so a later failure rolls everything back.
    session.flush()
    return len(rows), inserted, mapping.to_json(), skipped


def _row_to_offer(
    supplier_name: str,
    row,
    mapping,
) -> tuple[NormalizedOffer | None, str | None]:
    """Build a NormalizedOffer from a parsed row + detected mapping.

    Returns:
        (offer, None) on success.
        (None, reason) when the row must be skipped; reason is one of
        SKIP_NO_NAME / SKIP_PRICE_UNPARSEABLE / SKIP_PRICE_NONPOSITIVE.
    """
    name = mapping.get(row, "name")
    if not name:
        return None, SKIP_NO_NAME

    price_raw = mapping.get(row, "price")
    price = _parse_price(price_raw)
    if price is None:
        return None, SKIP_PRICE_UNPARSEABLE
    if price <= 0:
        return None, SKIP_PRICE_NONPOSITIVE

    packaging_raw = mapping.get(row, "packaging")
    norm = normalize_packaging(packaging_raw)

    quantity_base = norm.quantity_base if norm else None
    unit_base = norm.unit_base if norm else None

    # quantity_base == 0 (e.g. a "0 г" cell) would ZeroDivisionError below AND
    # is real data corruption upstream — surface it as its own skip reason so
    # it is not silently lumped with "missing pack size".
    if quantity_base is not None and quantity_base <= 0:
        return None, SKIP_PACKAGING_ZERO

    # Price per 1 base unit, for fair comparison across different pack sizes.
    # None when packaging wasn't recognized — such offers are excluded from the
    # best-price selection and logged (see recompute_best_prices).
    price_per_unit = float(price) / float(quantity_base) if quantity_base else None

    return (
        NormalizedOffer(
            supplier_name=supplier_name,
            supplier_sku=mapping.get(row, "supplier_sku"),
            raw_name=name,
            raw_brand=mapping.get(row, "brand"),
            raw_packaging=packaging_raw,
            price=price,
            stock=mapping.get(row, "stock"),
            quantity_base=quantity_base,
            unit_base=unit_base,
            price_per_base_unit=price_per_unit,
        ),
        None,
    )


def _parse_price(value: str | None) -> float | None:
    """Coerce a price cell into float. Handles "1 234,56 руб" style strings.

    Returns None when the input cannot be parsed. The caller distinguishes
    "unparseable" (None here) from "nonpositive" (a real float <= 0), which
    previously were conflated into a single silent skip.
    """
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
        logger.debug("Could not parse price %r -> cleaned %r", value, s)
        return None
