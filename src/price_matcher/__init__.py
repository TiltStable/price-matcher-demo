"""Price Matcher: supplier price-list ingestion and matching engine.

Pipeline:
    parse  →  detect schema  →  normalize  →  match  →  update best price  →  export
"""

__version__ = "0.1.0"
