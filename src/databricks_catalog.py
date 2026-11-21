from urllib.parse import urlsplit

import pandas as pd


class DatabricksCatalogConfigurationError(ValueError):
    """Raised when a required Databricks app setting is unavailable."""


def get_user_access_token(headers):
    """Return the forwarded Databricks user token without storing it."""
    for name, value in headers.items():
        if name.lower() == "x-forwarded-access-token":
            return value
    return None


def connect_to_sql_warehouse(access_token, warehouse_id, workspace_host):
    """Connect to a Databricks SQL warehouse as the current user."""
    if not access_token:
        raise DatabricksCatalogConfigurationError(
            "Databricks user authorization is not available."
        )
    if not warehouse_id:
        raise DatabricksCatalogConfigurationError(
            "Configure a SQL warehouse resource for this Databricks app."
        )
    if not workspace_host:
        raise DatabricksCatalogConfigurationError(
            "The Databricks workspace host is not configured."
        )

    host = workspace_host.strip()
    if "://" not in host:
        host = f"https://{host}"
    parsed_host = urlsplit(host)
    if not parsed_host.hostname:
        raise DatabricksCatalogConfigurationError(
            "The Databricks workspace host is invalid."
        )

    from databricks import sql

    return sql.connect(
        server_hostname=parsed_host.hostname,
        http_path=f"/sql/1.0/warehouses/{warehouse_id}",
        access_token=access_token,
    )


def quote_identifier(identifier):
    """Quote a SQL identifier, escaping embedded backticks."""
    if not identifier:
        raise ValueError("SQL identifiers must not be empty.")
    return "`{}`".format(str(identifier).replace("`", "``"))


def fetch_dataframe(cursor, query, parameters=()):
    """Execute a parameterized query and return its rows as a DataFrame."""
    cursor.execute(query, parameters)
    if cursor.description is None:
        raise RuntimeError("The metadata query did not return a result set.")
    columns = [str(column[0]).lower() for column in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def list_catalogs(cursor):
    """List catalogs visible to the current user."""
    cursor.execute("SHOW CATALOGS")
    return sorted(str(row[0]) for row in cursor.fetchall())


def list_schemas(cursor, catalog):
    """List non-system schemas visible to the current user in a catalog."""
    catalog_name = quote_identifier(catalog)
    schemas = fetch_dataframe(
        cursor,
        f"""
        SELECT schema_name
        FROM {catalog_name}.information_schema.schemata
        WHERE LOWER(schema_name) <> 'information_schema'
        ORDER BY schema_name
        """,
    )
    return schemas["schema_name"].dropna().astype(str).tolist()


def list_table_metadata(cursor, catalog, schema):
    """Return visible table metadata for the selected schema."""
    catalog_name = quote_identifier(catalog)
    return fetch_dataframe(
        cursor,
        f"""
        SELECT table_name, table_type, table_owner, comment, created, last_altered
        FROM {catalog_name}.information_schema.tables
        WHERE table_schema = ?
        ORDER BY table_name
        """,
        (schema,),
    )


def list_column_metadata(cursor, catalog, schema, table_names=None):
    """Return column metadata for all or selected tables in a schema."""
    if table_names is not None and not table_names:
        return pd.DataFrame(
            columns=[
                "table_name",
                "column_name",
                "full_data_type",
                "is_nullable",
                "comment",
                "ordinal_position",
            ]
        )

    catalog_name = quote_identifier(catalog)
    query = f"""
        SELECT table_name, column_name, full_data_type, is_nullable, comment,
               ordinal_position
        FROM {catalog_name}.information_schema.columns
        WHERE table_schema = ?
    """
    parameters = [schema]
    if table_names is not None:
        placeholders = ", ".join("?" for _ in table_names)
        query += f" AND table_name IN ({placeholders})"
        parameters.extend(table_names)
    query += " ORDER BY table_name, ordinal_position"

    return fetch_dataframe(cursor, query, tuple(parameters))
