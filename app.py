from pathlib import Path

import streamlit as st

from src.catalog import (
    build_table_card_context,
    create_template_environment,
    filter_catalog,
    load_catalog,
    summarize_catalog,
)

BASE_DIRECTORY = Path(__file__).resolve().parent
ASSETS_DIRECTORY = BASE_DIRECTORY / "assets"
DATA_DIRECTORY = BASE_DIRECTORY / "data"

# Configure the page once before any widgets or rendered content.
st.set_page_config(
    page_title="Superstore App",
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
templates = create_template_environment(ASSETS_DIRECTORY)

try:
    table_information = load_catalog(DATA_DIRECTORY / "table_information.csv")
except (FileNotFoundError, ValueError) as error:
    # Stop rendering instead of continuing with an incomplete catalog.
    st.error(str(error))
    st.stop()

with st.sidebar:
    st.markdown("### View Details")

    # Track every filter in Streamlit session state through stable widget keys.
    order_by = st.selectbox(
        "Order By",
        ["A \u2192 Z", "Z \u2192 A"],
        key="order_by",
    )
    database = st.selectbox(
        "Database",
        ["All"] + sorted(table_information["database"].dropna().unique()),
        key="database",
    )
    schema = st.selectbox(
        "Table Schema",
        ["All"] + sorted(table_information["schema"].dropna().unique()),
        key="schema",
    )
    owner = st.selectbox(
        "Table Owner",
        ["All"] + sorted(table_information["owner"].dropna().unique()),
        key="owner",
    )
    table_types = st.multiselect(
        "Table Type",
        sorted(table_information["table_type"].dropna().unique()),
        default=[],
        key="table_type",
    )

    max_size = max(1.0, float(table_information["data_size_mb"].max()))
    size_limit = st.slider(
        "Data Size (MB)",
        min_value=0.0,
        max_value=float(round(max_size, 2)),
        value=float(round(max_size, 2)),
        step=0.1,
        key="size_limit",
    )

    max_rows = max(1, int(table_information["number_of_rows"].max()))
    row_limit = st.slider(
        "Number of Rows",
        min_value=0,
        max_value=max_rows,
        value=max_rows,
        step=max(1, max_rows // 100),
        key="row_limit",
    )

    if st.button("Clear Selections", use_container_width=True):
        st.session_state.order_by = "A \u2192 Z"
        st.session_state.database = "All"
        st.session_state.schema = "All"
        st.session_state.owner = "All"
        st.session_state.table_type = []
        st.session_state.size_limit = float(round(max_size, 2))
        st.session_state.row_limit = max_rows
        st.rerun()

filtered_information = filter_catalog(
    table_information,
    database=database,
    schema=schema,
    owner=owner,
    table_types=table_types,
    size_limit=size_limit,
    row_limit=row_limit,
    order_by=order_by,
)

summary = summarize_catalog(filtered_information)
st.markdown(
    templates.get_template("catalog_metrics.html").render(**summary),
    unsafe_allow_html=True,
)

cards_per_row = 3
for start in range(0, len(filtered_information), cards_per_row):
    columns = st.columns(cards_per_row)
    card_rows = filtered_information.iloc[start:start + cards_per_row]
    for column, (_, table_row) in zip(columns, card_rows.iterrows()):
        card = templates.get_template("table_card.html").render(
            **build_table_card_context(table_row)
        )
        column.markdown(card, unsafe_allow_html=True)

