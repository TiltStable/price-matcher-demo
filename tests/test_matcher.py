"""Tests for matcher.py — the cascade matching engine."""

from __future__ import annotations

from price_matcher.matcher import match_offer
from price_matcher.schemas import NormalizedOffer


def _make_offer(**overrides) -> NormalizedOffer:
    defaults = dict(
        supplier_name="X",
        supplier_sku=None,
        raw_name="Мука пшеничная в/с",
        raw_brand="Мельник",
        raw_packaging="1 кг",
        price=65.0,
        stock=None,
        quantity_base=1000.0,
        unit_base="g",
    )
    defaults.update(overrides)
    return NormalizedOffer(**defaults)


class _FakeProduct:
    """Minimal stand-in for a Product ORM object to keep the test DB-free."""
    def __init__(self, pid, sku, name, brand=None, quantity_base=None, unit_base=None):
        self.id = pid
        self.sku = sku
        self.name = name
        self.brand = brand
        self.quantity_base = quantity_base
        self.unit_base = unit_base


def test_exact_match_by_sku():
    p = _FakeProduct(1, "AF-1001", "Мука пшеничная в/с", "Мельник", 1000, "g")
    offer = _make_offer(supplier_sku="AF-1001")
    d = match_offer(offer, [p])
    assert d.is_linked()
    assert d.method == "exact"
    assert d.confidence == 1.0


def test_exact_match_is_case_insensitive():
    p = _FakeProduct(1, "AF-1001", "irrelevant")
    offer = _make_offer(supplier_sku="af-1001")
    d = match_offer(offer, [p])
    assert d.method == "exact"


def test_fuzzy_match_when_sku_absent():
    p = _FakeProduct(1, "MASTER-1", "Мука пшеничная в/с", "Мельник", 1000, "g")
    offer = _make_offer(supplier_sku=None)
    d = match_offer(offer, [p])
    assert d.is_linked()
    assert d.method == "fuzzy"
    assert d.confidence >= 0.6


def test_no_match_when_name_too_different():
    p = _FakeProduct(1, "MASTER-1", "Совершенно другой товар", "X", 100, "g")
    offer = _make_offer(supplier_sku=None, raw_name="Мука пшеничная в/с")
    d = match_offer(offer, [p])
    assert not d.is_linked()
    assert d.method == "none"


def test_unit_incompatibility_lowers_confidence():
    # Same name, but product is liquid — incompatible with a solid offer.
    p = _FakeProduct(1, "MASTER-1", "Мука пшеничная в/с", "Мельник", 1000, "ml")
    offer = _make_offer(unit_base="g", quantity_base=1000)
    d = match_offer(offer, [p])
    # Still matches on name, but at lower confidence due to unit penalty.
    assert d.is_linked()
    assert "unit:incompatible" in (d.detail or "")


def test_confidence_never_exceeds_one():
    """Regression: brand bonus + unit bonus must stay capped at 1.0.

    The DB has a CHECK constraint match_confidence BETWEEN 0 AND 1, so any
    overflow would crash the insert.
    """
    # Name exact (100) + brand match (+10) + unit compatible (+5) → would
    # naively be 1.15; must be capped to 1.0.
    p = _FakeProduct(1, "M-1", "Мука пшеничная в/с", "Мельник", 1000, "g")
    offer = _make_offer(supplier_sku=None)  # force fuzzy path
    d = match_offer(offer, [p])
    assert d.is_linked()
    assert d.confidence <= 1.0
    assert d.confidence >= 0.0


def test_empty_candidates_returns_none():
    d = match_offer(_make_offer(), [])
    assert not d.is_linked()
    assert d.method == "none"
