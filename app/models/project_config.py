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
    "variables": {},
    "question_types": {},
    "scales": {},
    "nets": {},
    "custom_variables": {},
    "banners": {},
    "filters": {},
    "weights": {},
    "stats": {},
    "topline": {
        "variables": [],
        "include_lift": False,
        "include_significance_notes": True,
    },
}


def build_default_project_config() -> dict[str, Any]:
    """Return a fresh project config object.

    Returns:
        A deep copy of the default configuration template.
    """
    return deepcopy(PROJECT_CONFIG_TEMPLATE)

