from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# A single normalized row extracted from any supplier price list.
OfferRow = dict[str, "OfferRowValue"]
OfferRowValue = str | int | float | None


class ParsedRow(BaseModel):
    """One row of a price list after parsing but before schema detection."""

    raw: dict[str, str | float | None] = Field(
        default_factory=dict,
        description="Column name → cell value, exactly as read from the file.",
    )


class NormalizedOffer(BaseModel):
    """A supplier offer in canonical shape, ready to insert into the DB."""

    supplier_name: str
    supplier_sku: str | None = None
    raw_name: str
    raw_brand: str | None = None
    raw_packaging: str | None = None
    price: float
    stock: str | None = None
    quantity_base: float | None = None
    unit_base: Literal["g", "ml", "pcs"] | None = None
    price_per_base_unit: float | None = None

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        if self.price < 0:
            raise ValueError(f"price must be >= 0, got {self.price}")


class MatchResult(BaseModel):
    """Outcome of matching one supplier offer against the product catalog."""

    offer_id: int
    product_id: int | None
    method: Literal["exact", "fuzzy", "llm", "manual", "none"] = "none"
    confidence: float = Field(ge=0.0, le=1.0)
    detail: str | None = None


class BestPriceRecord(BaseModel):
    """One row of the aggregated best-price view (export target)."""

    sku: str
    name: str
    brand: str | None = None
    # Best price per 1 base unit (g / ml / pcs). This is the fair-comparison
    # value: offers with different pack sizes are compared by price per unit,
    # not by raw price. None when no offer had a recognized pack size.
    best_price_per_unit: float | None = None
    # The raw price of the winning offer (for reference).
    best_raw_price: float
    best_supplier: str
    best_offer_id: int
    # Pack size of the winning offer, so the consumer can interpret the price.
    best_quantity_base: float | None = None
    best_unit_base: str | None = None
    updated_at: datetime
    source: str = "auto"
    check_status: Literal["auto", "verified", "review"] = "auto"
    alternatives_count: int = 0
