import os
from pathlib import Path

import pandas as pd
import streamlit as st
from databricks.sql.exc import Error as DatabricksSqlError

from src.databricks_catalog import (
    DatabricksCatalogConfigurationError,
    connect_to_sql_warehouse,
    get_user_access_token,
    list_catalogs,
    list_column_metadata,
    list_schemas,
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


def load_css(file_path, dark_theme):
    """Load the base stylesheet and optionally the dark-theme overrides."""
    with open(file_path) as css_file:
        st.markdown(
            f"<style>{css_file.read()}</style>",
            unsafe_allow_html=True,
        )
    if dark_theme:
        with open(ASSETS_DIRECTORY / "css" / "dark_theme.css") as dark_css:
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


def show_catalog_browser(cursor):
    """Render the catalog, schema, table, and table-column browser."""
    catalog_names = list_catalogs(cursor)
    if not catalog_names:
        st.info("No Unity Catalog catalogs are available to your account.")
        return

    if st.session_state.get("catalog_name") not in catalog_names:
        st.session_state["catalog_name"] = catalog_names[0]
    selected_catalog = st.selectbox(
        "Catalog",
        catalog_names,
        key="catalog_name",
    )
    if st.session_state.get("_active_catalog") != selected_catalog:
        st.session_state.pop("schema_name", None)
        st.session_state.pop("selected_table_names", None)
        st.session_state["_active_catalog"] = selected_catalog
        st.session_state["_active_schema"] = None

    schema_names = list_schemas(cursor, selected_catalog)
    if not schema_names:
        st.info("No schemas in this catalog are available to your account.")
        return

    if st.session_state.get("schema_name") not in schema_names:
        st.session_state["schema_name"] = schema_names[0]
    selected_schema = st.selectbox(
        "Schema",
        schema_names,
        key="schema_name",
    )
    schema_scope = (selected_catalog, selected_schema)
    if st.session_state.get("_active_schema") != schema_scope:
        st.session_state.pop("selected_table_names", None)
        st.session_state["_active_schema"] = schema_scope

    table_metadata = list_table_metadata(
        cursor,
        selected_catalog,
        selected_schema,
    )
    if table_metadata.empty:
        st.info("No tables or views in this schema are available to your account.")
        return

    table_names = table_metadata["table_name"].astype(str).tolist()
    st.subheader(f"{selected_catalog}.{selected_schema}")
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
        cursor,
        selected_catalog,
        selected_schema,
        selected_table_names,
    )
    st.caption(f"Showing details for {len(selected_metadata)} table(s).")

    for index, (_, table) in enumerate(selected_metadata.iterrows()):
        table_name = str(table["table_name"])
        with st.expander(
            f"{table_name} · {table['table_type']}",
            expanded=len(selected_metadata) == 1 or index == 0,
        ):
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
                column_metadata["table_name"] == table_name
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
            st.dataframe(
                table_columns,
                use_container_width=True,
                hide_index=True,
            )


user_access_token = get_user_access_token(st.context.headers)
if not user_access_token:
    st.info(
        "Sign in through the Databricks app with user authorization enabled "
        "to browse catalogs using your permissions."
    )
else:
    connection = None
    cursor = None
    try:
        connection = connect_to_sql_warehouse(
            user_access_token,
            os.getenv("DATABRICKS_WAREHOUSE_ID"),
            os.getenv("DATABRICKS_HOST"),
        )
        cursor = connection.cursor()
        show_catalog_browser(cursor)
    except DatabricksCatalogConfigurationError as error:
        st.error(str(error))
    except DatabricksSqlError as error:
        st.error(f"Could not load Unity Catalog metadata: {error}")
    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()
