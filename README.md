# Price Matcher Demo

Сопоставление товарных позиций из прайсов разных поставщиков и агрегация лучших цен для HoReCa.

> Это **демонстрационный проект**, реализующий ядро системы: загрузку прайсов, распознавание структуры, нормализацию фасовок и каскадный matching. Не production-ready сервис — это техническое демо подхода.

## Что внутри

```
Прайс (xlsx/csv)  →  Парсер  →  Schema Detection  →  Normalizer  →  Matcher  →  PostgreSQL  →  Best-Price  →  Экспорт
```

| Модуль | Назначение |
|---|---|
| `parsers.py` | Универсальный парсер `.xlsx` / `.xls` / `.csv` (pandas) |
| `schema_detector.py` | Сопоставление произвольных заголовков ("Цена", "price_rub", "price") с каноническими полями. Синонимы (RU+EN) + fuzzy-fallback |
| `unit_normalizer.py` | Нормализация фасовок: `"1 кг"` / `"1000г"` / `"уп. 24 шт по 100 г"` → `(quantity_base=2400, unit_base="g")` |
| `matcher.py` | **Каскадный matching**: точные ключи (SKU+бренд) → fuzzy (rapidfuzz) → заглушка LLM |
| `ingest.py` | Загрузка прайса в БД, кеширование схемы поставщика |
| `best_price.py` | Агрегация: минимальная цена по каждому товару + история изменений |
| `exporter.py` | Экспорт сводной таблицы лучших цен в `.xlsx` / `.csv` |
| `pipeline.py` | Оркестратор end-to-end пайплайна |
| `cli.py` | CLI на typer |

## Архитектура matching-движка (ядро проекта)

Подход — **каскад**, а не «всё на LLM»:

```
1. EXACT  — SKU + бренд совпали точно     → мгновенно, бесплатно
2. FUZZY  — fuzzy name + brand bonus      → кандидатный список
            + проверка совместимости единиц (1кг ≠ 1л)
3. LLM    — заглушка (требует OPENAI_API_KEY)
            → подтверждение спорных fuzzy-совпадений
```

**Почему так:** каскад пропускает через LLM только ~5–10% неоднозначных случаев — это и быстрее, и в 10–20 раз дешевле, чем «отправить всё в GPT». Каждое решение фиксируется с `confidence` и `method` (аудит-трейл для проверки человеком).

## Стек

- **Python 3.13**, FastAPI (точка расширения для API-слоя)
- **PostgreSQL 16** через Docker, SQLAlchemy 2.0
- **pandas**, **openpyxl** для парсинга
- **rapidfuzz** для fuzzy-matching
- **typer** + **rich** для CLI
- (опционально) **openai** SDK для LLM-каскада

## Быстрый старт

### 1. Клонировать и установить зависимости

```bash
git clone <your-repo-url>
cd price-matcher-demo
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -e .
```

### 2. Поднять PostgreSQL через Docker

```bash
docker compose up -d
```

Создать `.env` из примера:

```bash
cp .env.example .env
```

### 3. Создать таблицы и сгенерировать тестовые данные

```bash
price-matcher init-db
python scripts/generate_sample_data.py
```

### 4. Запустить pipeline

```bash
price-matcher run \
  --supplier "АльфаФуд"     --file data/supplier_alpha.xlsx \
  --supplier "Бета-Трейд"   --file data/supplier_beta.xlsx \
  --supplier "Гамма-Опт"    --file data/supplier_gamma.xlsx \
  --master  data/master_products.csv \
  --out     output/best_prices.xlsx
```

В `output/best_prices.xlsx` — сводная таблица лучших цен по каждому товару.

## Тесты

```bash
pytest
```

Покрыты ключевые модули: `unit_normalizer` (16 кейсов на разные формы записи фасовок), `schema_detector` (RU/EN заголовки, fuzzy), `matcher` (точный/fuzzy/no-match/unit-incompatibility).

## Что намеренно НЕ входит в demo

Эти части заложены в архитектуру, но не реализованы в коде, чтобы сохранить demo компактным:

| Компонент | Статус |
|---|---|
| PDF-парсинг (`pdfplumber` + Vision fallback) | не реализован |
| LLM-верификатор (GPT-4o-mini) | заглушка в `matcher.py`, место отмечено |
| Эмбеддинги (sentence-transformers) | не реализован |
| Google Sheets sync | не реализован (для MVP используется экспорт в xlsx) |
| Веб-интерфейс | фаза 2 |
| FastAPI endpoints | не реализован (FastAPI в deps как точка расширения, но `run_pipeline` синхронный и держит сессию → нужен слой фоновых задач прежде чем поднимать HTTP) |
| Celery / фоновые задачи | не реализован |
| Alembic-миграции | не реализован (используется `create_all`; для добавления колонок к существующей БД — нужны миграции) |

## Best-price: почему по цене за единицу, а не по сырой цене

«Лучшая цена» — это `min(price_per_base_unit)`, а **не** `min(price)`.

Сравнивать сырые цены через разные фасовки математически неверно:
- Поставщик А: «Сахар» 1 кг за 52 ₽
- Поставщик Б: «Сахар» уп. 5 кг за 245 ₽ → **49 ₽/кг** ← дешевле

При `min(price)` «лучшим» стал бы А (52 < 245). При `min(price_per_base_unit)` правильно
выбирается Б (0.049 ₽/г < 0.052 ₽/г). Это и проверяется в `output/best_prices.xlsx`.

Офферы с нераспознанной фасовкой (`quantity_base IS NULL`) исключаются из выбора
и логируются — оператор видит, какие позиции нужно обогатить данными об упаковке.

## Известные ограничения (технический долг)

Зафиксировано по результатам код-ревью. Не критично для demo, но обязательно
к правке до production:

- Авто-создание master-продуктов при отсутствии SKU у поставщика может
  склеить разные товары, если у двух поставщиков одинаковый SKU
- `_load_master_products` не валидирует пустые/NaN-значения в CSV
- Нет repository-слоя → будет больно добавлять embeddings/векторный поиск
- Каскад matcher монолитный; нет top-K кандидатов и полосы «на ревью»
- Нет entity для ревью-очереди (`check_status` объявлен, но нигде не пишется)
- Нет нормализации текста (ё→е, пунктуация, аббревиатуры) в matcher

## Схема данных (PostgreSQL)

```
suppliers          — поставщики + кеш схемы их прайса
products           — мастер-номенклатура (эталон)
supplier_offers    — строки прайсов поставщиков, линкованные к products
                     + method/confidence/detail (аудит matching)
price_history      — append-only история изменения лучшей цены
```

## Лицензия

MIT
