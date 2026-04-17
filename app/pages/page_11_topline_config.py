"""Topline configuration page."""

from __future__ import annotations

from copy import deepcopy

import pandas as pd
import streamlit as st

from src.custom_vars import build_question_lookup
from src.utils import format_timestamp


def _append_topline_change(message: str) -> None:
    """Append a timestamped change-log entry for topline configuration."""
    st.session_state.topline_change_log.append(f"[{format_timestamp()}] {message}")


def _build_topline_editor_frame() -> pd.DataFrame:
    """Create the editable topline inclusion table from current included columns.

    Inputs:
        Reads the currently included columns from session state and the saved
        topline configuration.

    Outputs:
        Returns a dataframe with one row per currently included column and a
        checkbox showing whether that column is included on the topline.
    """
    included_columns = list(st.session_state.get("included_columns", []))
    question_metadata = {row.get("variable"): row for row in st.session_state.get("question_metadata", [])}
    saved_variables = list(st.session_state.get("topline_config", {}).get("variables", []))

    if saved_variables:
        selected_lookup = {value: True for value in saved_variables}
    else:
        selected_lookup = {value: True for value in included_columns}

    rows: list[dict[str, object]] = []
    for variable in included_columns:
        metadata_row = question_metadata.get(variable, {})
        rows.append(
            {
                "Column": variable,
                "Question Text": metadata_row.get("question_label", variable),
                "Include in Topline": bool(selected_lookup.get(variable, False)),
            }
        )
    st.session_state.topline_editor_source_columns = included_columns
    return pd.DataFrame(rows)


def _reset_topline_editor() -> None:
    """Reset the topline selection back to all currently included columns.

    Inputs:
        Reads the currently included columns from session state.

    Outputs:
        Updates the saved topline configuration and editor dataframe in place.
    """
    included_columns = list(st.session_state.get("included_columns", []))
    current_config = deepcopy(st.session_state.get("topline_config", {}))
    current_config["variables"] = included_columns
    current_config["response_selections"] = _build_default_response_selections(included_columns)
    st.session_state.topline_config = current_config
    st.session_state.topline_editor = _build_topline_editor_frame()


def _build_default_response_selections(variables: list[str]) -> dict[str, list[str]]:
    """Build default topline response selections for the chosen variables.

    Inputs:
        variables: Variables currently selected for topline inclusion.

    Outputs:
        Returns a mapping of variable name to all available response choices
        and enabled net labels for that variable.
    """
    question_lookup = build_question_lookup(
        st.session_state.get("question_metadata", []),
        st.session_state.get("net_definitions", {}),
        st.session_state.get("scale_mappings", {}),
    )
    selections: dict[str, list[str]] = {}
    for variable in variables:
        question = question_lookup.get(variable, {})
        choices = list(question.get("answer_choices_list", []))
        selections[variable] = [str(choice) for choice in choices if str(choice).strip()]
    return selections


def render() -> None:
    """Render the Topline Configuration page.

    Inputs:
        Uses current included columns, question metadata, and saved topline
        options from session state.

    Outputs:
        Updates topline configuration in session state, including the selected
        columns, output options, and change log entries.
    """
    st.header("9. Topline Configuration")

    included_columns = list(st.session_state.get("included_columns", []))
    if not included_columns:
        st.info("Complete Data Intake before configuring topline columns.")
        return

    if (
        st.session_state.get("topline_editor") is None
        or list(st.session_state.get("topline_editor_source_columns", [])) != included_columns
    ):
        st.session_state.topline_editor = _build_topline_editor_frame()

    editor_df = st.data_editor(
        st.session_state.topline_editor,
        key="topline_columns_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Column": st.column_config.TextColumn("Column", disabled=True, width="medium"),
            "Question Text": st.column_config.TextColumn("Question Text", disabled=True, width="large"),
            "Include in Topline": st.column_config.CheckboxColumn("Include in Topline"),
        },
    )

    selected_variables_preview = [
        str(row["Column"])
        for row in editor_df.to_dict(orient="records")
        if bool(row.get("Include in Topline"))
    ]
    saved_response_selections = deepcopy(
        st.session_state.get("topline_config", {}).get("response_selections", {})
    )
    question_lookup = build_question_lookup(
        st.session_state.get("question_metadata", []),
        st.session_state.get("net_definitions", {}),
        st.session_state.get("scale_mappings", {}),
    )

    st.subheader("Response Choices")
    st.caption("Choose which response choices and saved nets should appear on the topline for each selected variable.")
    response_selection_map: dict[str, list[str]] = {}
    for variable in selected_variables_preview:
        question = question_lookup.get(variable, {})
        available_choices = [
            str(choice)
            for choice in question.get("answer_choices_list", [])
            if str(choice).strip()
        ]
        default_choices = saved_response_selections.get(variable, available_choices)
        valid_default_choices = [choice for choice in default_choices if choice in available_choices]
        selected_choices = st.multiselect(
            f"{variable} response choices",
            options=available_choices,
            default=valid_default_choices,
            key=f"topline_response_selection_{variable}",
        )
        response_selection_map[variable] = selected_choices

    button_left, button_right = st.columns(2)
    with button_left:
        if st.button("Update Columns", type="primary", use_container_width=True):
            previous_variables = list(st.session_state.get("topline_config", {}).get("variables", []))
            previous_response_selections = deepcopy(
                st.session_state.get("topline_config", {}).get("response_selections", {})
            )
            selected_variables = [
                str(row["Column"])
                for row in editor_df.to_dict(orient="records")
                if bool(row.get("Include in Topline"))
            ]
            st.session_state.topline_editor = editor_df.copy()
            updated_config = deepcopy(st.session_state.get("topline_config", {}))
            updated_config["variables"] = selected_variables
            updated_config["response_selections"] = {
                variable: list(response_selection_map.get(variable, []))
                for variable in selected_variables
            }
            st.session_state.topline_config = updated_config

            added = [value for value in selected_variables if value not in previous_variables]
            removed = [value for value in previous_variables if value not in selected_variables]
            response_updates = []
            for variable in selected_variables:
                old_choices = previous_response_selections.get(variable, [])
                new_choices = response_selection_map.get(variable, [])
                if old_choices != new_choices:
                    response_updates.append(variable)
            if added:
                _append_topline_change(f"Included topline columns: {', '.join(added)}")
            if removed:
                _append_topline_change(f"Removed topline columns: {', '.join(removed)}")
            if response_updates:
                _append_topline_change(
                    f"Updated topline response selections for: {', '.join(response_updates)}"
                )
            if not added and not removed:
                _append_topline_change("Topline columns updated with no net changes.")
            st.success("Topline columns updated.")

    with button_right:
        if st.button("Reset Columns", use_container_width=True):
            _reset_topline_editor()
            _append_topline_change("Topline columns reset to all currently included columns.")
            st.success("Topline columns reset.")
            st.rerun()

    include_lift = st.checkbox(
        "Include lift",
        value=bool(st.session_state.get("topline_config", {}).get("include_lift", False)),
        help="Lift is only meaningful for binary comparison splits.",
    )
    include_significance_notes = st.checkbox(
        "Include significance notes",
        value=bool(st.session_state.get("topline_config", {}).get("include_significance_notes", True)),
    )

    current_config = deepcopy(st.session_state.get("topline_config", {}))
    current_config["include_lift"] = include_lift
    current_config["include_significance_notes"] = include_significance_notes
    if "variables" not in current_config:
        current_config["variables"] = [
            str(row["Column"])
            for row in st.session_state.topline_editor.to_dict(orient="records")
            if bool(row.get("Include in Topline"))
        ]
    st.session_state.topline_config = current_config

    st.subheader("Change Log")
    if st.session_state.get("topline_change_log"):
        for entry in reversed(st.session_state.topline_change_log[-20:]):
            st.code(entry)
    else:
        st.caption("No topline changes yet.")
