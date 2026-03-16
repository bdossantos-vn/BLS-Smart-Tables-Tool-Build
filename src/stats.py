"""Statistical setup scaffolding for V1."""

from __future__ import annotations

DEFAULT_ALPHA = 0.05


def validate_statistical_setup(stat_config: dict) -> list[str]:
    """Validate the statistical configuration scaffold."""
    issues: list[str] = []
    alpha = stat_config.get("alpha", DEFAULT_ALPHA)
    if not isinstance(alpha, (int, float)) or alpha <= 0 or alpha >= 1:
        issues.append("Alpha must be a numeric value between 0 and 1.")
    return issues


def build_statistical_setup_summary(stat_config: dict) -> dict:
    """Return a serializable summary of the stored statistical configuration."""
    return {
        "alpha": stat_config.get("alpha", DEFAULT_ALPHA),
        "enabled": bool(stat_config.get("enabled", True)),
        "compare_to_control": bool(stat_config.get("compare_to_control", True)),
        "planned_test": "independent two-sample z-test for proportions",
    }


def run_placeholder_significance() -> dict:
    """Return a V1 placeholder result without performing production significance testing."""
    return {
        "status": "not_run",
        "reason": "V1 reserves production statistical execution for a later iteration.",
    }
