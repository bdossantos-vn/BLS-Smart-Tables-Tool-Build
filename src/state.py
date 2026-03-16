"""Session state helpers for the BLS Smart Tables Tool."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import streamlit as st


DEFAULT_STATE: dict[str, Any] = {
    "uploaded_filename": None,
    "raw_df": None,
    "cleaned_df": None,
    "question_labels": {},
    "ingestion_log": [],
    "cell_col": None,
    "blacklist_used": [],
    "restored_columns": [],
    "metadata_rows_removed": 0,
    "removed_column_count": 0,
    "removed_columns": [],
    "blank_cell_rows_removed": 0,
    "sheet_name": "",
    "ingestion_completed_at": "",
    "cell_letter_map": {},
    "locked_cell_bases": {},
    "cell_sort_order": {},
    "cell_config_editor": None,
    "question_metadata": [],
    "metadata_change_log": [],
    "scale_mappings": {},
    "custom_variables": [],
    "net_definitions": [],
    "global_filters": {},
    "weighting_config": {},
    "banner_config": {},
    "local_overrides": {},
    "stat_config": {},
    "generated_tables": {},
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
