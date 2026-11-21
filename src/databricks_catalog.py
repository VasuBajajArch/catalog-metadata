import time
from urllib.parse import quote, urlsplit

import pandas as pd
import requests


class DatabricksCatalogConfigurationError(ValueError):
    """Raised when a required Databricks app setting is unavailable."""


class DatabricksApiError(RuntimeError):
    """Raised when a Databricks workspace API call fails."""


def _workspace_url(workspace_host, path):
    if not workspace_host:
        raise DatabricksCatalogConfigurationError(
            "The Databricks workspace host is not configured."
        )

    host = workspace_host.strip()
    if "://" not in host:
        host = f"https://{host}"
    parsed_host = urlsplit(host)
    if (
        parsed_host.scheme != "https"
        or not parsed_host.hostname
        or parsed_host.username
        or parsed_host.password
        or parsed_host.path not in ("", "/")
        or parsed_host.query
        or parsed_host.fragment
    ):
        raise DatabricksCatalogConfigurationError(
            "The Databricks workspace host is invalid."
        )
    return f"https://{parsed_host.netloc}{path}"


def _workspace_api_request(method, access_token, workspace_host, path, **kwargs):
    if not access_token:
        raise DatabricksCatalogConfigurationError(
            "Databricks user authorization is not available."
        )

    url = _workspace_url(workspace_host, path)
    try:
        response = requests.request(
            method,
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=(5, 20),
            **kwargs,
        )
    except requests.RequestException as error:
        raise DatabricksApiError(
            f"Could not reach the Databricks workspace API: {error}"
        ) from error

    if not response.ok:
        try:
            error_body = response.json()
        except ValueError:
            error_body = {}
        detail = None
        if isinstance(error_body, dict):
            detail = error_body.get("message") or error_body.get("error_code")
        message = (
            f"Databricks workspace API request {method} {path} returned "
            f"HTTP {response.status_code}"
        )
        if detail:
            message += f": {detail}"
        if response.status_code in (401, 403):
            message += (
                ". Verify the app's `sql` user-authorization scope and user "
                "consent, that `DATABRICKS_HOST` is the same workspace where "
                "the app is deployed, and that the signed-in user can use a "
                "SQL warehouse. Starting a warehouse does not grant "
                "permission."
            )
        raise DatabricksApiError(message)

    return response


def get_user_access_token(headers):
    """Return the forwarded Databricks user token without storing it."""
    for name, value in headers.items():
        if name.lower() == "x-forwarded-access-token":
            return value
    return None


def list_sql_warehouses(access_token, workspace_host):
    """List SQL warehouses visible to the current user."""
    path = "/api/2.0/sql/warehouses"
    page_token = None
    seen_page_tokens = set()
    warehouses = []

    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        response = _workspace_api_request(
            "GET",
            access_token,
            workspace_host,
            path,
            params=params,
        )
        try:
            payload = response.json()
        except ValueError as error:
            raise DatabricksApiError(
                "Databricks returned invalid warehouse data."
            ) from error

        if not isinstance(payload, dict):
            raise DatabricksApiError(
                "Databricks returned invalid warehouse data."
            )
        page = payload.get("warehouses")
        if not isinstance(page, list):
            raise DatabricksApiError(
                "Databricks returned an invalid warehouse list."
            )
        warehouses.extend(
            warehouse
            for warehouse in page
            if isinstance(warehouse, dict)
            and warehouse.get("id")
            and warehouse.get("name")
        )

        next_page_token = payload.get("next_page_token")
        if not next_page_token:
            break
        if next_page_token in seen_page_tokens:
            raise DatabricksApiError(
                "Databricks returned an invalid warehouse pagination token."
            )
        seen_page_tokens.add(next_page_token)
        page_token = next_page_token

    return sorted(
        warehouses,
        key=lambda warehouse: (
            str(warehouse["name"]).casefold(),
            str(warehouse["id"]),
        ),
    )


def ensure_sql_warehouse_running(
    access_token,
    workspace_host,
    warehouse_id,
    timeout_seconds=180,
    poll_interval_seconds=2,
):
    """Start a selected warehouse if needed and wait until it is running."""
    if not warehouse_id:
        raise DatabricksCatalogConfigurationError(
            "Select a SQL warehouse to continue."
        )

    encoded_id = quote(str(warehouse_id), safe="")
    warehouse_path = f"/api/2.0/sql/warehouses/{encoded_id}"
    response = _workspace_api_request(
        "GET",
        access_token,
        workspace_host,
        warehouse_path,
    )
    try:
        status = response.json()
    except ValueError as error:
        raise DatabricksApiError(
            "Databricks returned invalid warehouse status data."
        ) from error
    if not isinstance(status, dict):
        raise DatabricksApiError(
            "Databricks returned invalid warehouse status data."
        )
    state = status.get("state")

    if state == "RUNNING":
        return state
    start_requested = False
    if state == "STOPPED":
        _workspace_api_request(
            "POST",
            access_token,
            workspace_host,
            f"{warehouse_path}/start",
        )
        start_requested = True
    elif state not in {"STARTING", "STOPPING"}:
        raise DatabricksApiError(
            f"The selected warehouse cannot be started from state {state!r}."
        )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        time.sleep(poll_interval_seconds)
        response = _workspace_api_request(
            "GET",
            access_token,
            workspace_host,
            warehouse_path,
        )
        try:
            status = response.json()
        except ValueError as error:
            raise DatabricksApiError(
                "Databricks returned invalid warehouse status data."
            ) from error
        if not isinstance(status, dict):
            raise DatabricksApiError(
                "Databricks returned invalid warehouse status data."
            )
        state = status.get("state")
        if state == "RUNNING":
            return state
        if state == "STOPPED":
            if not start_requested:
                _workspace_api_request(
                    "POST",
                    access_token,
                    workspace_host,
                    f"{warehouse_path}/start",
                )
                start_requested = True
        elif state not in {"STARTING", "STOPPING"}:
            raise DatabricksApiError(
                f"The selected warehouse cannot be started from state {state!r}."
            )

    raise DatabricksApiError(
        f"Timed out waiting for warehouse {warehouse_id} to start."
    )


def connect_to_sql_warehouse(access_token, warehouse_id, workspace_host):
    """Connect to a Databricks SQL warehouse as the current user."""
    if not access_token:
        raise DatabricksCatalogConfigurationError(
            "Databricks user authorization is not available."
        )
    if not warehouse_id:
        raise DatabricksCatalogConfigurationError(
            "Select a SQL warehouse to continue."
        )
    if not workspace_host:
        raise DatabricksCatalogConfigurationError(
            "The Databricks workspace host is not configured."
        )

    host = urlsplit(_workspace_url(workspace_host, "")).hostname

    from databricks import sql

    return sql.connect(
        server_hostname=host,
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
        WHERE LOWER(table_schema) = LOWER(?)
    """
    parameters = [schema]
    if table_names is not None:
        query += (
            f" AND LOWER(table_name) IN "
            f"({', '.join('LOWER(?)' for _ in table_names)})"
        )
        parameters.extend(table_names)
    query += " ORDER BY table_name, ordinal_position"

    return fetch_dataframe(cursor, query, tuple(parameters))
