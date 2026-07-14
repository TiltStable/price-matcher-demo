"""Matching engine: link a supplier offer to a master product.

Cascade (cheapest first):
    1. EXACT  — supplier SKU + brand matches a product exactly.
    2. FUZZY  — name + brand similarity above threshold, AND
                normalized unit compatible (same base unit, quantity close).
    3. LLM    — when enabled, asks GPT-4o-mini to confirm fuzzy candidates.
                Currently a stub: returns the fuzzy result unchanged.

Each decision is recorded with (method, confidence, detail) so the caller
can audit and review low-confidence matches later.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from rapidfuzz import fuzz

from price_matcher.models import Product, SupplierOffer
from price_matcher.schemas import NormalizedOffer

MatchMethod = Literal["exact", "fuzzy", "llm", "manual", "none"]

# Thresholds (tuned empirically; expose to config later).
FUZZY_NAME_THRESHOLD = 85      # token_set_ratio on product name
FUZZY_BRAND_BONUS = 10         # confidence boost when brand also matches
UNIT_TOLERANCE_PCT = 0.10      # ±10% difference in quantity_base is "compatible"
MIN_ACCEPTABLE_CONFIDENCE = 0.6


@dataclass
class MatchDecision:
    product_id: int | None
    method: MatchMethod
    confidence: float
    detail: str

    def is_linked(self) -> bool:
        return self.product_id is not None


def match_offer(
    offer: NormalizedOffer,
    candidates: list[Product],
) -> MatchDecision:
    """Run the cascade for a single offer.

    Args:
        offer: normalized supplier offer.
        candidates: candidate master products to match against. The caller is
            responsible for pre-filtering (e.g. by category) to keep this fast.
    """
    if not candidates:
        return MatchDecision(None, "none", 0.0, "no candidates")

    # 1) EXACT — SKU + brand.
    if offer.supplier_sku:
        for p in candidates:
            if offer.supplier_sku.strip().lower() == (p.sku or "").strip().lower():
                confidence = 1.0
                if offer.raw_brand and p.brand:
                    confidence = (
                        1.0 if offer.raw_brand.lower() == p.brand.lower() else 0.95
                    )
                return MatchDecision(p.id, "exact", confidence, "sku+brand exact")

    # 2) FUZZY — name + brand + unit compatibility.
    best: tuple[float, Product, str] | None = None  # (score, product, detail)
    for p in candidates:
        name_score = fuzz.token_set_ratio(
            _norm_text(offer.raw_name), _norm_text(p.name)
        )
        if name_score < FUZZY_NAME_THRESHOLD:
            continue

        # Brand contributes a bonus, not a hard filter — brands are often missing.
        confidence = name_score / 100.0
        detail_parts = [f"name={name_score}"]
        if offer.raw_brand and p.brand:
            brand_score = fuzz.ratio(
                _norm_text(offer.raw_brand), _norm_text(p.brand)
            )
            if brand_score >= 90:
                confidence = min(1.0, confidence + FUZZY_BRAND_BONUS / 100.0)
                detail_parts.append(f"brand=+{int(brand_score)}")

        # Unit compatibility: optional but strong signal.
        unit_note = _unit_compatibility_note(offer, p)
        if unit_note == "incompatible":
            confidence -= 0.2
            detail_parts.append("unit:incompatible")
        elif unit_note == "compatible":
            confidence += 0.05
            detail_parts.append("unit:compatible")

        # Cap to [0, 1] — bonuses and penalties must never violate the
        # match_confidence CHECK constraint in the DB.
        confidence = max(0.0, min(1.0, confidence))

        detail = ",".join(detail_parts)
        if best is None or confidence > best[0]:
            best = (confidence, p, detail)

    if best is not None and best[0] >= MIN_ACCEPTABLE_CONFIDENCE:
        confidence, product, detail = best
        # 3) LLM-verify would run here if OPENAI_API_KEY were set.
        return MatchDecision(product.id, "fuzzy", confidence, detail)

    return MatchDecision(
        None, "none", best[0] if best else 0.0,
        f"below threshold; best={best[2] if best else 'n/a'}",
    )


def _norm_text(s: str | None) -> str:
    if not s:
        return ""
    return " ".join(s.lower().split())


def _unit_compatibility_note(
    offer: NormalizedOffer, product: Product
) -> Literal["compatible", "incompatible", "unknown"]:
    """Compare normalized unit/quantity between offer and master product."""
    if offer.unit_base is None or product.unit_base is None:
        return "unknown"
    if offer.unit_base != product.unit_base:
        return "incompatible"
    if offer.quantity_base is None or product.quantity_base is None:
        return "unknown"
    q_offer = float(offer.quantity_base) if isinstance(offer.quantity_base, Decimal) else offer.quantity_base
    q_prod = float(product.quantity_base) if isinstance(product.quantity_base, Decimal) else product.quantity_base
    if q_prod == 0:
        return "unknown"
    diff = abs(q_offer - q_prod) / q_prod
    return "compatible" if diff <= UNIT_TOLERANCE_PCT else "incompatible"
