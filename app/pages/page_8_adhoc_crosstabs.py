"""Custom AdHoc Crosstabs page."""

from __future__ import annotations

import streamlit as st

from src.config import (
    build_analysis_variable_catalog,
    build_default_adhoc_crosstab_config,
    build_default_adhoc_crosstab_row,
)
from src.utils import normalize_text


def render() -> None:
    """Render the Custom AdHoc Crosstabs page."""
    st.header("8. Custom AdHoc Crosstabs")
    st.write(
        "Build custom crosstab tables by pairing one row variable with one column variable. "
        "All AdHoc tables will export together on a single sheet."
    )

    if not st.session_state.get("adhoc_crosstabs_config"):
        st.session_state.adhoc_crosstabs_config = build_default_adhoc_crosstab_config()

    variable_catalog = build_analysis_variable_catalog(
        st.session_state.get("question_metadata", []),
        st.session_state.get("custom_variables", []),
        st.session_state.get("comparison_col"),
    )
    variable_options = [item["id"] for item in variable_catalog]
    variable_labels = {item["id"]: item["label"] for item in variable_catalog}

    existing_tables = list(st.session_state.adhoc_crosstabs_config.get("tables", []))
    table_count = int(
        st.number_input(
            "Number of AdHoc Crosstabs",
            min_value=0,
            max_value=30,
            value=max(0, len(existing_tables)),
            step=1,
        )
    )
    while len(existing_tables) < table_count:
        existing_tables.append(build_default_adhoc_crosstab_row())
    existing_tables = existing_tables[:table_count]

    rendered_tables: list[dict[str, str]] = []
    for index in range(table_count):
        row = existing_tables[index]
        st.markdown(f"**AdHoc Crosstab {index + 1}**")
        table_name = st.text_input(
            "Crosstab Name",
            value=row.get("name", ""),
            key=f"adhoc_table_name_{index}",
            help="Optional short export label. If blank, the row variable name will be used.",
        )
        left, right = st.columns(2)
        row_variable = left.selectbox(
            "Row Variable",
            options=["", *variable_options],
            index=([ "", *variable_options ].index(row.get("row_variable", "")) if row.get("row_variable", "") in ["", *variable_options] else 0),
            format_func=lambda value: variable_labels.get(value, value) if value else "Select variable",
            key=f"adhoc_table_row_variable_{index}",
        )
        column_variable = right.selectbox(
            "Column Variable",
            options=["", *variable_options],
            index=([ "", *variable_options ].index(row.get("column_variable", "")) if row.get("column_variable", "") in ["", *variable_options] else 0),
            format_func=lambda value: variable_labels.get(value, value) if value else "Select variable",
            key=f"adhoc_table_column_variable_{index}",
        )
        rendered_tables.append(
            {
                "name": normalize_text(table_name) or normalize_text(row_variable),
                "row_variable": normalize_text(row_variable),
                "column_variable": normalize_text(column_variable),
            }
        )

    valid_tables = [
        row for row in rendered_tables
        if normalize_text(row.get("row_variable")) and normalize_text(row.get("column_variable"))
    ]
    st.session_state.adhoc_crosstabs_config = {
        "tables": valid_tables,
    }

    if table_count and not valid_tables:
        st.warning("Configure at least one valid AdHoc Crosstab with both a row variable and a column variable.")
    else:
        st.success("AdHoc Crosstab configuration saved.")
