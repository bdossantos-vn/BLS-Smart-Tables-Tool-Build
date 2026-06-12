"""Central session-state manager for the refactored app.

This module keeps a structured `project_config` object in sync with the
existing step-level session state used by the current working pages.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import streamlit as st

from app.models.project_config import (
    build_default_project_config,
    build_project_snapshot,
    migrate_project_config,
    unpack_project_payload,
)
from src.config import build_default_adhoc_crosstab_config, build_default_stat_config
from src.comparisons import build_default_comparison_scheme, sanitize_comparison_scheme
from src.metadata import parse_answer_choices, serialize_answer_choices
from src.state import init_session_state


EXTRA_DEFAULTS: dict[str, Any] = {
    "project_config": build_default_project_config(),
    "topline_config": {
        "configured": False,
        "variables": [],
        "response_selections": {},
        "note_base_sections": {},
        "include_lift": False,
        "comparison_scope": "control_vs_test",
        "include_significance_notes": True,
    },
    "topline_editor": None,
    "topline_change_log": [],
    "topline_editor_source_signature": [],
    "project_setup_mode": "Start from scratch",
    "template_upload_message": "",
    "app_current_step": "1. Project Setup",
    "adhoc_crosstabs_config": build_default_adhoc_crosstab_config(),
    "banner_stat_config": build_default_stat_config(),
    "adhoc_stat_config": build_default_stat_config(),
    "comparison_scheme": build_default_comparison_scheme(),
    "pending_project_config": None,
    "pending_project_snapshot_info": {},
    "project_restore_message": "",
    "project_restore_status": {},
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
    project_config = migrate_project_config(st.session_state.get("project_config") or build_default_project_config())
    available_columns = _get_available_columns()
    included_columns = [
        column
        for column in st.session_state.get("included_columns", [])
        if column in available_columns
    ]
    included_lookup = set(included_columns)
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
        "comparison_group_order": deepcopy(st.session_state.get("comparison_group_order", {})),
        "comparison_group_labels": deepcopy(st.session_state.get("comparison_group_labels", {})),
    }
    # 2026-05-19 BD: Keep the new layered comparison scheme in the exported
    # project config without changing the legacy comparison-column payload.
    project_config["comparison_scheme"] = deepcopy(
        st.session_state.get("comparison_scheme", EXTRA_DEFAULTS["comparison_scheme"])
    )
    project_config["variables"] = {
        "available_columns": available_columns,
        "included_columns": included_columns,
        "excluded_columns": [
            column
            for column in available_columns
            if column not in included_lookup
        ],
        "blacklist_removed_columns": list(st.session_state.get("removed_columns", [])),
        "restored_columns": list(st.session_state.get("restored_columns", [])),
    }
    project_config["question_types"] = {
        row.get("variable"): {
            "display_variable_name": row.get("display_variable_name", row.get("variable", "")),
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
        if isinstance(item, dict)
    }
    project_config["ad_hoc_crosstabs"] = deepcopy(
        st.session_state.get("adhoc_crosstabs_config", EXTRA_DEFAULTS["adhoc_crosstabs_config"])
    )
    project_config["banners"] = deepcopy(st.session_state.get("banner_config", {}))
    project_config["filters"] = deepcopy(st.session_state.get("global_filters", {}))
    project_config["weights"] = deepcopy(st.session_state.get("weighting_config", {}))
    project_config["stats"] = {
        "banners": deepcopy(st.session_state.get("banner_stat_config", EXTRA_DEFAULTS["banner_stat_config"])),
        "adhoc_crosstabs": deepcopy(st.session_state.get("adhoc_stat_config", EXTRA_DEFAULTS["adhoc_stat_config"])),
    }
    project_config["topline"] = deepcopy(st.session_state.get("topline_config", EXTRA_DEFAULTS["topline_config"]))
    project_config["change_logs"] = {
        "intake": list(st.session_state.get("intake_change_log", [])),
        "metadata": list(st.session_state.get("metadata_change_log", [])),
        "scale": list(st.session_state.get("scale_change_log", [])),
        "topline": list(st.session_state.get("topline_change_log", [])),
    }
    st.session_state.project_config = project_config


def load_project_template(template_payload: dict[str, Any]) -> None:
    """Apply a saved template to current session state.

    Inputs:
        template_payload: Configuration-only template payload. It must not
        contain respondent data.

    Outputs:
        Updates Streamlit session state in-place.
    """
    project_config, snapshot_info = unpack_project_payload(template_payload)

    st.session_state.project_config = project_config
    st.session_state.pending_project_config = deepcopy(project_config)
    st.session_state.pending_project_snapshot_info = deepcopy(snapshot_info)
    st.session_state.banner_config = deepcopy(project_config.get("banners", {}))
    st.session_state.adhoc_crosstabs_config = deepcopy(
        project_config.get("ad_hoc_crosstabs", EXTRA_DEFAULTS["adhoc_crosstabs_config"])
    )
    st.session_state.global_filters = deepcopy(project_config.get("filters", {}))
    st.session_state.weighting_config = deepcopy(project_config.get("weights", {}))
    stats_config = deepcopy(project_config.get("stats", {}))
    st.session_state.banner_stat_config = deepcopy(
        stats_config.get("banners", EXTRA_DEFAULTS["banner_stat_config"])
    )
    st.session_state.adhoc_stat_config = deepcopy(
        stats_config.get("adhoc_crosstabs", EXTRA_DEFAULTS["adhoc_stat_config"])
    )
    st.session_state.stat_config = deepcopy(st.session_state.banner_stat_config)
    st.session_state.scale_mappings = deepcopy(project_config.get("scales", {}))
    st.session_state.net_definitions = deepcopy(project_config.get("nets", {}))
    st.session_state.custom_variables = _custom_variables_from_config(project_config.get("custom_variables", {}))
    st.session_state.topline_config = deepcopy(project_config.get("topline", EXTRA_DEFAULTS["topline_config"]))
    # 2026-05-19 BD: Restore layered comparison rules from saved templates.
    st.session_state.comparison_scheme = deepcopy(
        project_config.get("comparison_scheme", EXTRA_DEFAULTS["comparison_scheme"])
    )
    st.session_state.comparison_group_labels = deepcopy(
        project_config.get("data", {}).get("comparison_group_labels", {})
    )
    st.session_state.template_upload_message = "Project settings loaded. Process the matching data file in Data Intake to restore the working project."
    st.session_state.project_restore_message = ""
    st.session_state.project_restore_status = {}


def export_project_template() -> str:
    """Serialize the current project configuration as JSON text.

    Returns:
        A JSON string that contains configuration only and excludes data rows.
    """
    sync_project_config_from_session()
    snapshot = build_project_snapshot(st.session_state.project_config)
    return json.dumps(snapshot, indent=2, default=str)


def _get_available_columns() -> list[str]:
    """Return the current uploaded-data columns without touching row data."""
    survey_df = st.session_state.get("survey_df")
    if hasattr(survey_df, "columns"):
        return list(survey_df.columns)
    return list(st.session_state.get("comparison_options", []))


def _string_list(value: Any) -> list[str]:
    """Return a cleaned list of string values from a saved config field."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _reconcile_included_columns(
    project_config: dict[str, Any],
    available_columns: list[str],
) -> tuple[list[str], list[str]]:
    """Restore included questions/variables against the current data schema."""
    variables_config = project_config.get("variables", {})
    saved_included = _string_list(variables_config.get("included_columns"))
    saved_available = _string_list(variables_config.get("available_columns"))
    if not saved_included:
        return available_columns.copy(), []

    available_lookup = set(available_columns)
    included_columns = [column for column in saved_included if column in available_lookup]
    missing_columns = [column for column in saved_included if column not in available_lookup]

    if saved_available:
        saved_available_lookup = set(saved_available)
        included_columns.extend(
            column
            for column in available_columns
            if column not in saved_available_lookup and column not in included_columns
        )

    if not included_columns:
        included_columns = available_columns.copy()

    return list(dict.fromkeys(included_columns)), missing_columns


def prepare_project_config_for_loaded_data(
    project_config: dict[str, Any],
    default_comparison_col: str | None,
) -> tuple[str | None, dict[str, Any]]:
    """Apply data-shaping parts of a saved config before comparison rebuild."""
    migrated_config = migrate_project_config(project_config)
    available_columns = _get_available_columns()
    included_columns, missing_included = _reconcile_included_columns(migrated_config, available_columns)

    saved_comparison_col = migrated_config.get("data", {}).get("comparison_col")
    comparison_col = saved_comparison_col if saved_comparison_col in available_columns else default_comparison_col
    if comparison_col and comparison_col not in included_columns:
        included_columns = [comparison_col, *included_columns]

    st.session_state.included_columns = included_columns
    st.session_state.comparison_col = comparison_col
    st.session_state.cell_col = comparison_col

    return comparison_col, {
        "missing_included_variables": missing_included,
        "comparison_restored": bool(saved_comparison_col and saved_comparison_col == comparison_col),
        "comparison_fallback": saved_comparison_col if saved_comparison_col and saved_comparison_col != comparison_col else "",
    }


def _restore_question_metadata(
    current_metadata: list[dict[str, Any]],
    project_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge saved audit edits onto freshly inferred metadata rows."""
    saved_question_types = project_config.get("question_types", {})
    if not isinstance(saved_question_types, dict):
        return current_metadata, []

    restored_rows: list[dict[str, Any]] = []
    current_variables: set[str] = set()
    for row in current_metadata:
        variable = row.get("variable")
        current_variables.add(variable)
        saved_row = saved_question_types.get(variable)
        if not isinstance(saved_row, dict):
            restored_rows.append(row)
            continue

        restored_row = deepcopy(row)
        display_name = saved_row.get("display_variable_name")
        question_text = saved_row.get("question_text")
        question_type = saved_row.get("question_type")
        if isinstance(display_name, str) and display_name:
            restored_row["display_variable_name"] = display_name
        if isinstance(question_text, str) and question_text:
            restored_row["question_label"] = question_text
        if isinstance(question_type, str) and question_type:
            restored_row["detected_type"] = question_type
            restored_row["include"] = question_type != "Ignore"

        if "answer_choices" in saved_row:
            saved_choices = saved_row.get("answer_choices")
            if isinstance(saved_choices, list):
                answer_choices = [choice for choice in saved_choices if isinstance(choice, str) and choice]
            elif isinstance(saved_choices, str):
                answer_choices = parse_answer_choices(saved_choices)
            else:
                answer_choices = []
            restored_row["answer_choices_list"] = answer_choices
            restored_row["answer_choices"] = serialize_answer_choices(answer_choices)

        restored_rows.append(restored_row)

    missing_metadata = [
        variable
        for variable in saved_question_types
        if variable not in current_variables
    ]
    return restored_rows, missing_metadata


def _filter_mapping_by_current_variables(
    saved_mapping: Any,
    current_variables: set[str],
) -> dict[str, Any]:
    """Keep saved variable-keyed config entries that still exist."""
    if not isinstance(saved_mapping, dict):
        return {}
    return {
        variable: deepcopy(value)
        for variable, value in saved_mapping.items()
        if variable in current_variables
    }


def _custom_variables_from_config(saved_custom_variables: Any) -> list[dict[str, Any]]:
    """Return saved custom variable records from current or legacy config shapes."""
    if isinstance(saved_custom_variables, dict):
        return [
            deepcopy(value)
            for value in saved_custom_variables.values()
            if isinstance(value, dict)
        ]
    if isinstance(saved_custom_variables, list):
        return [
            deepcopy(value)
            for value in saved_custom_variables
            if isinstance(value, dict)
        ]
    return []


def _restore_comparison_order(project_config: dict[str, Any]) -> None:
    """Restore comparison labels and group order when saved values still exist."""
    data_config = project_config.get("data", {})
    saved_order = data_config.get("comparison_group_order", {})
    if isinstance(saved_order, dict) and saved_order:
        current_order = st.session_state.get("comparison_group_order", {})
        current_keys = set(current_order.keys())
        restored_order = {
            key: int(saved_order.get(key, index))
            for index, key in enumerate(saved_order, start=1)
            if key in current_keys
        }
        next_order = max(restored_order.values(), default=0) + 1
        for key, value in sorted(current_order.items(), key=lambda item: item[1]):
            if key not in restored_order:
                restored_order[key] = next_order
                next_order += 1
        if restored_order:
            st.session_state.comparison_group_order = dict(
                sorted(restored_order.items(), key=lambda item: item[1])
            )
            st.session_state.cell_sort_order = dict(st.session_state.comparison_group_order)

    saved_labels = data_config.get("comparison_group_labels", {})
    if isinstance(saved_labels, dict) and saved_labels:
        current_labels = st.session_state.get("comparison_group_labels", {})
        merged_labels = deepcopy(current_labels)
        for key, label in saved_labels.items():
            if key in current_labels or key in st.session_state.get("comparison_group_order", {}):
                merged_labels[key] = label
        st.session_state.comparison_group_labels = merged_labels


def apply_project_config_after_loaded_data(project_config: dict[str, Any]) -> dict[str, Any]:
    """Restore saved settings after the uploaded data has been processed."""
    migrated_config = migrate_project_config(project_config)
    current_metadata = list(st.session_state.get("question_metadata", []))
    restored_metadata, missing_metadata = _restore_question_metadata(current_metadata, migrated_config)
    st.session_state.question_metadata = restored_metadata
    current_variables = {
        row.get("variable")
        for row in restored_metadata
        if row.get("variable")
    }

    st.session_state.scale_mappings = _filter_mapping_by_current_variables(
        migrated_config.get("scales", {}),
        current_variables,
    )
    st.session_state.net_definitions = _filter_mapping_by_current_variables(
        migrated_config.get("nets", {}),
        current_variables,
    )
    st.session_state.custom_variables = _custom_variables_from_config(
        migrated_config.get("custom_variables", {})
    )
    st.session_state.banner_config = deepcopy(migrated_config.get("banners", {}))
    st.session_state.adhoc_crosstabs_config = deepcopy(
        migrated_config.get("ad_hoc_crosstabs", EXTRA_DEFAULTS["adhoc_crosstabs_config"])
    )
    st.session_state.global_filters = deepcopy(migrated_config.get("filters", {}))
    st.session_state.weighting_config = deepcopy(migrated_config.get("weights", {}))

    stats_config = deepcopy(migrated_config.get("stats", {}))
    st.session_state.banner_stat_config = deepcopy(
        stats_config.get("banners", EXTRA_DEFAULTS["banner_stat_config"])
    )
    st.session_state.adhoc_stat_config = deepcopy(
        stats_config.get("adhoc_crosstabs", EXTRA_DEFAULTS["adhoc_stat_config"])
    )
    st.session_state.stat_config = deepcopy(st.session_state.banner_stat_config)
    st.session_state.topline_config = deepcopy(migrated_config.get("topline", EXTRA_DEFAULTS["topline_config"]))

    comparison_scheme = sanitize_comparison_scheme(
        migrated_config.get("comparison_scheme", EXTRA_DEFAULTS["comparison_scheme"])
    )
    st.session_state.comparison_scheme = comparison_scheme
    _restore_comparison_order(migrated_config)

    change_logs = migrated_config.get("change_logs", {})
    if isinstance(change_logs, dict):
        st.session_state.intake_change_log = list(change_logs.get("intake", st.session_state.get("intake_change_log", [])))
        st.session_state.metadata_change_log = list(change_logs.get("metadata", []))
        st.session_state.scale_change_log = list(change_logs.get("scale", []))
        st.session_state.topline_change_log = list(change_logs.get("topline", []))

    st.session_state.scale_mapping_seed_version = max(
        int(st.session_state.get("scale_mapping_seed_version", 0)),
        1,
    )
    st.session_state.scale_mapping_editor_revision = int(
        st.session_state.get("scale_mapping_editor_revision", 0)
    ) + 1

    status = {
        "applied": True,
        "missing_question_metadata": missing_metadata,
        "restored_scale_mappings": len(st.session_state.scale_mappings),
        "restored_net_definitions": len(st.session_state.net_definitions),
    }
    st.session_state.project_restore_status = status
    st.session_state.project_restore_message = _build_restore_message(status)
    st.session_state.pending_project_config = None
    st.session_state.pending_project_snapshot_info = {}
    sync_project_config_from_session()
    return status


def _build_restore_message(status: dict[str, Any]) -> str:
    """Build a concise user-facing restore summary."""
    parts = ["Project settings restored from the saved file."]
    missing_count = len(status.get("missing_question_metadata", []))
    if missing_count:
        parts.append(f"{missing_count} saved question/variable setting(s) were skipped because the variable was not found in this data file.")
    return " ".join(parts)
