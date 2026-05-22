"""Project configuration model helpers.

This module defines the central configuration object used across the app.
The object is stored in Streamlit session state and mirrors the product spec.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


PROJECT_CONFIG_TEMPLATE: dict[str, Any] = {
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
