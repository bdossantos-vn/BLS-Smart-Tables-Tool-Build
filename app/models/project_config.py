"""Project configuration model helpers.

This module defines the central configuration object used across the app.
The object is stored in Streamlit session state and mirrors the product spec.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any


PROJECT_CONFIG_SCHEMA_VERSION = 2
PROJECT_SNAPSHOT_SCHEMA_VERSION = 1
PROJECT_SNAPSHOT_KIND = "bls_smart_tables_project_settings"

PROJECT_CONFIG_TEMPLATE: dict[str, Any] = {
    "schema_version": PROJECT_CONFIG_SCHEMA_VERSION,
    "project": {
        "template_name": "",
        "setup_mode": "Start from scratch",
    },
    "data": {},
    # 2026-05-19 BD: Save layered comparison rules in templates so they can be
    # merged or replayed separately from respondent data.
    "comparison_scheme": {
        "enabled": False,
        "mode": "exclusive",
        "control_group_id": "",
        "groups": [],
    },
    "variables": {},
    "question_types": {},
    "scales": {},
    "nets": {},
    "custom_variables": {},
    "ad_hoc_crosstabs": {},
    "banners": {},
    "filters": {},
    "weights": {},
    "stats": {
        "banners": {},
        "adhoc_crosstabs": {},
    },
    "change_logs": {
        "intake": [],
        "metadata": [],
        "scale": [],
        "topline": [],
    },
    "topline": {
        "configured": False,
        "variables": [],
        "response_selections": {},
        "note_base_sections": {},
        "include_lift": False,
        "comparison_scope": "control_vs_test",
        "include_significance_notes": True,
    },
}


def build_default_project_config() -> dict[str, Any]:
    """Return a fresh project config object.

    Returns:
        A deep copy of the default configuration template.
    """
    return deepcopy(PROJECT_CONFIG_TEMPLATE)


def _deep_merge(default_value: Any, saved_value: Any) -> Any:
    """Merge a saved config value onto a default value without losing new keys."""
    if isinstance(default_value, dict) and isinstance(saved_value, dict):
        merged = deepcopy(default_value)
        for key, value in saved_value.items():
            if key in merged:
                merged[key] = _deep_merge(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    if isinstance(saved_value, type(default_value)) or default_value is None:
        return deepcopy(saved_value)
    return deepcopy(default_value)


def migrate_project_config(saved_config: dict[str, Any] | None) -> dict[str, Any]:
    """Return a current-schema project config from a saved or legacy payload."""
    migrated = build_default_project_config()
    if not isinstance(saved_config, dict):
        return migrated

    migrated = _deep_merge(migrated, saved_config)
    migrated["schema_version"] = PROJECT_CONFIG_SCHEMA_VERSION

    variables = migrated.setdefault("variables", {})
    if "available_columns" not in variables:
        variables["available_columns"] = []
    if "blacklist_removed_columns" not in variables:
        variables["blacklist_removed_columns"] = list(
            variables.get("removed_columns", variables.get("default_removed_columns", [])) or []
        )
    if "excluded_columns" not in variables:
        variables["excluded_columns"] = []

    data = migrated.setdefault("data", {})
    if "comparison_group_order" not in data:
        data["comparison_group_order"] = {}
    if "comparison_group_labels" not in data:
        data["comparison_group_labels"] = {}

    return migrated


def unpack_project_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Accept either a snapshot envelope or an older raw config payload."""
    if not isinstance(payload, dict):
        raise ValueError("Project settings file must contain a JSON object.")

    if payload.get("kind") == PROJECT_SNAPSHOT_KIND and isinstance(payload.get("project_config"), dict):
        info = {
            "kind": payload.get("kind"),
            "snapshot_schema_version": payload.get("schema_version"),
            "saved_at": payload.get("saved_at"),
            "source_filename": payload.get("source_filename"),
            "app": deepcopy(payload.get("app", {})),
        }
        return migrate_project_config(payload.get("project_config")), info

    info = {
        "kind": "legacy_project_config",
        "snapshot_schema_version": None,
        "saved_at": payload.get("saved_at"),
        "source_filename": payload.get("data", {}).get("uploaded_filename"),
        "app": {},
    }
    return migrate_project_config(payload), info


def build_project_snapshot(project_config: dict[str, Any], app_version: str = "") -> dict[str, Any]:
    """Wrap the current project config in a portable, versioned snapshot."""
    migrated_config = migrate_project_config(project_config)
    data_config = migrated_config.get("data", {})
    return {
        "kind": PROJECT_SNAPSHOT_KIND,
        "schema_version": PROJECT_SNAPSHOT_SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "source_filename": data_config.get("uploaded_filename"),
        "project_config": migrated_config,
        "app": {
            "name": "BLS Smart Tables Tool",
            "version": app_version,
            "project_config_schema_version": PROJECT_CONFIG_SCHEMA_VERSION,
        },
    }
