"""Command-line entry point.

Usage:
    price-matcher init-db
    price-matcher ingest --supplier "Поставщик А" --file data/supplier_a.xlsx
    price-matcher run --out output/best_prices.xlsx
    price-matcher run --supplier "Поставщик А" --file data/a.csv \\
                    --supplier "Поставщик Б" --file data/b.xlsx \\
                    --master data/master.csv --out output/best.xlsx
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from price_matcher.db import get_engine
from price_matcher.exporter import export_records
from price_matcher.models import Base

app = typer.Typer(help="Supplier price-list matcher for HoReCa.", add_completion=False)
console = Console()


@app.command()
def init_db() -> None:
    """Create all tables (drops nothing)."""
    Base.metadata.create_all(get_engine())
    console.print("[green]✓[/green] Tables created.")


@app.command()
def ingest(
    supplier: Annotated[str, typer.Option(help="Supplier name")],
    file: Annotated[Path, typer.Option(help="Path to the price-list file")],
) -> None:
    """Ingest a single price list into the DB."""
    from price_matcher.ingest import ingest_price_list
    from price_matcher.db import session_scope

    with session_scope() as session:
        rows, inserted, mapping_json = ingest_price_list(session, supplier, file)
    console.print(
        f"[green]✓[/green] {supplier}: read {rows} rows, inserted {inserted} offers."
    )
    console.print(f"  schema mapping: {mapping_json}")


@app.command()
def run(
    supplier: Annotated[
        list[str],
        typer.Option(help="(name) — repeatable. Pair with --file in order."),
    ] = [],
    file: Annotated[
        list[Path],
        typer.Option(help="path — repeatable. Pair with --supplier in order."),
    ] = [],
    master: Annotated[
        Path | None, typer.Option(help="Optional master-products CSV seed.")
    ] = None,
    out: Annotated[Path, typer.Option(help="Output file (.xlsx or .csv)")] = Path(
        "output/best_prices.xlsx"
    ),
) -> None:
    """Run the full pipeline and export the best-price snapshot."""
    if len(supplier) != len(file):
        console.print(
            f"[red]✗[/red] --supplier ({len(supplier)}) and --file ({len(file)}) "
            "counts must match and be paired in order."
        )
        raise typer.Exit(code=2)

    from price_matcher.pipeline import run_pipeline

    price_lists = list(zip(supplier, file))
    stats, records = run_pipeline(price_lists, master_csv=master)

    # Summary table.
    t = Table(title="Pipeline summary", show_header=False)
    t.add_column("Metric", style="cyan")
    t.add_column("Value", style="white")
    t.add_row("Suppliers processed", str(stats.suppliers))
    t.add_row("Offers loaded", str(stats.offers_loaded))
    t.add_row("Offers matched (existing products)", str(stats.offers_matched))
    t.add_row("Offers unmatched (new products created)", str(stats.offers_unmatched))
    console.print(t)

    out_path = export_records(records, out)
    console.print(f"[green]✓[/green] Exported {len(records)} rows → {out_path}")


if __name__ == "__main__":
    app()
