"""Best-price aggregation: pick the cheapest offer per product, log history.

The "best" price is the lowest **price per base unit** (g / ml / pcs), NOT the
lowest raw price. Comparing raw prices across suppliers that sell the same
product in different pack sizes (1 kg vs 5 kg) is mathematically wrong: a 5 kg
sack for 245 ₽ is cheaper per kilogram than a 1 kg bag for 52 ₽, but the old
aggregator declared the 1 kg bag the "best" because 52 < 245.

Offers with no recognized pack size (`quantity_base IS NULL`) are EXCLUDED from
the comparison and logged — the operator can then decide whether to enrich the
packaging data. If a product has only pack-size-less offers, it is skipped
with a warning.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from price_matcher.models import PriceHistory, Product, Supplier, SupplierOffer
from price_matcher.schemas import BestPriceRecord

logger = logging.getLogger(__name__)


def recompute_best_prices(session: Session) -> list[BestPriceRecord]:
    """For each product with offers that have a pack size, pick the cheapest
    offer by price_per_base_unit. Append a PriceHistory row per product.

    Returns the current best-price snapshot for all eligible products.
    """
    # Lowest price_per_base_unit per product, considering only offers with
    # a recognized pack size.
    stmt = (
        select(
            SupplierOffer.product_id,
            func.min(SupplierOffer.price_per_base_unit).label("best_unit_price"),
        )
        .where(
            SupplierOffer.product_id.is_not(None),
            SupplierOffer.price_per_base_unit.is_not(None),
        )
        .group_by(SupplierOffer.product_id)
    )
    best_per_product = {
        row.product_id: float(row.best_unit_price)
        for row in session.execute(stmt)
    }

    # Log offers that were excluded from comparison due to missing pack size.
    _log_excluded_offers(session, set(best_per_product.keys()))

    records: list[BestPriceRecord] = []
    for product_id, best_unit_price in best_per_product.items():
        # The offer that achieves this best per-unit price. The subquery above
        # guarantees at least one row exists; order_by + limit(1) make the pick
        # deterministic on ties. Using .first() (not scalar_one) avoids both
        # MultipleResultsFound and NoResultFound — the latter could otherwise
        # fire on float/Numeric equality drift between Python and the column.
        offer = session.execute(
            select(SupplierOffer)
            .where(
                SupplierOffer.product_id == product_id,
                SupplierOffer.price_per_base_unit == best_unit_price,
            )
            .order_by(SupplierOffer.loaded_at.desc(), SupplierOffer.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if offer is None:
            # best_unit_price came from min(price_per_base_unit) on the same
            # table; a NULL here means float/Numeric drift between the aggregate
            # and the per-row comparison. Log + skip rather than abort the run.
            logger.error(
                "best-price consistency error: no offer found for product_id=%s "
                "at price_per_base_unit=%s (aggregate did not match any row — "
                "likely float/Decimal drift)",
                product_id, best_unit_price,
            )
            continue

        product = session.get(Product, product_id)
        supplier = session.get(Supplier, offer.supplier_id)

        # Price-history snapshot. best_offer_id is SET NULL on offer deletion
        # (re-ingest), but price + product_id survive — append-only history.
        session.add(
            PriceHistory(
                product_id=product_id,
                best_offer_id=offer.id,
                price=best_unit_price,
            )
        )

        records.append(
            BestPriceRecord(
                sku=product.sku,
                name=product.name,
                brand=product.brand,
                best_price_per_unit=best_unit_price,
                best_raw_price=float(offer.price),
                best_supplier=supplier.name,
                best_offer_id=offer.id,
                best_quantity_base=float(offer.quantity_base)
                if offer.quantity_base is not None
                else None,
                best_unit_base=offer.unit_base,
                updated_at=offer.loaded_at,
                alternatives_count=_count_alternatives(session, product_id, offer.id),
            )
        )

    # No commit — owned by run_pipeline's session_scope.
    session.flush()
    return records


def _log_excluded_offers(session: Session, eligible_product_ids: set[int]) -> None:
    """Log offers excluded from best-price selection.

    Splits by the actual root cause so operators can debug accurately:
      - quantity_base IS NULL  → "missing pack size" (enrich packaging data)
      - quantity_base IS NOT NULL → "invalid (zero/neg) quantity_base" (data
        corruption upstream — the row parsed but the value is unusable)
    """
    excluded = session.execute(
        select(
            SupplierOffer.id,
            SupplierOffer.raw_name,
            SupplierOffer.quantity_base,
        )
        .where(
            SupplierOffer.product_id.is_not(None),
            SupplierOffer.price_per_base_unit.is_(None),
        )
    ).all()
    if not excluded:
        return

    missing_pkg = [r for r in excluded if r.quantity_base is None]
    invalid_qty = [r for r in excluded if r.quantity_base is not None]
    if missing_pkg:
        logger.warning(
            "Excluded %d offers from best-price selection (missing pack size): %s",
            len(missing_pkg),
            [(r.id, r.raw_name) for r in missing_pkg[:5]],
        )
    if invalid_qty:
        logger.error(
            "Excluded %d offers from best-price selection (invalid zero/negative "
            "quantity_base — upstream data corruption): %s",
            len(invalid_qty),
            [(r.id, r.raw_name, float(r.quantity_base)) for r in invalid_qty[:5]],
        )


def _count_alternatives(
    session: Session, product_id: int, exclude_offer_id: int
) -> int:
    """How many other offers exist for this product (excluding the best one).

    COUNT(*) never returns NULL per SQL semantics. We still guard explicitly
    (raise, not assert) so the invariant survives `python -O` and produces a
    clear domain error instead of a generic AssertionError.
    """
    count = session.scalar(
        select(func.count())
        .select_from(SupplierOffer)
        .where(
            SupplierOffer.product_id == product_id,
            SupplierOffer.id != exclude_offer_id,
        )
    )
    if count is None:
        # Truly impossible for COUNT(*) — a NULL here signals an ORM/driver bug.
        raise RuntimeError(
            f"COUNT(*) returned NULL for product_id={product_id} — "
            "violates SQL semantics; indicates an ORM/driver bug"
        )
    return count
