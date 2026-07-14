"""Best-price aggregation: pick the cheapest offer per product, log history."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from price_matcher.models import PriceHistory, Product, Supplier, SupplierOffer
from price_matcher.schemas import BestPriceRecord


def recompute_best_prices(session: Session) -> list[BestPriceRecord]:
    """For each product with linked offers, set the best (lowest) price.

    Writes a PriceHistory row for each product that changed.
    Returns the current best-price snapshot for all products.
    """
    # Window: lowest price per product among linked offers.
    stmt = (
        select(
            SupplierOffer.product_id,
            func.min(SupplierOffer.price).label("best_price"),
        )
        .where(SupplierOffer.product_id.is_not(None))
        .group_by(SupplierOffer.product_id)
    )
    best_per_product = {
        row.product_id: float(row.best_price)
        for row in session.execute(stmt)
    }

    records: list[BestPriceRecord] = []
    for product_id, best_price in best_per_product.items():
        # The offer that achieves this best price.
        offer = session.execute(
            select(SupplierOffer)
            .where(
                SupplierOffer.product_id == product_id,
                SupplierOffer.price == best_price,
            )
            .order_by(SupplierOffer.loaded_at.desc())
            .limit(1)
        ).scalar_one()

        product = session.get(Product, product_id)
        supplier = session.get(Supplier, offer.supplier_id)

        # Record price history for audit.
        session.add(
            PriceHistory(
                product_id=product_id,
                best_offer_id=offer.id,
                price=best_price,
            )
        )

        records.append(
            BestPriceRecord(
                sku=product.sku,
                name=product.name,
                brand=product.brand,
                best_price=best_price,
                best_supplier=supplier.name,
                best_offer_id=offer.id,
                updated_at=offer.loaded_at,
                alternatives_count=_count_alternatives(session, product_id, offer.id),
            )
        )

    session.commit()
    return records


def _count_alternatives(
    session: Session, product_id: int, exclude_offer_id: int
) -> int:
    """How many other offers exist for this product (excluding the best one)."""
    return session.scalar(
        select(func.count())
        .select_from(SupplierOffer)
        .where(
            SupplierOffer.product_id == product_id,
            SupplierOffer.id != exclude_offer_id,
        )
    ) or 0
