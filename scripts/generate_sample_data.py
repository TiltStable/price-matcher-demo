"""Generate sample price lists from 3 fictitious suppliers.

Each supplier uses different column names and structure to exercise the
schema detector and matching engine. Run once:

    python scripts/generate_sample_data.py

Outputs go to data/.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def build_supplier_alpha() -> pd.DataFrame:
    """Supplier 'АльфаФуд': Russian headers, units in 'кг'/'л'."""
    return pd.DataFrame(
        [
            {"Артикул": "AF-1001", "Наименование": "Мука пшеничная в/с", "Бренд": "Мельник",
             "Фасовка": "1 кг", "Цена": "65.00", "Наличие": "много"},
            {"Артикул": "AF-1002", "Наименование": "Сахар-песок", "Бренд": "Кубань",
             "Фасовка": "1 кг", "Цена": "52.00", "Наличие": "много"},
            {"Артикул": "AF-1003", "Наименование": "Масло подсолнечное рафинированное",
             "Бренд": "Злато", "Фасовка": "1 л", "Цена": "115.00", "Наличие": "мало"},
            {"Артикул": "AF-1004", "Наименование": "Соль поваренная пищевая", "Бренд": "Солика",
             "Фасовка": "1 кг", "Цена": "18.00", "Наличие": "много"},
            {"Артикул": "AF-1005", "Наименование": "Рис круглозерный", "Бренд": "Увелка",
             "Фасовка": "1 кг", "Цена": "98.00", "Наличие": "много"},
            {"Артикул": "AF-1006", "Наименование": "Паста томатная 25%", "Бренд": "Помидорка",
             "Фасовка": "упаковка 24 шт по 100 г", "Цена": "1 200.00", "Наличие": "мало"},
            {"Артикул": "AF-1007", "Наименование": "Кофе зерновой Арабика", "Бренд": "Бариста",
             "Фасовка": "1 кг", "Цена": "1 450.00", "Наличие": "мало"},
        ]
    )


def build_supplier_beta() -> pd.DataFrame:
    """Supplier 'Бета-Трейд': English/mixed headers, grams, multiplier syntax."""
    return pd.DataFrame(
        [
            {"sku": "BT-2001", "Product": "Мука высшего сорта", "Brand": "Мельник",
             "weight_g": 1000, "price_rub": 68.50, "stock_qty": 50},
            {"sku": "BT-2002", "Product": "Сахар белый", "Brand": "Кубань",
             "weight_g": 1000, "price_rub": 49.00, "stock_qty": 80},
            {"sku": "BT-2003", "Product": "Масло растительное рафинированное", "Brand": "Ideal",
             "weight_g": 900, "price_rub": 119.00, "stock_qty": 30},
            {"sku": "BT-2004", "Product": "Соль пищевая", "Brand": "Солика",
             "weight_g": 1000, "price_rub": 22.00, "stock_qty": 100},
            {"sku": "BT-2005", "Product": "Рис круглый", "Brand": "Увелка",
             "weight_g": 900, "price_rub": 95.00, "stock_qty": 60},
            {"sku": "BT-2006", "Product": "Кофе в зернах арабика", "Brand": "Бариста",
             "weight_g": 1000, "price_rub": 1390.00, "stock_qty": 15},
            {"sku": "BT-2007", "Product": "Какао-порошок", "Brand": "Золотой ярлык",
             "weight_g": 100, "price_rub": 145.00, "stock_qty": 40},
        ]
    )


def build_supplier_gamma() -> pd.DataFrame:
    """Supplier 'Гамма-Опт': terse headers, 'уп.' notation, no SKU column."""
    return pd.DataFrame(
        [
            {"Товар": "Мука пшеничная высший сорт", "Производитель": "Мельник",
             "Объем": "уп. 2 кг", "Цена руб": "120.00", "Остаток": "в наличии"},
            {"Товар": "Сахар песок", "Производитель": "Кубань",
             "Объем": "уп. 5 кг", "Цена руб": "245.00", "Остаток": "в наличии"},
            {"Товар": "Масло подсолнечное", "Производитель": "Злато",
             "Объем": "5 л", "Цена руб": "560.00", "Остаток": "мало"},
            {"Товар": "Соль", "Производитель": "Солика",
             "Объем": "уп. 10 шт по 1 кг", "Цена руб": "165.00", "Остаток": "много"},
            {"Товар": "Рис круглозерный", "Производитель": "Увелка",
             "Объем": "уп. 2 кг", "Цена руб": "189.00", "Остаток": "много"},
            {"Товар": "Томатная паста 25%", "Производитель": "Помидорка",
             "Объем": "уп. 12 шт по 100 г", "Цена руб": "620.00", "Остаток": "мало"},
            {"Товар": "Чай черный байховый", "Производитель": "Принцесса",
             "Объем": "уп. 100 шт по 2 г", "Цена руб": "380.00", "Остаток": "много"},
        ]
    )


def build_master_csv() -> pd.DataFrame:
    """Seed master products — the canonical catalog to match against."""
    return pd.DataFrame(
        [
            {"sku": "MASTER-001", "name": "Мука пшеничная высший сорт", "brand": "Мельник",
             "quantity_base": 1000, "unit_base": "g", "packaging_raw": "1 кг"},
            {"sku": "MASTER-002", "name": "Сахар белый", "brand": "Кубань",
             "quantity_base": 1000, "unit_base": "g", "packaging_raw": "1 кг"},
            {"sku": "MASTER-003", "name": "Масло подсолнечное рафинированное", "brand": "Злато",
             "quantity_base": 1000, "unit_base": "ml", "packaging_raw": "1 л"},
            {"sku": "MASTER-004", "name": "Соль пищевая", "brand": "Солика",
             "quantity_base": 1000, "unit_base": "g", "packaging_raw": "1 кг"},
            {"sku": "MASTER-005", "name": "Рис круглозерный", "brand": "Увелка",
             "quantity_base": 1000, "unit_base": "g", "packaging_raw": "1 кг"},
            {"sku": "MASTER-006", "name": "Паста томатная 25%", "brand": "Помидорка",
             "quantity_base": 2400, "unit_base": "g", "packaging_raw": "уп. 24 шт по 100 г"},
            {"sku": "MASTER-007", "name": "Кофе зерновой Арабика", "brand": "Бариста",
             "quantity_base": 1000, "unit_base": "g", "packaging_raw": "1 кг"},
        ]
    )


def main() -> None:
    build_supplier_alpha().to_excel(DATA_DIR / "supplier_alpha.xlsx", index=False)
    build_supplier_beta().to_excel(DATA_DIR / "supplier_beta.xlsx", index=False)
    build_supplier_gamma().to_excel(DATA_DIR / "supplier_gamma.xlsx", index=False)
    build_master_csv().to_csv(DATA_DIR / "master_products.csv", index=False)
    print(f"Sample data written to {DATA_DIR}/")


if __name__ == "__main__":
    main()
