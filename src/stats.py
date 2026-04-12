"""Statistical setup scaffolding for V1."""

from __future__ import annotations

DEFAULT_ALPHA = 0.05
CONFIDENCE_INTERVAL_OPTIONS = [80, 90, 95, 99]
CONFIDENCE_TO_ALPHA = {
    80: 0.20,
    90: 0.10,
    95: 0.05,
    99: 0.01,
}


def validate_statistical_setup(stat_config: dict) -> list[str]:
    """Validate the statistical configuration scaffold."""
    issues: list[str] = []
    confidence_intervals = stat_config.get("confidence_intervals", [95])
    if not isinstance(confidence_intervals, list) or not confidence_intervals:
        issues.append("Select at least one confidence interval.")
        return issues
    if len(confidence_intervals) > 2:
        issues.append("Select no more than two confidence intervals.")
    invalid_values = [value for value in confidence_intervals if value not in CONFIDENCE_INTERVAL_OPTIONS]
    if invalid_values:
        issues.append("Confidence interval must be one of 80%, 90%, 95%, or 99%.")
    return issues


def build_statistical_setup_summary(stat_config: dict) -> dict:
    """Return a serializable summary of the stored statistical configuration."""
    confidence_intervals = [
        int(value)
        for value in stat_config.get("confidence_intervals", [95])
        if value in CONFIDENCE_INTERVAL_OPTIONS
    ] or [95]
    return {
        "confidence_intervals": confidence_intervals,
        "alpha_values": [CONFIDENCE_TO_ALPHA.get(value, DEFAULT_ALPHA) for value in confidence_intervals],
        "enabled": bool(stat_config.get("enabled", True)),
        "comparison_scope": "Compare across all lowest banner-level groups",
        "planned_test": "independent two-sample z-test for proportions",
    }


def run_placeholder_significance() -> dict:
    """Return a V1 placeholder result without performing production significance testing."""
    return {
        "status": "not_run",
        "reason": "V1 reserves production statistical execution for a later iteration.",
    }
