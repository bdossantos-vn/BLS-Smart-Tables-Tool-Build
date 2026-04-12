"""Topline configuration page."""

from __future__ import annotations

import streamlit as st

from src.config import build_analysis_variable_catalog


def render() -> None:
    """Render the Topline Configuration page.

    This first refactor pass stores topline choices in central state and
    prepares the later export layer to consume them.
    """
    st.header("9. Topline Configuration")
    st.write("Choose which variables should appear on the topline sheet and which supporting options to include.")

    variable_catalog = build_analysis_variable_catalog(
        st.session_state.get("question_metadata", []),
        st.session_state.get("custom_variables", []),
        st.session_state.get("comparison_col"),
    )
    variable_options = [item["id"] for item in variable_catalog]
    variable_labels = {item["id"]: item["label"] for item in variable_catalog}

    topline_config = st.session_state.get("topline_config", {})
    selected_variables = st.multiselect(
        "Topline Variables",
        options=variable_options,
        default=[value for value in topline_config.get("variables", []) if value in variable_options],
        format_func=lambda value: variable_labels.get(value, value),
        help="Select variables and custom variables that should be summarized on the topline sheet.",
    )
    include_lift = st.checkbox(
        "Include lift",
        value=bool(topline_config.get("include_lift", False)),
        help="Lift is only meaningful for binary comparison splits.",
    )
    include_significance_notes = st.checkbox(
        "Include significance notes",
        value=bool(topline_config.get("include_significance_notes", True)),
    )

    st.session_state.topline_config = {
        "variables": selected_variables,
        "include_lift": include_lift,
        "include_significance_notes": include_significance_notes,
    }
    st.success("Topline configuration saved.")
