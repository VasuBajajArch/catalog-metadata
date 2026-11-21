# Unity Catalog Explorer

A Streamlit app for browsing Unity Catalog metadata in Databricks. Select a
catalog and schema, then inspect metadata and column definitions for every
table or for tables you choose. Queries use the signed-in user's Databricks
identity, so catalog visibility follows that user's Unity Catalog permissions.

The app reads metadata only; it does not display table rows.

## Themes

Use the **Light theme** toggle in the sidebar to switch between light and dark
appearance. The sidebar, selectors, dropdown menus, and app header adapt to the
selected theme.

### Light theme

![Superstore Table Catalog in light theme](images/light_theme.png)

### Dark theme

![Superstore Table Catalog in dark theme](images/dark_theme.png)

## Deploy to Databricks Apps

The app needs a SQL warehouse resource and user authorization configured in
Databricks:

1. Add a SQL warehouse under the app's **Settings → Resources**, using the
   default resource key `sql-warehouse` and granting the app **Can use**.
   `app.yaml` maps this resource to `DATABRICKS_WAREHOUSE_ID`.
2. Under **Settings → User authorization**, add the `sql` scope and save.
3. Give each app user the required permission to use the warehouse and discover
   the Unity Catalog metadata they should see.
4. Deploy or redeploy the app.

The app uses the `X-Forwarded-Access-Token` supplied by Databricks Apps for each
request. It does not fall back to the app service principal for catalog queries.
This keeps metadata discovery scoped to the signed-in user. Local runs do not
receive this forwarded token and therefore cannot browse catalogs.

## Metadata displayed

For visible tables and views, the app displays the table type, owner, comment,
creation and last-altered timestamps, and column names, data types, nullability,
and comments. It queries Unity Catalog `information_schema` metadata and uses
parameterized filters for schema and table names.

## Dependencies

Install dependencies from the project directory with:

```sh
python -m pip install -r requirements.txt
```

## Project layout

- `app.py` - Streamlit interface and theme selection
- `src/databricks_catalog.py` - User-token SQL connection and metadata queries
- `assets/css/` - Light and dark theme stylesheets
- `images/` - Screenshots of the light and dark themes
- `tests/` - Unit tests
- `app.yaml` - Databricks Apps run command and warehouse resource mapping

Run the unit tests from the project directory with:

```sh
python -m unittest discover -s tests -p "test_*.py" -v
```
