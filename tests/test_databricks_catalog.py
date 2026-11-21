"""Unit tests for Databricks API and metadata helpers."""

# Test names serve as their documentation; test doubles intentionally expose
# only the subset of the production interface each test needs.
# pylint: disable=missing-function-docstring,too-few-public-methods

import unittest
from unittest.mock import patch

from src.databricks_catalog import (
    DatabricksApiError,
    DatabricksCatalogConfigurationError,
    connect_to_sql_warehouse,
    ensure_sql_warehouse_running,
    fetch_dataframe,
    get_user_access_token,
    list_catalogs,
    list_column_metadata,
    list_schemas,
    list_sql_warehouses,
    list_table_metadata,
    quote_identifier,
)


class FakeCursor:
    """Minimal cursor test double that captures SQL queries."""

    def __init__(self, columns=(), rows=()):
        self.description = [(column,) for column in columns]
        self.rows = rows
        self.query = None
        self.parameters = None

    def execute(self, query, parameters=()):
        self.query = query
        self.parameters = parameters

    def fetchall(self):
        return self.rows


class FakeResponse:
    """Minimal response test double for workspace API calls."""

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.ok = status_code < 400

    def json(self):
        return self.payload


class TestDatabricksCatalog(unittest.TestCase):
    """Tests for workspace API access and metadata queries."""

    def test_user_token_header_lookup_is_case_insensitive(self):
        self.assertEqual(
            get_user_access_token(
                {"x-forwarded-access-token": "user-token"}
            ),
            "user-token",
        )
        self.assertIsNone(get_user_access_token({"other-header": "value"}))

    def test_quote_identifier_escapes_backticks(self):
        self.assertEqual(quote_identifier("sales`west"), "`sales``west`")

    def test_quote_identifier_rejects_empty_identifiers(self):
        with self.assertRaises(ValueError):
            quote_identifier("")

    def test_list_catalogs_sorts_results(self):
        cursor = FakeCursor(rows=[("zeta",), ("alpha",)])

        self.assertEqual(list_catalogs(cursor), ["alpha", "zeta"])
        self.assertEqual(cursor.query, "SHOW CATALOGS")

    def test_list_schemas_quotes_catalog_identifier(self):
        cursor = FakeCursor(
            columns=("schema_name",),
            rows=[("analytics",), ("sales",)],
        )

        schemas = list_schemas(cursor, "catalog`west")

        self.assertEqual(schemas, ["analytics", "sales"])
        self.assertIn(
            "`catalog``west`.information_schema.schemata",
            cursor.query,
        )

    def test_list_table_metadata_binds_selected_schema(self):
        cursor = FakeCursor(
            columns=("table_name", "table_type", "table_owner"),
            rows=[("orders", "MANAGED", "analyst")],
        )

        tables = list_table_metadata(cursor, "analytics", "sales")

        self.assertEqual(tables.iloc[0]["table_owner"], "analyst")
        self.assertEqual(cursor.parameters, ("sales",))
        self.assertIn(
            "`analytics`.information_schema.tables",
            cursor.query,
        )

    def test_selected_table_names_are_bound_as_parameters(self):
        cursor = FakeCursor(
            columns=("table_name", "column_name"),
            rows=[("orders", "id")],
        )
        selected_names = ["orders", "weird'name"]

        frame = list_column_metadata(
            cursor,
            "analytics",
            "public",
            selected_names,
        )

        self.assertEqual(frame["column_name"].tolist(), ["id"])
        self.assertEqual(cursor.parameters, ("public", "orders", "weird'name"))
        self.assertIn(
            "LOWER(table_name) IN (LOWER(?), LOWER(?))",
            cursor.query,
        )
        self.assertIn("LOWER(table_schema) = LOWER(?)", cursor.query)
        self.assertNotIn("weird'name", cursor.query)

    def test_fetch_dataframe_normalizes_column_names(self):
        cursor = FakeCursor(columns=("TABLE_NAME",), rows=[("orders",)])

        frame = fetch_dataframe(cursor, "SELECT table_name")

        self.assertEqual(frame.columns.tolist(), ["table_name"])
        self.assertEqual(frame.iloc[0]["table_name"], "orders")

    @patch("src.databricks_catalog.requests.request")
    def test_list_sql_warehouses_includes_all_pages_and_sorts(self, request):
        request.side_effect = [
            FakeResponse(
                {
                    "warehouses": [
                        {"id": "z-id", "name": "Zulu", "state": "RUNNING"}
                    ],
                    "next_page_token": "next",
                }
            ),
            FakeResponse(
                {
                    "warehouses": [
                        {"id": "a-id", "name": "Alpha", "state": "STOPPED"}
                    ]
                }
            ),
        ]

        warehouses = list_sql_warehouses("user-token", "workspace.example")

        self.assertEqual(
            [warehouse["id"] for warehouse in warehouses],
            ["a-id", "z-id"],
        )
        self.assertEqual(request.call_count, 2)
        first_call = request.call_args_list[0]
        self.assertEqual(first_call.args[:2], (
            "GET",
            "https://workspace.example/api/2.0/sql/warehouses",
        ))
        self.assertEqual(
            first_call.kwargs["headers"]["Authorization"],
            "Bearer user-token",
        )
        self.assertEqual(
            request.call_args_list[1].kwargs["params"]["page_token"],
            "next",
        )

    def test_list_sql_warehouses_requires_user_authorization(self):
        with self.assertRaises(DatabricksCatalogConfigurationError):
            list_sql_warehouses("", "workspace.example")

    @patch("src.databricks_catalog.sql.connect")
    def test_connect_to_sql_warehouse_uses_workspace_host_and_user_token(
        self,
        connect,
    ):
        connect_to_sql_warehouse(
            "user-token",
            "warehouse-id",
            "https://workspace.example",
        )

        connect.assert_called_once_with(
            server_hostname="workspace.example",
            http_path="/sql/1.0/warehouses/warehouse-id",
            access_token="user-token",
        )

    @patch("src.databricks_catalog.requests.request")
    def test_start_stopped_warehouse_then_wait_until_running(self, request):
        request.side_effect = [
            FakeResponse({"state": "STOPPED"}),
            FakeResponse({}),
            FakeResponse({"state": "RUNNING"}),
        ]

        with patch("src.databricks_catalog.time.sleep"):
            state = ensure_sql_warehouse_running(
                "user-token",
                "https://workspace.example",
                "warehouse/one",
                poll_interval_seconds=0,
            )

        self.assertEqual(state, "RUNNING")
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            ["GET", "POST", "GET"],
        )
        self.assertEqual(
            request.call_args_list[1].args[1],
            "https://workspace.example/api/2.0/sql/warehouses/warehouse%2Fone/start",
        )

    @patch("src.databricks_catalog.requests.request")
    def test_running_warehouse_is_not_restarted(self, request):
        request.return_value = FakeResponse({"state": "RUNNING"})

        state = ensure_sql_warehouse_running(
            "user-token",
            "workspace.example",
            "warehouse-id",
        )

        self.assertEqual(state, "RUNNING")
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0], "GET")

    @patch("src.databricks_catalog.requests.request")
    def test_stopping_warehouse_waits_then_starts_once(self, request):
        request.side_effect = [
            FakeResponse({"state": "STOPPING"}),
            FakeResponse({"state": "STOPPED"}),
            FakeResponse({}),
            FakeResponse({"state": "STOPPED"}),
            FakeResponse({"state": "STARTING"}),
            FakeResponse({"state": "RUNNING"}),
        ]

        with patch("src.databricks_catalog.time.sleep"):
            state = ensure_sql_warehouse_running(
                "user-token",
                "workspace.example",
                "warehouse-id",
                poll_interval_seconds=0,
            )

        self.assertEqual(state, "RUNNING")
        self.assertEqual(
            [call.args[0] for call in request.call_args_list],
            ["GET", "GET", "POST", "GET", "GET", "GET"],
        )

    @patch("src.databricks_catalog.requests.request")
    def test_forbidden_warehouse_list_reports_required_scope(self, request):
        request.return_value = FakeResponse(
            {"error_code": "PERMISSION_DENIED"},
            status_code=403,
        )

        with self.assertRaisesRegex(
            DatabricksApiError,
            "GET /api/2.0/sql/warehouses returned HTTP 403.*sql.*consent"
            ".*DATABRICKS_HOST.*same workspace.*permission",
        ):
            list_sql_warehouses("user-token", "workspace.example")

    def test_workspace_host_must_use_https(self):
        with self.assertRaises(DatabricksCatalogConfigurationError):
            list_sql_warehouses("user-token", "http://workspace.example")


if __name__ == "__main__":
    unittest.main()
