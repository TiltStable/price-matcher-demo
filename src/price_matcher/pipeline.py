"""End-to-end pipeline orchestration.

Flow:
    ingest price lists → ensure master products → match offers →
    recompute best prices → export snapshot.

This module is the glue used by the CLI and (later) by the FastAPI layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from price_matcher.best_price import recompute_best_prices
from price_matcher.db import session_scope
from price_matcher.ingest import ingest_price_list
from price_matcher.matcher import match_offer
from price_matcher.models import Product, SupplierOffer
from price_matcher.schemas import BestPriceRecord, NormalizedOffer


@dataclass
class PipelineStats:
    suppliers: int
    offers_loaded: int
    offers_matched: int
    offers_unmatched: int
    products_in_catalog: int
    rows_skipped: dict[str, int]  # {reason: count} — rows read but not inserted


def run_pipeline(
    price_lists: list[tuple[str, str | Path]],
    master_csv: str | Path | None = None,
) -> tuple[PipelineStats, list[BestPriceRecord]]:
    """Run the full pipeline.

    Args:
        price_lists: list of (supplier_name, file_path).
        master_csv: optional CSV with seed master products (sku, name, brand,
            manufacturer, quantity_base, unit_base). If None, products are
            created on-the-fly from unmatched offers.

    Returns:
        (stats, best_price_records)
    """
    with session_scope() as session:
        _load_master_products(session, master_csv)

        offers_loaded = 0
        skipped_total: dict[str, int] = {}
        for supplier_name, path in price_lists:
            _, inserted, _, skipped = ingest_price_list(session, supplier_name, path)
            offers_loaded += inserted
            for reason, count in skipped.items():
                skipped_total[reason] = skipped_total.get(reason, 0) + count

        matched, unmatched = _match_all_offers(session)
        records = recompute_best_prices(session)

        products_in_catalog = session.execute(select(Product)).scalars().all().__len__()

    stats = PipelineStats(
        suppliers=len(price_lists),
        offers_loaded=offers_loaded,
        offers_matched=matched,
        offers_unmatched=unmatched,
        products_in_catalog=products_in_catalog,
        rows_skipped=skipped_total,
    )
    return stats, records


def _load_master_products(session: Session, master_csv: str | Path | None) -> None:
    if master_csv is None:
        return
    df = pd.read_csv(master_csv)
    expected = {"sku", "name"}
    missing = expected - set(df.columns.str.lower())
    if missing:
        raise ValueError(f"master_csv missing required columns: {missing}")

    for _, row in df.iterrows():
        sku = str(row["sku"]).strip()
        # Lookup by sku first — merge() matches on primary key (id), which we
        # don't have for a new row, so it would INSERT and hit the unique
        # constraint on a second run.
        existing = session.execute(
            select(Product).where(Product.sku == sku)
        ).scalar_one_or_none()
        if existing is None:
            existing = Product(sku=sku)
            session.add(existing)
        existing.name = str(row["name"]).strip()
        existing.brand = _cell(row, "brand")
        existing.manufacturer = _cell(row, "manufacturer")
        existing.quantity_base = _cell(row, "quantity_base")
        existing.unit_base = _cell(row, "unit_base")
        existing.packaging_raw = _cell(row, "packaging_raw")
    # No commit — owned by run_pipeline's session_scope.
    session.flush()


def _cell(row, name: str):
    if name not in row.index:
        return None
    v = row[name]
    if pd.isna(v):
        return None
    return v


def _match_all_offers(session: Session) -> tuple[int, int]:
    """Apply the matching cascade to every offer that is not yet linked."""
    offers_rows = session.execute(
        select(SupplierOffer.id, SupplierOffer.supplier_id).where(
            SupplierOffer.product_id.is_(None)
        )
    ).all()

    products = session.execute(select(Product)).scalars().all()
    matched = 0
    unmatched = 0

    for offer_id, _ in offers_rows:
        offer_obj = session.get(SupplierOffer, offer_id)
        norm = NormalizedOffer(
            supplier_name="",
            supplier_sku=offer_obj.supplier_sku,
            raw_name=offer_obj.raw_name,
            raw_brand=offer_obj.raw_brand,
            raw_packaging=offer_obj.raw_packaging,
            price=float(offer_obj.price),
            stock=offer_obj.stock,
            quantity_base=float(offer_obj.quantity_base) if offer_obj.quantity_base else None,
            unit_base=offer_obj.unit_base,
        )
        decision = match_offer(norm, products)

        offer_obj.match_method = decision.method
        offer_obj.match_confidence = decision.confidence
        offer_obj.match_detail = decision.detail

        if decision.is_linked():
            offer_obj.product_id = decision.product_id
            matched += 1
        else:
            # Auto-create a new master product from the unmatched offer so
            # the best-price snapshot is complete even on the first run.
            sku = offer_obj.supplier_sku or f"AUTO-{offer_obj.id}"
            new_product = session.execute(
                select(Product).where(Product.sku == sku)
            ).scalar_one_or_none()
            if new_product is None:
                new_product = Product(
                    sku=sku,
                    name=offer_obj.raw_name,
                    brand=offer_obj.raw_brand,
                    quantity_base=offer_obj.quantity_base,
                    unit_base=offer_obj.unit_base,
                    packaging_raw=offer_obj.raw_packaging,
                )
                session.add(new_product)
                session.flush()
            offer_obj.product_id = new_product.id
            offer_obj.match_method = "manual"
            offer_obj.match_detail = "auto-created master product"
            unmatched += 1

    # No commit — owned by run_pipeline's session_scope.
    session.flush()
    return matched, unmatched
