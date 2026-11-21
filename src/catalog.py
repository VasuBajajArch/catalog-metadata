from pathlib import Path

import pandas as pd
from jinja2 import Environment, FileSystemLoader, select_autoescape


REQUIRED_COLUMNS = {
    "database",
    "schema",
    "table_name",
    "number_of_rows",
    "primary_key",
    "columns",
    "column_types",
    "metadata",
    "generated_at",
    "owner",
    "table_type",
    "data_size_mb",
}


def load_catalog(csv_path):
    """Load and validate a table catalog CSV."""
    catalog = pd.read_csv(csv_path)
    missing_columns = REQUIRED_COLUMNS - set(catalog.columns)
    if missing_columns:
        raise ValueError(
            "Catalog is missing required columns: "
            + ", ".join(sorted(missing_columns))
        )
    return catalog


def filter_catalog(
    catalog,
    database="All",
    schema="All",
    owner="All",
    table_types=None,
    size_limit=None,
    row_limit=None,
    order_by="A \u2192 Z",
):
    """Apply catalog filters and deterministic table-name sorting."""
    filtered = catalog.copy()

    if database != "All":
        filtered = filtered[filtered["database"] == database]
    if schema != "All":
        filtered = filtered[filtered["schema"] == schema]
    if owner != "All":
        filtered = filtered[filtered["owner"] == owner]
    if table_types:
        filtered = filtered[filtered["table_type"].isin(table_types)]
    if size_limit is not None:
        filtered = filtered[filtered["data_size_mb"] <= size_limit]
    if row_limit is not None:
        filtered = filtered[filtered["number_of_rows"] <= row_limit]

    return filtered.sort_values(
        "table_name",
        ascending=(order_by == "A \u2192 Z"),
    )


def summarize_catalog(catalog):
    """Build summary values for the catalog metrics template."""
    total_rows = int(catalog["number_of_rows"].sum())
    total_size_mb = float(catalog["data_size_mb"].sum())
    return {
        "table_count": len(catalog),
        "view_count": int(catalog["table_type"].eq("VIEW").sum()),
        "materialized_count": int(
            catalog["table_type"].eq("MATERIALIZED VIEW").sum()
        ),
        "row_label": format_row_label(total_rows),
        "size_label": format_size_label(total_size_mb),
    }


def format_row_label(number_of_rows):
    """Format a row count for the summary metric cards."""
    if number_of_rows >= 1_000_000:
        return f"{number_of_rows / 1_000_000:.2f}M"
    if number_of_rows >= 1_000:
        return f"{number_of_rows:,}"
    return str(number_of_rows)


def format_size_label(size_mb):
    """Format catalog size in MB or GB."""
    if size_mb >= 1024:
        return f"{size_mb / 1024:.2f} GB"
    return f"{size_mb:.2f} MB"


def format_card_row_count(number_of_rows):
    """Format row counts for the compact table cards."""
    if number_of_rows >= 1000:
        return f"{number_of_rows / 1000:.1f}K"
    return str(number_of_rows)


def format_card_size(size_mb):
    """Format card size labels, switching to GB for large values."""
    if size_mb >= 1024:
        return f"{size_mb / 1024:.2f} GB"
    return f"{size_mb:.2f} MB"


def get_table_type_style(table_type):
    """Map a table type to its card and badge CSS classes."""
    normalized = str(table_type).strip().upper()
    if normalized == "VIEW":
        return "card-view", "badge-view", "VIEW"
    if normalized == "MATERIALIZED VIEW":
        return "card-materialized-view", "badge-materialized-view", "MATERIALIZED VIEW"
    return "card-base-table", "badge-base-table", "BASE TABLE"


def build_table_card_context(table_row):
    """Convert a catalog row into display values for the card template."""
    card_type_class, badge_class, table_type = get_table_type_style(
        table_row["table_type"]
    )
    return {
        "card_type_class": card_type_class,
        "table_name": str(table_row["table_name"]).upper(),
        "database": str(table_row["database"]).upper(),
        "schema": str(table_row["schema"]).upper(),
        "row_display": format_card_row_count(int(table_row["number_of_rows"])),
        "size_display": format_card_size(float(table_row["data_size_mb"])),
        "column_count": len(str(table_row["columns"]).split(",")),
        "badge_class": badge_class,
        "table_type": table_type,
        "owner": str(table_row["owner"]),
        "primary_key": str(table_row["primary_key"]),
        "created": str(table_row["generated_at"])[:10],
    }


def create_template_environment(base_directory):
    """Create a Jinja environment rooted in the assets directory."""
    templates_directory = Path(base_directory) / "templates"
    return Environment(
        loader=FileSystemLoader(str(templates_directory)),
        autoescape=select_autoescape(["html"]),
    )
