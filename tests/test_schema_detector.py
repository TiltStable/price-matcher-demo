"""Tests for schema_detector.py."""

from __future__ import annotations

from price_matcher.schemas import ParsedRow
from price_matcher.schema_detector import detect_schema


def test_detects_russian_headers():
    rows = [
        ParsedRow(raw={
            "Артикул": "AF-1", "Наименование": "Мука", "Цена": "65",
            "Фасовка": "1 кг", "Наличие": "да",
        })
    ]
    m = detect_schema(rows)
    assert m.mapping["supplier_sku"] == "Артикул"
    assert m.mapping["name"] == "Наименование"
    assert m.mapping["price"] == "Цена"
    assert m.mapping["packaging"] == "Фасовка"
    assert m.mapping["stock"] == "Наличие"
    assert m.confidence > 0.5


def test_detects_english_headers():
    rows = [ParsedRow(raw={"sku": "1", "Product": "Flour", "price_rub": "10"})]
    m = detect_schema(rows)
    assert m.mapping["supplier_sku"] == "sku"
    assert m.mapping["name"] == "Product"
    assert m.mapping["price"] == "price_rub"


def test_fuzzy_match_for_unusual_header():
    # "Товарный знак" is not in synonyms — should fuzzy-match "brand".
    rows = [ParsedRow(raw={"товарный знак": "X", "name": "Y", "price": "1"})]
    m = detect_schema(rows)
    assert "name" in m.mapping
    assert "price" in m.mapping


def test_get_returns_value_from_correct_column():
    rows = [ParsedRow(raw={"Наименование": "Сахар", "Цена": "52"})]
    m = detect_schema(rows)
    assert m.get(rows[0], "name") == "Сахар"
    assert m.get(rows[0], "price") == "52"
    # Field that wasn't detected → None
    assert m.get(rows[0], "stock") is None


def test_empty_rows_returns_empty_mapping():
    assert detect_schema([]).mapping == {}
