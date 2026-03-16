"""Analysis configuration scaffolding for V1."""

from __future__ import annotations


def build_default_weighting_config() -> dict:
    """Return the default weighting scaffold."""
    return {
        "enabled": False,
        "weight_variable": "",
    }


def build_default_banner_config() -> dict:
    """Return the default banner scaffold."""
    return {
        "banner_variables": [],
    }


def build_default_stat_config() -> dict:
    """Return the default statistical configuration scaffold."""
    return {
        "alpha": 0.05,
        "enabled": True,
        "compare_to_control": True,
    }


def validate_analysis_config(
    weighting_config: dict,
    banner_config: dict,
    global_filters: dict,
) -> list[str]:
    """Validate the V1 analysis configuration scaffold."""
    issues: list[str] = []
    if weighting_config.get("enabled") and not weighting_config.get("weight_variable"):
        issues.append("Weighting is enabled but no weight variable is set.")
    if not isinstance(banner_config.get("banner_variables", []), list):
        issues.append("Banner variables must be stored as a list.")
    if not isinstance(global_filters, dict):
        issues.append("Global filters must be stored as a dictionary.")
    return issues
