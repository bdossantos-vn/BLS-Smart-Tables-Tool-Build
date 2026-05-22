"""Session state helpers for the BLS Smart Tables Tool."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import streamlit as st


DEFAULT_STATE: dict[str, Any] = {
    "uploaded_filename": None,
    "raw_df": None,
    "survey_df": None,
    "cleaned_df": None,
    "question_labels": {},
    "ingestion_log": [],
    "intake_change_log": [],
    "cell_col": None,
    "comparison_col": None,
    "comparison_options": [],
    "comparison_configured": False,
    "comparison_rows_removed": 0,
    "comparison_group_order": {},
    "comparison_group_labels": {},
    # 2026-05-19 BD: Persist rule-defined layered comparison groups alongside
    # the existing simple comparison-variable state.
    "comparison_scheme": {
        "enabled": False,
        "mode": "exclusive",
        "control_group_id": "",
        "groups": [],
    },
    "included_columns": [],
    "included_editor": None,
    "blacklist_used": [],
    "blacklist_catalog": [],
    "restored_columns": [],
    "metadata_rows_removed": 0,
    "removed_column_count": 0,
    "removed_columns": [],
    "blank_cell_rows_removed": 0,
    "sheet_name": "",
    "available_sheets": [],
    "ingestion_completed_at": "",
    "cell_letter_map": {},
    "locked_cell_bases": {},
    "cell_sort_order": {},
    "cell_config_editor": None,
    "blacklist_editor": None,
    "question_metadata": [],
    "metadata_change_log": [],
    "scale_mappings": {},
    "scale_change_log": [],
    "scale_mapping_seed_version": 0,
    "scale_save_message": "",
    "net_save_message": "",
    "custom_variables": [],
    "custom_var_edit_name": None,
    "custom_var_reset_requested": False,
    "custom_var_edit_payload": None,
    "net_definitions": {},
    "adhoc_crosstabs_config": {"tables": []},
    "topline_editor": None,
    "topline_change_log": [],
    "topline_editor_source_columns": [],
    "topline_response_selections": {},
    "global_filters": {},
    "weighting_config": {},
    "banner_config": {},
    "local_overrides": {},
    "stat_config": {},
    "banner_stat_config": {},
    "adhoc_stat_config": {},
    "generated_tables": {},
    "generated_tables_signature": "",
    "generated_excel_bytes": None,
    "generated_excel_filename": "",
    "generated_excel_signature": "",
}


def init_session_state() -> None:
    """Initialize expected session state keys exactly once per session."""
    for key, value in DEFAULT_STATE.items():
        if key not in st.session_state:
            st.session_state[key] = deepcopy(value)


def reset_project_state() -> None:
    """Reset the project-scoped state keys to their defaults."""
    for key, value in DEFAULT_STATE.items():
        st.session_state[key] = deepcopy(value)
