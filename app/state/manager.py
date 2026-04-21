"""Central session-state manager for the refactored app.

This module keeps a structured `project_config` object in sync with the
existing step-level session state used by the current working pages.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import streamlit as st

from app.models.project_config import build_default_project_config
from src.state import init_session_state


EXTRA_DEFAULTS: dict[str, Any] = {
    "project_config": build_default_project_config(),
    "topline_config": {
        "variables": [],
        "response_selections": {},
        "note_base_sections": {},
        "include_lift": False,
        "include_significance_notes": True,
    },
    "topline_editor": None,
    "topline_change_log": [],
    "topline_editor_source_signature": [],
    "project_setup_mode": "Start from scratch",
    "template_upload_message": "",
    "app_current_step": "1. Project Setup",
}


def init_app_state() -> None:
    """Initialize legacy state plus new central app state.

    This function should be called once at the start of every app run.
    """
    init_session_state()
    for key, value in EXTRA_DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = deepcopy(value)
    sync_project_config_from_session()


def sync_project_config_from_session() -> None:
    """Copy current step-level session state into the central config object.

    The goal is to keep one structured configuration payload that can be
    exported as a template and used later for persistence.
    """
    project_config = st.session_state.get("project_config") or build_default_project_config()
    project_config["project"] = {
        "template_name": project_config.get("project", {}).get("template_name", ""),
        "setup_mode": st.session_state.get("project_setup_mode", "Start from scratch"),
    }
    project_config["data"] = {
        "uploaded_filename": st.session_state.get("uploaded_filename"),
        "sheet_name": st.session_state.get("sheet_name"),
        "available_sheets": list(st.session_state.get("available_sheets", [])),
        "comparison_col": st.session_state.get("comparison_col"),
        "comparison_configured": bool(st.session_state.get("comparison_configured")),
        "comparison_rows_removed": int(st.session_state.get("comparison_rows_removed", 0)),
        "comparison_group_labels": deepcopy(st.session_state.get("comparison_group_labels", {})),
    }
    project_config["variables"] = {
        "included_columns": list(st.session_state.get("included_columns", [])),
        "excluded_columns": list(st.session_state.get("removed_columns", [])),
        "restored_columns": list(st.session_state.get("restored_columns", [])),
    }
    project_config["question_types"] = {
        row.get("variable"): {
            "question_text": row.get("question_label", ""),
            "question_type": row.get("detected_type", ""),
            "answer_choices": list(row.get("answer_choices_list", [])),
        }
        for row in st.session_state.get("question_metadata", [])
        if row.get("variable")
    }
    project_config["scales"] = deepcopy(st.session_state.get("scale_mappings", {}))
    project_config["nets"] = deepcopy(st.session_state.get("net_definitions", {}))
    project_config["custom_variables"] = {
        item.get("name", f"custom_{index}"): deepcopy(item)
        for index, item in enumerate(st.session_state.get("custom_variables", []), start=1)
    }
    project_config["banners"] = deepcopy(st.session_state.get("banner_config", {}))
    project_config["filters"] = deepcopy(st.session_state.get("global_filters", {}))
    project_config["weights"] = deepcopy(st.session_state.get("weighting_config", {}))
    project_config["stats"] = deepcopy(st.session_state.get("stat_config", {}))
    project_config["topline"] = deepcopy(st.session_state.get("topline_config", EXTRA_DEFAULTS["topline_config"]))
    st.session_state.project_config = project_config


def load_project_template(template_payload: dict[str, Any]) -> None:
    """Apply a saved template to current session state.

    Inputs:
        template_payload: Configuration-only template payload. It must not
        contain respondent data.

    Outputs:
        Updates Streamlit session state in-place.
    """
    project_config = build_default_project_config()
    for section, default_value in project_config.items():
        if section in template_payload and isinstance(template_payload[section], type(default_value)):
            project_config[section] = deepcopy(template_payload[section])

    st.session_state.project_config = project_config
    st.session_state.project_setup_mode = project_config.get("project", {}).get("setup_mode", "Upload template")
    st.session_state.banner_config = deepcopy(project_config.get("banners", {}))
    st.session_state.global_filters = deepcopy(project_config.get("filters", {}))
    st.session_state.weighting_config = deepcopy(project_config.get("weights", {}))
    st.session_state.stat_config = deepcopy(project_config.get("stats", {}))
    st.session_state.scale_mappings = deepcopy(project_config.get("scales", {}))
    st.session_state.net_definitions = deepcopy(project_config.get("nets", {}))
    st.session_state.custom_variables = list(project_config.get("custom_variables", {}).values())
    st.session_state.topline_config = deepcopy(project_config.get("topline", EXTRA_DEFAULTS["topline_config"]))
    st.session_state.comparison_group_labels = deepcopy(
        project_config.get("data", {}).get("comparison_group_labels", {})
    )
    st.session_state.template_upload_message = "Template loaded successfully."


def export_project_template() -> str:
    """Serialize the current project configuration as JSON text.

    Returns:
        A JSON string that contains configuration only and excludes data rows.
    """
    sync_project_config_from_session()
    return json.dumps(st.session_state.project_config, indent=2)
