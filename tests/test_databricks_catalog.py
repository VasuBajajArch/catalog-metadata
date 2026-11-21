import unittest

from src.databricks_catalog import (
    fetch_dataframe,
    get_user_access_token,
    list_catalogs,
    list_column_metadata,
    list_schemas,
    list_table_metadata,
    quote_identifier,
)


class FakeCursor:
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


class TestDatabricksCatalog(unittest.TestCase):
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
        self.assertIn("table_name IN (?, ?)", cursor.query)
        self.assertNotIn("weird'name", cursor.query)

    def test_fetch_dataframe_normalizes_column_names(self):
        cursor = FakeCursor(columns=("TABLE_NAME",), rows=[("orders",)])

        frame = fetch_dataframe(cursor, "SELECT table_name")

        self.assertEqual(frame.columns.tolist(), ["table_name"])
        self.assertEqual(frame.iloc[0]["table_name"], "orders")


if __name__ == "__main__":
    unittest.main()
