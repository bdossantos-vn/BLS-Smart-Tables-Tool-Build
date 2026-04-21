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
        "Build custom crosstab tables by pairing one question/custom variable with one saved banner. "
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

    banner_rows = list(st.session_state.get("banner_config", {}).get("banners", []))
    banner_options = [normalize_text(row.get("name")) for row in banner_rows if normalize_text(row.get("name"))]
    if not banner_options:
        st.info("Create at least one banner on the Banner Configuration page before building AdHoc crosstabs.")
        return

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
            help="Optional short export label. If blank, the source variable name will be used.",
        )
        left, right = st.columns(2)
        variable = left.selectbox(
            "Question / Custom Variable",
            options=["", *variable_options],
            index=([ "", *variable_options ].index(row.get("variable", "")) if row.get("variable", "") in ["", *variable_options] else 0),
            format_func=lambda value: variable_labels.get(value, value) if value else "Select variable",
            key=f"adhoc_table_variable_{index}",
        )
        banner = right.selectbox(
            "Banner",
            options=["", *banner_options],
            index=([ "", *banner_options ].index(normalize_text(row.get("banner"))) if normalize_text(row.get("banner")) in ["", *banner_options] else 0),
            format_func=lambda value: value if value else "Select banner",
            key=f"adhoc_table_banner_{index}",
        )
        rendered_tables.append(
            {
                "name": normalize_text(table_name) or normalize_text(variable),
                "variable": normalize_text(variable),
                "banner": normalize_text(banner),
            }
        )

    valid_tables = [
        row for row in rendered_tables
        if normalize_text(row.get("variable")) and normalize_text(row.get("banner"))
    ]
    st.session_state.adhoc_crosstabs_config = {
        "tables": valid_tables,
    }

    if table_count and not valid_tables:
        st.warning("Configure at least one valid AdHoc Crosstab with both a variable and a banner.")
    else:
        st.success("AdHoc Crosstab configuration saved.")
