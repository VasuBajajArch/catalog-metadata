# Superstore Table Catalog

A Streamlit app for exploring table metadata from a CSV catalog. Filter tables
by database, schema, owner, table type, data size, and row count; sort table
cards by name; and view summary metrics for the current selection.

## Themes

Use the **Light theme** toggle in the sidebar to switch between light and dark
appearance. The sidebar, filter controls, dropdown menus, and app header adapt
to the selected theme.

### Light theme

![Superstore Table Catalog in light theme](images/light_theme.png)

### Dark theme

![Superstore Table Catalog in dark theme](images/dark_theme.png)

## Run locally

From the project directory, create and activate a virtual environment, install
the dependencies, and start the app:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

The app opens in your browser. Streamlit uses the dark theme by default; switch
to the light theme with the sidebar toggle.

## Catalog data

The app reads `data/table_information.csv`. The CSV must include these columns:

`database`, `schema`, `table_name`, `number_of_rows`, `primary_key`,
`columns`, `column_types`, `metadata`, `generated_at`, `owner`, `table_type`,
and `data_size_mb`.

## Tests

Run the catalog unit tests with:

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

## Project layout

- `app.py` - Streamlit application and filter controls
- `src/catalog.py` - Catalog loading, validation, filtering, and formatting
- `data/table_information.csv` - Catalog source data
- `assets/css/` - Light and dark theme stylesheets
- `assets/templates/` - Jinja templates for metrics and table cards
- `images/` - Screenshots of the light and dark themes
- `tests/` - Unit tests for catalog behavior
- `.streamlit/config.toml` - Default Streamlit theme configuration
