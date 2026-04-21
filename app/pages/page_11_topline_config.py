"""Topline configuration page."""

from __future__ import annotations

from copy import deepcopy
import re

import pandas as pd
import streamlit as st

from src.custom_vars import build_question_lookup
from src.metadata import serialize_answer_choices
from src.utils import format_timestamp


def _append_topline_change(message: str) -> None:
    """Append a timestamped change-log entry for topline configuration."""
    st.session_state.topline_change_log.append(f"[{format_timestamp()}] {message}")


def _build_custom_variable_choices(record: dict[str, object]) -> list[str]:
    """Return the displayable bucket labels for one saved custom variable."""
    choices = [
        str(bucket.get("label", "")).strip()
        for bucket in record.get("buckets", [])
        if str(bucket.get("label", "")).strip()
    ]
    if record.get("fallback_mode") == "Create additional option":
        fallback_label = str(record.get("fallback_label", "")).strip() or "Other"
        if fallback_label not in choices:
            choices.append(fallback_label)
    return choices


def _default_topline_choices(variable: str, question: dict[str, object]) -> list[str]:
    """Return the default selected topline choices for one variable."""
    available_choices = [
        str(choice) for choice in question.get("answer_choices_list", []) if str(choice).strip()
    ]
    enabled_net_labels = [
        str(label) for label in question.get("choice_expansion_map", {}).keys() if str(label).strip()
    ]
    if enabled_net_labels:
        return enabled_net_labels
    return available_choices


def _build_topline_catalog() -> list[dict[str, object]]:
    """Build the list of topline-eligible rows from included columns and custom variables."""
    included_columns = list(st.session_state.get("included_columns", []))
    saved_variables = list(st.session_state.get("topline_config", {}).get("variables", []))
    response_selections = deepcopy(
        st.session_state.get("topline_config", {}).get("response_selections", {})
    )
    note_base_sections = deepcopy(
        st.session_state.get("topline_config", {}).get("note_base_sections", {})
    )
    question_lookup = build_question_lookup(
        st.session_state.get("question_metadata", []),
        st.session_state.get("net_definitions", {}),
        st.session_state.get("scale_mappings", {}),
    )

    rows: list[dict[str, object]] = []
    for variable in included_columns:
        question = question_lookup.get(variable, {})
        available_choices = _default_topline_choices(variable, question)
        all_display_choices = [
            str(choice) for choice in question.get("answer_choices_list", []) if str(choice).strip()
        ]
        selected_choices = response_selections.get(variable, available_choices)
        valid_selected_choices = [choice for choice in selected_choices if choice in all_display_choices]
        if not saved_variables:
            include_in_topline = True
        else:
            include_in_topline = variable in saved_variables
        rows.append(
            {
                "Column": variable,
                "Question Text": question.get("question_label", variable),
                "Response Choices Count": len(all_display_choices),
                "Available Response Choices": serialize_answer_choices(all_display_choices),
                "Include in Topline": include_in_topline,
                "_default_choices": all_display_choices,
                "_preferred_default_choices": available_choices,
                "_selected_choices": valid_selected_choices,
                "_note_base_section": note_base_sections.get(variable, "Total Answering"),
                "_row_type": "question",
            }
        )

    for record in st.session_state.get("custom_variables", []):
        variable_name = str(record.get("name", "")).strip()
        if not variable_name:
            continue
        available_choices = _build_custom_variable_choices(record)
        selected_choices = response_selections.get(variable_name, available_choices)
        valid_selected_choices = [choice for choice in selected_choices if choice in available_choices]
        include_in_topline = variable_name in saved_variables if saved_variables else False
        rows.append(
            {
                "Column": variable_name,
                "Question Text": f"Custom Variable - {record.get('builder_type', 'Custom Variable')}",
                "Response Choices Count": len(available_choices),
                "Available Response Choices": serialize_answer_choices(available_choices),
                "Include in Topline": include_in_topline,
                "_default_choices": available_choices,
                "_preferred_default_choices": available_choices,
                "_selected_choices": valid_selected_choices,
                "_note_base_section": note_base_sections.get(variable_name, "Total Answering"),
                "_row_type": "custom_variable",
            }
        )
    return rows


def _build_source_signature() -> list[str]:
    """Build a compact signature so the editor refreshes when inputs change."""
    included_columns = list(st.session_state.get("included_columns", []))
    custom_names = [
        str(item.get("name", "")).strip()
        for item in st.session_state.get("custom_variables", [])
        if str(item.get("name", "")).strip()
    ]
    return included_columns + ["__custom__"] + custom_names


def _build_topline_editor_frame() -> pd.DataFrame:
    """Create the editable topline table from included columns and custom variables."""
    rows = _build_topline_catalog()
    st.session_state.topline_editor_source_signature = _build_source_signature()
    return pd.DataFrame(rows)


def _reset_topline_editor() -> None:
    """Reset the topline configuration back to current defaults."""
    included_columns = list(st.session_state.get("included_columns", []))
    question_lookup = build_question_lookup(
        st.session_state.get("question_metadata", []),
        st.session_state.get("net_definitions", {}),
        st.session_state.get("scale_mappings", {}),
    )
    response_selections = {
        variable: _default_topline_choices(variable, question_lookup.get(variable, {}))
        for variable in included_columns
    }
    for record in st.session_state.get("custom_variables", []):
        variable_name = str(record.get("name", "")).strip()
        if variable_name:
            response_selections[variable_name] = _build_custom_variable_choices(record)

    current_config = deepcopy(st.session_state.get("topline_config", {}))
    current_config["variables"] = included_columns
    current_config["response_selections"] = response_selections
    current_config["note_base_sections"] = {
        variable: "Total Answering"
        for variable in response_selections
    }
    st.session_state.topline_config = current_config
    st.session_state.topline_editor = _build_topline_editor_frame()


def _topline_choice_key(variable: str) -> str:
    """Build a safe session-state key for one topline response chooser."""
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", variable).strip("_") or "variable"
    return f"topline_choice_selector_{slug}"


def _topline_note_base_key(variable: str) -> str:
    """Build a safe session-state key for one topline note-base selector."""
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", variable).strip("_") or "variable"
    return f"topline_note_base_selector_{slug}"


def _set_all_selected_note_bases(rows: list[dict[str, object]], note_base: str) -> None:
    """Apply one note-base choice to every currently included topline row."""
    for row in rows:
        variable = str(row.get("Column", "")).strip()
        if not variable:
            continue
        st.session_state[_topline_note_base_key(variable)] = note_base


def render() -> None:
    """Render the Topline Configuration page."""
    st.header("9. Topline Configuration")

    included_columns = list(st.session_state.get("included_columns", []))
    custom_variables = list(st.session_state.get("custom_variables", []))
    if not included_columns and not custom_variables:
        st.info("Complete Data Intake before configuring topline columns.")
        return

    if (
        st.session_state.get("topline_editor") is None
        or list(st.session_state.get("topline_editor_source_signature", [])) != _build_source_signature()
    ):
        st.session_state.topline_editor = _build_topline_editor_frame()

    editor_source_df = st.session_state.topline_editor.copy()
    editor_df = st.data_editor(
        editor_source_df.drop(columns=["_default_choices", "_preferred_default_choices", "_row_type"], errors="ignore"),
        key="topline_columns_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        height=560,
        column_config={
            "Column": st.column_config.TextColumn("Column", disabled=True, width="medium"),
            "Question Text": st.column_config.TextColumn("Question Text", disabled=True, width="large"),
            "Response Choices Count": st.column_config.NumberColumn(
                "Response Choices Count", disabled=True, width="small"
            ),
            "Available Response Choices": st.column_config.TextColumn(
                "Available Response Choices",
                disabled=True,
                width="large",
            ),
            "Include in Topline": st.column_config.CheckboxColumn("Include in Topline"),
        },
    )

    selected_editor_rows = [
        row
        for row in editor_df.to_dict(orient="records")
        if bool(row.get("Include in Topline", False))
    ]
    source_lookup = {
        str(row.get("Column", "")).strip(): row
        for row in editor_source_df.to_dict(orient="records")
    }

    if selected_editor_rows:
        st.subheader("Topline Response Selection")
        st.caption(
            "Choose the exact response options, nets, or custom-variable buckets to show in the topline, "
            "and which banner-comparison base the notes should use."
        )
        bulk_left, bulk_right = st.columns(2)
        with bulk_left:
            if st.button("Set All Banner Sig Comparisons to Total Answering", use_container_width=True):
                _set_all_selected_note_bases(selected_editor_rows, "Total Answering")
                st.success("All selected Banner Sig Comparisons set to Total Answering.")
                st.rerun()
        with bulk_right:
            if st.button("Set All Banner Sig Comparisons to Total Sample", use_container_width=True):
                _set_all_selected_note_bases(selected_editor_rows, "Total Sample")
                st.success("All selected Banner Sig Comparisons set to Total Sample.")
                st.rerun()
        for row in selected_editor_rows:
            variable = str(row.get("Column", "")).strip()
            source_row = source_lookup.get(variable, {})
            default_choices = list(source_row.get("_default_choices", []))
            preferred_default_choices = list(source_row.get("_preferred_default_choices", default_choices))
            saved_choices = list(source_row.get("_selected_choices", preferred_default_choices))
            valid_saved_choices = [choice for choice in saved_choices if choice in default_choices]
            choice_key = _topline_choice_key(variable)
            note_base_key = _topline_note_base_key(variable)
            saved_note_base = str(source_row.get("_note_base_section", "Total Answering")).strip() or "Total Answering"
            if (
                choice_key not in st.session_state
                or not isinstance(st.session_state.get(choice_key), list)
                or any(choice not in default_choices for choice in st.session_state.get(choice_key, []))
            ):
                st.session_state[choice_key] = valid_saved_choices
            if st.session_state.get(note_base_key) not in {"Total Sample", "Total Answering"}:
                st.session_state[note_base_key] = saved_note_base

            with st.expander(f"{variable} Response Choices", expanded=False):
                st.multiselect(
                    "Select topline response choices",
                    options=default_choices,
                    key=choice_key,
                    help="Only the selected response choices will appear in the topline export.",
                )
                st.selectbox(
                    "Banner Sig Comparisons",
                    options=["Total Answering", "Total Sample"],
                    key=note_base_key,
                    help="Choose which banner-table base should drive the subgroup significance comparisons.",
                )
    else:
        st.caption("Check one or more rows above to choose topline response options.")

    button_left, button_right = st.columns(2)
    with button_left:
        if st.button("Update Columns", type="primary", use_container_width=True):
            previous_config = deepcopy(st.session_state.get("topline_config", {}))
            previous_variables = list(previous_config.get("variables", []))
            previous_response_selections = deepcopy(previous_config.get("response_selections", {}))
            previous_note_base_sections = deepcopy(previous_config.get("note_base_sections", {}))

            selected_variables: list[str] = []
            updated_response_selections: dict[str, list[str]] = {}
            updated_note_base_sections: dict[str, str] = {}
            response_updates: list[str] = []
            note_base_updates: list[str] = []

            updated_rows: list[dict[str, object]] = []
            source_records = editor_source_df.to_dict(orient="records")
            edited_records = editor_df.to_dict(orient="records")

            for source_row, edited_row in zip(source_records, edited_records):
                variable = str(edited_row.get("Column", "")).strip()
                default_choices = list(source_row.get("_default_choices", []))
                preferred_default_choices = list(source_row.get("_preferred_default_choices", default_choices))
                choice_key = _topline_choice_key(variable)
                note_base_key = _topline_note_base_key(variable)
                selected_choices = list(
                    st.session_state.get(
                        choice_key,
                        source_row.get("_selected_choices", preferred_default_choices),
                    )
                )
                parsed_choices = [choice for choice in selected_choices if choice in default_choices]
                selected_note_base = str(
                    st.session_state.get(note_base_key, source_row.get("_note_base_section", "Total Answering"))
                ).strip() or "Total Answering"
                if selected_note_base not in {"Total Sample", "Total Answering"}:
                    selected_note_base = "Total Answering"
                updated_rows.append(
                    {
                        **source_row,
                        "Response Choices Count": len(default_choices),
                        "Available Response Choices": serialize_answer_choices(default_choices),
                        "Include in Topline": bool(edited_row.get("Include in Topline", False)),
                        "_preferred_default_choices": preferred_default_choices,
                        "_selected_choices": parsed_choices,
                        "_note_base_section": selected_note_base,
                    }
                )
                if bool(edited_row.get("Include in Topline", False)):
                    selected_variables.append(variable)
                    updated_response_selections[variable] = parsed_choices
                    updated_note_base_sections[variable] = selected_note_base

                previous_choices = list(previous_response_selections.get(variable, preferred_default_choices))
                if previous_choices != parsed_choices:
                    response_updates.append(
                        f"{variable}: {serialize_answer_choices(previous_choices)} -> "
                        f"{serialize_answer_choices(parsed_choices)}"
                    )
                previous_note_base = str(previous_note_base_sections.get(variable, "Total Answering")).strip() or "Total Answering"
                if previous_note_base != selected_note_base:
                    note_base_updates.append(f"{variable}: {previous_note_base} -> {selected_note_base}")

            updated_config = deepcopy(previous_config)
            updated_config["variables"] = selected_variables
            updated_config["response_selections"] = updated_response_selections
            updated_config["note_base_sections"] = updated_note_base_sections
            st.session_state.topline_config = updated_config
            st.session_state.topline_editor = pd.DataFrame(updated_rows)

            added = [value for value in selected_variables if value not in previous_variables]
            removed = [value for value in previous_variables if value not in selected_variables]
            if added:
                _append_topline_change(f"Included topline rows: {', '.join(added)}")
            if removed:
                _append_topline_change(f"Removed topline rows: {', '.join(removed)}")
            if response_updates:
                _append_topline_change(
                    f"Updated topline response selections for: {'; '.join(response_updates)}"
                )
            if note_base_updates:
                _append_topline_change(
                    f"Updated banner comparison note bases for: {'; '.join(note_base_updates)}"
                )
            if not added and not removed and not response_updates and not note_base_updates:
                _append_topline_change("Topline rows saved with no content changes.")
            st.success("Topline columns updated.")
            st.rerun()

    with button_right:
        if st.button("Reset Columns", use_container_width=True):
            _reset_topline_editor()
            _append_topline_change("Topline rows reset to current defaults.")
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
    st.session_state.topline_config = current_config

    st.subheader("Change Log")
    if st.session_state.get("topline_change_log"):
        for entry in reversed(st.session_state.topline_change_log[-20:]):
            st.code(entry)
    else:
        st.caption("No topline changes yet.")
