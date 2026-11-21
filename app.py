"""Streamlit interface for browsing Databricks Unity Catalog metadata."""

import os
from pathlib import Path

import pandas as pd
import streamlit as st
from databricks.sql.exc import Error as DatabricksSqlError

from src.databricks_catalog import (
    DatabricksApiError,
    DatabricksCatalogConfigurationError,
    connect_to_sql_warehouse,
    ensure_sql_warehouse_running,
    get_user_access_token,
    list_catalogs,
    list_column_metadata,
    list_schemas,
    list_sql_warehouses,
    list_table_metadata,
)

BASE_DIRECTORY = Path(__file__).resolve().parent
ASSETS_DIRECTORY = BASE_DIRECTORY / "assets"

# Configure the page once before any widgets or rendered content.
st.set_page_config(
    page_title="Unity Catalog Explorer",
    layout="wide",
    page_icon=":bar_chart:",
)


def load_css(file_path, use_dark_theme):
    """Load the base stylesheet and optionally the dark-theme overrides."""
    with open(file_path, encoding="utf-8") as css_file:
        st.markdown(
            f"<style>{css_file.read()}</style>",
            unsafe_allow_html=True,
        )
    if use_dark_theme:
        with open(
            ASSETS_DIRECTORY / "css" / "dark_theme.css",
            encoding="utf-8",
        ) as dark_css:
            st.markdown(
                f"<style>{dark_css.read()}</style>",
                unsafe_allow_html=True,
            )


with st.sidebar:
    st.markdown("### Appearance")
    light_theme = st.toggle(
        "Light theme",
        value=False,
        key="light_theme",
        help="Switch between the dark and light application themes.",
    )

dark_theme = not light_theme
load_css(ASSETS_DIRECTORY / "css" / "styles.css", dark_theme)
st.title("Unity Catalog Explorer")
st.caption(
    "Browse the Unity Catalog metadata available to your Databricks account."
)


def show_catalog_browser(cursor_for_browser, catalog_name, schema_name):
    """Render table and column details for the selected catalog and schema."""
    table_metadata = list_table_metadata(
        cursor_for_browser,
        catalog_name,
        schema_name,
    )
    if table_metadata.empty:
        st.info("No tables or views in this schema are available to your account.")
        return

    table_names = table_metadata["table_name"].astype(str).tolist()
    st.subheader(f"{catalog_name}.{schema_name}")
    show_all_tables = st.checkbox(
        "Show details for all tables",
        value=True,
        key="show_all_tables",
    )
    if show_all_tables:
        selected_table_names = table_names
    else:
        previous_selection = st.session_state.get(
            "selected_table_names",
            [],
        )
        if not set(previous_selection).issubset(table_names):
            st.session_state["selected_table_names"] = []
        selected_table_names = st.multiselect(
            "Select table(s)",
            table_names,
            key="selected_table_names",
        )

    if not selected_table_names:
        st.info("Select one or more tables to see their details.")
        return

    selected_metadata = table_metadata[
        table_metadata["table_name"].isin(selected_table_names)
    ]
    column_metadata = list_column_metadata(
        cursor_for_browser,
        catalog_name,
        schema_name,
        selected_table_names,
    )
    st.caption(f"Showing details for {len(selected_metadata)} table(s).")

    for index, (_, table) in enumerate(selected_metadata.iterrows()):
        with st.expander(
            f"{table['table_name']} · {table['table_type']}",
            expanded=len(selected_metadata) == 1 or index == 0,
        ):
            show_table_details(table, column_metadata)


def show_table_details(table, column_metadata):
    """Render a table's attributes and its visible column metadata."""
    table_name = str(table["table_name"])
    detail_columns = st.columns(2)
    detail_columns[0].write(f"**Type:** {table['table_type']}")
    owner = table["table_owner"]
    detail_columns[0].write(
        f"**Owner:** {owner if pd.notna(owner) and owner else '—'}"
    )
    detail_columns[1].write(
        f"**Created:** {table['created'] if pd.notna(table['created']) else '—'}"
    )
    detail_columns[1].write(
        "**Last altered:** "
        f"{table['last_altered'] if pd.notna(table['last_altered']) else '—'}"
    )
    comment = table["comment"]
    if pd.notna(comment) and comment:
        st.write(f"**Comment:** {comment}")

    table_columns = column_metadata[
        column_metadata["table_name"]
        .astype(str)
        .str.casefold()
        == table_name.casefold()
    ][
        [
            "column_name",
            "full_data_type",
            "is_nullable",
            "comment",
        ]
    ].rename(
        columns={
            "column_name": "Column",
            "full_data_type": "Data type",
            "is_nullable": "Nullable",
            "comment": "Comment",
        }
    )
    if table_columns.empty:
        st.info(
            "No column metadata is visible for this table. "
            "Check that your Unity Catalog permissions allow you to "
            "interact with it."
        )
    else:
        st.markdown(
            table_columns.fillna("").to_html(
                index=False,
                escape=True,
                classes="metadata-table",
            ),
            unsafe_allow_html=True,
        )


user_access_token = get_user_access_token(st.context.headers)
if not user_access_token:
    st.info(
        "Sign in through the Databricks app with user authorization enabled "
        "to select a SQL warehouse and browse catalogs using your permissions."
    )
else:
    try:
        workspace_host = os.getenv("DATABRICKS_HOST")
        warehouses = list_sql_warehouses(
            user_access_token,
            workspace_host,
        )
    except (DatabricksApiError, DatabricksCatalogConfigurationError) as error:
        st.error(str(error))
    else:
        warehouse_by_id = {
            str(warehouse["id"]): warehouse for warehouse in warehouses
        }
        warehouse_ids = list(warehouse_by_id)
        if not warehouse_ids:
            st.sidebar.info("No SQL warehouses are available to your account.")
        else:
            if st.session_state.get("warehouse_id") not in warehouse_ids:
                st.session_state.pop("warehouse_id", None)
            st.sidebar.markdown("### Filters")
            selected_warehouse_id = st.sidebar.selectbox(
                "SQL warehouse",
                warehouse_ids,
                index=None,
                placeholder="Select a warehouse",
                format_func=lambda warehouse_id: (
                    f"{warehouse_by_id[warehouse_id]['name']} "
                    f"({warehouse_by_id[warehouse_id].get('state', 'UNKNOWN')})"
                ),
                key="warehouse_id",
            )
            if selected_warehouse_id:
                if (
                    st.session_state.get("_active_warehouse_id")
                    != selected_warehouse_id
                ):
                    st.session_state.pop("catalog_name", None)
                    st.session_state.pop("schema_name", None)
                    st.session_state.pop("selected_table_names", None)
                    st.session_state.pop("_active_catalog", None)
                    st.session_state.pop("_active_schema", None)
                    st.session_state["_active_warehouse_id"] = (
                        selected_warehouse_id
                    )

                warehouse = warehouse_by_id[selected_warehouse_id]
                try:
                    with st.spinner(
                        f"Starting {warehouse['name']} if it is stopped..."
                    ):
                        ensure_sql_warehouse_running(
                            user_access_token,
                            workspace_host,
                            selected_warehouse_id,
                        )

                    connection = connect_to_sql_warehouse(
                        user_access_token,
                        selected_warehouse_id,
                        workspace_host,
                    )
                    try:
                        with connection.cursor() as db_cursor:
                            catalog_names = list_catalogs(db_cursor)
                            if not catalog_names:
                                st.sidebar.info(
                                    "No Unity Catalog catalogs are available "
                                    "to your account."
                                )
                            else:
                                if (
                                    st.session_state.get("catalog_name")
                                    not in catalog_names
                                ):
                                    st.session_state["catalog_name"] = (
                                        catalog_names[0]
                                    )
                                selected_catalog = st.sidebar.selectbox(
                                    "Catalog",
                                    catalog_names,
                                    key="catalog_name",
                                )
                                if (
                                    st.session_state.get("_active_catalog")
                                    != selected_catalog
                                ):
                                    st.session_state.pop("schema_name", None)
                                    st.session_state.pop(
                                        "selected_table_names",
                                        None,
                                    )
                                    st.session_state["_active_catalog"] = (
                                        selected_catalog
                                    )
                                    st.session_state["_active_schema"] = None

                                schema_names = list_schemas(
                                    db_cursor,
                                    selected_catalog,
                                )
                                if not schema_names:
                                    st.sidebar.info(
                                        "No schemas in this catalog are "
                                        "available to your account."
                                    )
                                else:
                                    if (
                                        st.session_state.get("schema_name")
                                        not in schema_names
                                    ):
                                        st.session_state["schema_name"] = (
                                            schema_names[0]
                                        )
                                    selected_schema = st.sidebar.selectbox(
                                        "Schema",
                                        schema_names,
                                        key="schema_name",
                                    )
                                    schema_scope = (
                                        selected_catalog,
                                        selected_schema,
                                    )
                                    if (
                                        st.session_state.get("_active_schema")
                                        != schema_scope
                                    ):
                                        st.session_state.pop(
                                            "selected_table_names",
                                            None,
                                        )
                                        st.session_state["_active_schema"] = (
                                            schema_scope
                                        )

                                    show_catalog_browser(
                                        db_cursor,
                                        selected_catalog,
                                        selected_schema,
                                    )
                    finally:
                        connection.close()
                except DatabricksCatalogConfigurationError as error:
                    st.error(str(error))
                except DatabricksApiError as error:
                    st.error(f"Could not start the selected warehouse: {error}")
                except DatabricksSqlError as error:
                    st.error(f"Could not load Unity Catalog metadata: {error}")
