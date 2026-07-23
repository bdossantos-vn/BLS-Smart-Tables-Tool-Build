"""Statistical setup page."""

from __future__ import annotations

from copy import deepcopy

import streamlit as st

from src.config import (
    build_default_stat_config,
    build_stat_comparison_options,
    build_stat_notation_options,
)
from src.stats import CONFIDENCE_INTERVAL_OPTIONS, normalize_confidence_intervals, validate_statistical_setup


def _render_stat_section(title: str, session_key: str) -> None:
    """Render one statistical settings section."""
    if not st.session_state.get(session_key):
        st.session_state[session_key] = build_default_stat_config()

    config = deepcopy(st.session_state.get(session_key, {}))
    st.subheader(title)
    ci_values = normalize_confidence_intervals(config.get("confidence_intervals", [95]))
    left, right = st.columns(2)
    primary_ci = left.selectbox(
        f"{title} Confidence Interval (C.I)",
        options=CONFIDENCE_INTERVAL_OPTIONS,
        index=CONFIDENCE_INTERVAL_OPTIONS.index(ci_values[0]),
        format_func=lambda value: f"{value}%",
        key=f"{session_key}_primary_ci",
    )
    secondary_options = [""] + [value for value in CONFIDENCE_INTERVAL_OPTIONS if int(value) < int(primary_ci)]
    secondary_default = ci_values[1] if len(ci_values) > 1 else ""
    if secondary_default not in secondary_options:
        secondary_default = ""
    secondary_ci = right.selectbox(
        f"{title} Second C.I (Optional)",
        options=secondary_options,
        index=secondary_options.index(secondary_default) if secondary_default in secondary_options else 0,
        format_func=lambda value: f"{value}%" if value else "None",
        key=f"{session_key}_secondary_ci",
    )

    metric_col_1, metric_col_2, metric_col_3 = st.columns(3)
    include_percentage = metric_col_1.checkbox(
        "Include % in Export",
        value=bool(config.get("include_percentage", True)),
        key=f"{session_key}_include_percentage",
    )
    stored_comparison_scope = config.get("comparison_scope", "control_vs_test")
    include_stat_testing = metric_col_2.checkbox(
        "Include stat testing",
        value=bool(config.get("enabled", True)) and stored_comparison_scope != "none",
        key=f"{session_key}_include_stat_testing",
    )
    include_n_count = metric_col_3.checkbox(
        "Include N Count in Export",
        value=bool(config.get("include_n_count", False)),
        key=f"{session_key}_include_n_count",
    )
    include_lift = st.checkbox(
        "Include lift",
        value=bool(config.get("include_lift", False)),
        key=f"{session_key}_include_lift",
    )
    comparison_options = build_stat_comparison_options(st.session_state.get("comparison_col"))
    comparison_options = [option for option in comparison_options if option[0] != "none"]
    comparison_ids = [option_id for option_id, _ in comparison_options]
    comparison_scope = stored_comparison_scope if include_stat_testing else "none"
    if include_stat_testing and comparison_scope not in comparison_ids:
        comparison_scope = comparison_ids[0]
    if include_stat_testing:
        comparison_scope = st.selectbox(
            "Statistical Comparisons",
            options=comparison_ids,
            index=comparison_ids.index(comparison_scope),
            format_func=lambda value: dict(comparison_options).get(value, value),
            key=f"{session_key}_comparison_scope",
        )
    notation_options = build_stat_notation_options()
    notation_ids = [option_id for option_id, _ in notation_options]
    notation_location = config.get("notation_location", "appended_to_metric")
    if notation_location not in notation_ids:
        notation_location = notation_ids[0]
    if include_stat_testing:
        notation_location = st.selectbox(
            "Statistic Notation Location",
            options=notation_ids,
            index=notation_ids.index(notation_location),
            format_func=lambda value: dict(notation_options).get(value, value),
            key=f"{session_key}_notation_location",
        )

    selected_confidence_intervals = [int(primary_ci)]
    if secondary_ci:
        selected_confidence_intervals.append(int(secondary_ci))

    updated_config = {
        "confidence_intervals": normalize_confidence_intervals(selected_confidence_intervals),
        "alpha": config.get("alpha", 0.05),
        "enabled": include_stat_testing,
        "include_percentage": include_percentage,
        "include_n_count": include_n_count,
        "include_lift": include_lift,
        "comparison_scope": comparison_scope,
        "notation_location": notation_location,
    }
    st.session_state[session_key] = updated_config

    validation_target = {
        **updated_config,
        "confidence_intervals": updated_config["confidence_intervals"],
    }
    issues = validate_statistical_setup(validation_target)
    if issues:
        for issue in issues:
            st.warning(issue)
    else:
        st.success(f"{title} saved.")


def render() -> None:
    """Render the split statistical setup page."""
    st.header("11. Statistical Setup")
    _render_stat_section("Banner Settings", "banner_stat_config")
    st.divider()
    _render_stat_section("Custom AdHoc Crosstab Settings", "adhoc_stat_config")
    st.session_state.stat_config = deepcopy(st.session_state.get("banner_stat_config", build_default_stat_config()))
