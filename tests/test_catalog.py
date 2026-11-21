import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.catalog import (
    build_table_card_context,
    filter_catalog,
    format_card_row_count,
    format_card_size,
    format_row_label,
    format_size_label,
    get_table_type_style,
    load_catalog,
    summarize_catalog,
)


def make_catalog():
    return pd.DataFrame(
        [
            {
                "database": "analytics",
                "schema": "public",
                "table_name": "orders",
                "number_of_rows": 1500,
                "primary_key": "order_id",
                "columns": "order_id, customer_id",
                "column_types": "order_id: int64",
                "metadata": "Orders",
                "generated_at": "2026-11-21T13:00:00+00:00",
                "owner": "analyst",
                "table_type": "BASE TABLE",
                "data_size_mb": 2.5,
            },
            {
                "database": "analytics",
                "schema": "reporting",
                "table_name": "customer_view",
                "number_of_rows": 2500000,
                "primary_key": "customer_id",
                "columns": "customer_id, name",
                "column_types": "customer_id: int64",
                "metadata": "Customer view",
                "generated_at": "2026-11-21T14:00:00+00:00",
                "owner": "reporter",
                "table_type": "VIEW",
                "data_size_mb": 2048.0,
            },
            {
                "database": "warehouse",
                "schema": "reporting",
                "table_name": "daily_sales",
                "number_of_rows": 500,
                "primary_key": "sale_id",
                "columns": "sale_id, amount",
                "column_types": "sale_id: int64",
                "metadata": "Daily sales",
                "generated_at": "2026-11-21T15:00:00+00:00",
                "owner": "analyst",
                "table_type": "MATERIALIZED VIEW",
                "data_size_mb": 1.0,
            },
        ]
    )


class TestLoadCatalog(unittest.TestCase):
    def test_load_catalog_reads_valid_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "catalog.csv"
            make_catalog().to_csv(csv_path, index=False)
            loaded = load_catalog(csv_path)
        self.assertEqual(len(loaded), 3)

    def test_load_catalog_rejects_missing_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            csv_path = Path(directory) / "catalog.csv"
            pd.DataFrame({"table_name": ["orders"]}).to_csv(
                csv_path,
                index=False,
            )
            with self.assertRaises(ValueError):
                load_catalog(csv_path)


class TestFilterCatalog(unittest.TestCase):
    def test_filter_catalog_combines_database_schema_and_owner(self):
        filtered = filter_catalog(
            make_catalog(),
            database="analytics",
            schema="public",
            owner="analyst",
        )
        self.assertEqual(filtered["table_name"].tolist(), ["orders"])

    def test_filter_catalog_supports_multiple_table_types(self):
        filtered = filter_catalog(
            make_catalog(),
            table_types=["VIEW", "MATERIALIZED VIEW"],
        )
        self.assertEqual(
            set(filtered["table_type"]),
            {"VIEW", "MATERIALIZED VIEW"},
        )

    def test_filter_catalog_applies_size_and_row_limits(self):
        filtered = filter_catalog(
            make_catalog(),
            size_limit=2.0,
            row_limit=1000,
        )
        self.assertEqual(filtered["table_name"].tolist(), ["daily_sales"])

    def test_filter_catalog_sorts_descending(self):
        filtered = filter_catalog(make_catalog(), order_by="Z \u2192 A")
        self.assertEqual(
            filtered["table_name"].tolist(),
            ["orders", "daily_sales", "customer_view"],
        )


class TestFormatting(unittest.TestCase):
    def test_format_row_label_uses_millions(self):
        self.assertEqual(format_row_label(2_500_000), "2.50M")

    def test_format_card_row_count_uses_thousands(self):
        self.assertEqual(format_card_row_count(1500), "1.5K")

    def test_format_size_label_uses_gigabytes(self):
        self.assertEqual(format_size_label(2048), "2.00 GB")

    def test_format_card_size_uses_megabytes(self):
        self.assertEqual(format_card_size(2.5), "2.50 MB")


class TestTableTypeStyle(unittest.TestCase):
    def test_base_table_style(self):
        self.assertEqual(
            get_table_type_style("BASE TABLE"),
            ("card-base-table", "badge-base-table", "BASE TABLE"),
        )

    def test_view_style(self):
        self.assertEqual(
            get_table_type_style("VIEW"),
            ("card-view", "badge-view", "VIEW"),
        )

    def test_materialized_view_style(self):
        self.assertEqual(
            get_table_type_style("MATERIALIZED VIEW"),
            (
                "card-materialized-view",
                "badge-materialized-view",
                "MATERIALIZED VIEW",
            ),
        )


class TestSummaryAndCard(unittest.TestCase):
    def test_summarize_catalog(self):
        summary = summarize_catalog(make_catalog())
        self.assertEqual(summary["table_count"], 3)
        self.assertEqual(summary["view_count"], 1)
        self.assertEqual(summary["materialized_count"], 1)

    def test_build_table_card_context(self):
        context = build_table_card_context(make_catalog().iloc[1])
        self.assertEqual(context["table_name"], "CUSTOMER_VIEW")
        self.assertEqual(context["row_display"], "2500.0K")
        self.assertEqual(context["table_type"], "VIEW")


if __name__ == "__main__":
    unittest.main()
