"""Tests for unit_normalizer.py — the trickiest piece of logic in the system."""

from __future__ import annotations

import pytest

from price_matcher.unit_normalizer import normalize_packaging


@pytest.mark.parametrize(
    "raw, expected_qty, expected_unit",
    [
        # Bare weight, kg → g
        ("1 кг", 1000, "g"),
        ("1кг", 1000, "g"),
        ("0,5 кг", 500, "g"),
        ("1000 г", 1000, "g"),
        ("500г", 500, "g"),
        # Bare volume, l → ml
        ("1 л", 1000, "ml"),
        ("0.5 литра", 500, "ml"),
        ("500 мл", 500, "ml"),
        # English
        ("1 kg", 1000, "g"),
        ("10 kg", 10000, "g"),
        ("2 L", 2000, "ml"),
        # Pieces
        ("упаковка 24 шт", 24, "pcs"),
        ("12 шт", 12, "pcs"),
        # Multipliers
        ("упаковка 24 шт по 100 г", 2400, "g"),
        ("5x200г", 1000, "g"),
        ("5х200 г", 1000, "g"),  # Russian х
        ("уп. 2 кг", 2000, "g"),
        ("уп. 12 шт по 100 г", 1200, "g"),
    ],
)
def test_normalize_known_shapes(raw, expected_qty, expected_unit):
    result = normalize_packaging(raw)
    assert result is not None, f"Expected parse for {raw!r}"
    assert result.unit_base == expected_unit, f"{raw!r}: unit"
    assert pytest.approx(result.quantity_base, rel=1e-3) == expected_qty, f"{raw!r}: qty"


def test_returns_none_on_garbage():
    assert normalize_packaging(None) is None
    assert normalize_packaging("") is None
    assert normalize_packaging("   ") is None


def test_returns_none_on_text_without_unit():
    # A bare number with no recognizable unit → None (no false guess).
    assert normalize_packaging("100") is None
