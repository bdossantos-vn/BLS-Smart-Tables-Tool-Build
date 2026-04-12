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
    confidence_interval = stat_config.get("confidence_interval", 95)
    if confidence_interval not in CONFIDENCE_INTERVAL_OPTIONS:
        issues.append("Confidence interval must be one of 80%, 90%, 95%, or 99%.")
    return issues


def build_statistical_setup_summary(stat_config: dict) -> dict:
    """Return a serializable summary of the stored statistical configuration."""
    confidence_interval = int(stat_config.get("confidence_interval", 95))
    return {
        "confidence_interval": confidence_interval,
        "alpha": CONFIDENCE_TO_ALPHA.get(confidence_interval, DEFAULT_ALPHA),
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
