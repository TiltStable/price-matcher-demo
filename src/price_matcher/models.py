from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ---- Reference data ---------------------------------------------------------

class Supplier(Base):
    """A vendor that provides price lists."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)

    # Cached schema-mapping of the supplier's most recent price list.
    # Format: {"sku": "col_a", "name": "col_b", ...} — see schema_detector.py
    column_mapping_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    offers: Mapped[list[SupplierOffer]] = relationship(
        back_populates="supplier", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Supplier id={self.id} name={self.name!r}>"


class Product(Base):
    """Normalized master product (canonical record)."""

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_products_sku"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Volume/weight stored in a normalized base unit (grams or milliliters).
    # See unit_normalizer.py for the convention.
    quantity_base: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    unit_base: Mapped[Literal["g", "ml", "pcs"] | None] = mapped_column(String(8), nullable=True)

    # Raw packaging string kept for traceability (e.g. "уп. 24 шт по 100 г").
    packaging_raw: Mapped[str | None] = mapped_column(Text, nullable=True)

    offers: Mapped[list[SupplierOffer]] = relationship(back_populates="product")

    def __repr__(self) -> str:
        return f"<Product id={self.id} sku={self.sku!r} name={self.name!r}>"


# ---- Operational data -------------------------------------------------------

class SupplierOffer(Base):
    """One row from a supplier price list: a concrete offer for a product.

    An offer is linked to a Product either by an exact key (sku) or by the
    matching engine (fuzzy / LLM) with a confidence score and audit trail.
    """

    __tablename__ = "supplier_offers"
    __table_args__ = (
        UniqueConstraint("supplier_id", "supplier_sku", name="uq_offers_supplier_sku"),
        CheckConstraint(
            "match_confidence BETWEEN 0 AND 1", name="ck_confidence_range"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )

    # Raw values as they came from the file (after type coercion).
    supplier_sku: Mapped[str | None] = mapped_column(String(100), nullable=True)
    raw_name: Mapped[str] = mapped_column(String(500), nullable=False)
    raw_brand: Mapped[str | None] = mapped_column(String(200), nullable=True)
    raw_packaging: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    stock: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Normalized copy used by the matching engine.
    quantity_base: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    unit_base: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Matching audit.
    match_method: Mapped[Literal["exact", "fuzzy", "llm", "manual", "none"]] = mapped_column(
        String(16), nullable=False, default="none"
    )
    match_confidence: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0.0,
    )
    match_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    supplier: Mapped[Supplier] = relationship(back_populates="offers")
    product: Mapped[Product | None] = relationship(back_populates="offers")

    def __repr__(self) -> str:
        return (
            f"<SupplierOffer id={self.id} supplier_id={self.supplier_id} "
            f"raw_name={self.raw_name!r} price={self.price}>"
        )


class PriceHistory(Base):
    """Append-only log of best-price changes for audit and rollback."""

    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    best_offer_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_offers.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
