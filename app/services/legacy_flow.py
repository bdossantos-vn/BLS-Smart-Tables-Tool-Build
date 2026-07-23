"""Legacy page rendering logic preserved during the architecture refactor."""

from __future__ import annotations

from typing import Any
import hashlib
import json
import re

import pandas as pd
import streamlit as st

from app.components.multiselect import (
    safe_multiselect,
    sanitize_multiselect_session_values,
    valid_multiselect_values,
    widget_key_token,
)
from app.services.snowflake_service import (
    build_survey_options,
    get_snowflake_session,
    load_available_surveys,
)
from app.state.manager import (
    apply_project_config_after_loaded_data,
    prepare_project_config_for_loaded_data,
)
from src.cleaning import (
    extract_snowflake_label_maps,
    ingest_qualtrics_dataframe,
    ingest_qualtrics_excel,
    ingest_qualtrics_sav,
    ingest_snowflake_dataframe,
)
from src.io import get_excel_sheet_names
from src.respondents import is_internal_respondent_column, respondent_count
from src.config import (
    build_analysis_variable_catalog,
    build_default_banner_config,
    build_default_filter_branch,
    build_default_filter_condition,
    build_default_banner_row,
    build_default_filter_row,
    build_default_stat_config,
    build_default_weight_row,
    build_default_weighting_config,
    build_filter_operator_options,
    build_weight_variable_options,
    validate_analysis_config,
)
from src.comparisons import (
    COMPARISON_SCHEME_DISPLAY_NAME,
    COMPARISON_SCHEME_LEVEL,
    build_comparison_group_masks,
    build_default_comparison_group,
    build_default_comparison_scheme,
    detect_group_overlaps,
    materialize_comparison_variable,
    sanitize_comparison_scheme,
    summarize_comparison_groups,
)
from src.custom_vars import (
    BUILD_TYPES,
    build_complex_variable_record,
    build_question_lookup,
    build_simple_variable_record,
    compute_complex_variable_counts,
    compute_simple_variable_counts,
    list_custom_variable_summaries,
    CONDITION_OPERATORS,
    MATCH_LOGIC_OPTIONS,
    upsert_custom_variable,
    validate_complex_variable_definition,
    validate_simple_variable_definition,
)
from src.mapping import (
    build_scale_change_log,
    build_scale_mapping_editor_frame,
    build_scale_mapping_options,
    ensure_scale_mappings,
    identify_scale_questions,
    save_scale_mapping_editor,
    validate_scale_mapping_editor,
)
from src.nets import (
    NET_LABELS,
    build_net_editor_frame,
    save_net_editor_frame,
    toggle_net_column,
)
from src.metadata import (
    build_metadata_change_log_entry,
    build_question_metadata,
    get_metadata_editor_columns,
    get_display_variable_name,
    merge_metadata_editor_with_source,
    parse_answer_choices,
    prepare_metadata_editor_frame,
    restore_metadata_defaults,
    sanitize_metadata_editor,
)
from src.state import DEFAULT_STATE, init_session_state, reset_project_state
from src.stats import (
    CONFIDENCE_INTERVAL_OPTIONS,
    DEFAULT_ALPHA,
    build_statistical_setup_summary,
    normalize_confidence_intervals,
    run_placeholder_significance,
    validate_statistical_setup,
)
from src.tables import (
    build_placeholder_table_preview,
    describe_generation_readiness,
    generate_placeholder_tables,
)
from src.exporter import export_tables_to_excel_bytes
from src.utils import (
    dataframe_to_download_name,
    format_timestamp,
    normalize_text,
    questionnaire_variable_sort_key,
)


NAV_STEPS = [
    "1. Data Intake",
    "2. Survey Question Audit",
    "3. Scale Mapping & Polarity",
    "4. Net Definitions",
    "5. Custom Variable Builder",
    "6. Banner Configuration",
    "7. Filter Configuration",
    "8. Weighting Configuration",
    "9. Statistical Setup",
    "10. Table Generator & Excel Export",
]

MAX_COMPARISON_GROUPS = 20
SOURCE_VARIABLE_DELIMITER = "\n"


def _append_log(message: str) -> None:
    """Append a timestamped log message to the session log."""
    st.session_state.ingestion_log.append(f"[{format_timestamp()}] {message}")


def _append_intake_change(message: str) -> None:
    """Append a timestamped change-log entry for Page 2 intake actions."""
    st.session_state.intake_change_log.append(f"[{format_timestamp()}] {message}")


def _summarize_choice_change(old_choices: str, new_choices: str, max_len: int = 140) -> str:
    """Build a compact before/after summary for answer-choice edits."""
    old_display = old_choices or "(blank)"
    new_display = new_choices or "(blank)"
    summary = f'"{old_display}" -> "{new_display}"'
    if len(summary) <= max_len:
        return summary
    return f"{len(parse_answer_choices(old_choices))} choice(s) -> {len(parse_answer_choices(new_choices))} choice(s)"


def _reset_custom_variable_builder_state() -> None:
    """Clear custom-variable builder inputs after a successful save."""
    for key in [
        "custom_var_name",
        "custom_var_simple_source",
        "custom_var_simple_fallback_mode",
        "custom_var_simple_fallback_label",
        "custom_var_complex_fallback_mode",
        "custom_var_complex_fallback_label",
    ]:
        st.session_state[key] = ""

    for key in [
        "custom_var_build_type",
        "custom_var_edit_name",
    ]:
        st.session_state[key] = BUILD_TYPES[0] if key == "custom_var_build_type" else None

    st.session_state.custom_var_edit_name = None
    st.session_state.custom_var_build_type = BUILD_TYPES[0]
    st.session_state.custom_var_bucket_count = 2
    st.session_state.custom_var_simple_source = ""
    st.session_state.custom_var_simple_fallback_mode = "Ignore / Missing"
    st.session_state.custom_var_simple_fallback_label = ""
    st.session_state.custom_var_complex_fallback_mode = "Ignore / Missing"
    st.session_state.custom_var_complex_fallback_label = ""

    for bucket_index in range(8):
        st.session_state[f"custom_bucket_label_{bucket_index}"] = ""
        st.session_state[f"custom_bucket_match_logic_{bucket_index}"] = MATCH_LOGIC_OPTIONS[0]
        st.session_state[f"custom_bucket_condition_count_{bucket_index}"] = 1
        st.session_state[f"custom_bucket_simple_choices_{bucket_index}"] = []
        for condition_index in range(6):
            st.session_state[f"custom_condition_variable_{bucket_index}_{condition_index}"] = ""
            st.session_state[f"custom_condition_operator_{bucket_index}_{condition_index}"] = ""
            st.session_state[f"custom_condition_choices_{bucket_index}_{condition_index}"] = []


def _load_custom_variable_into_builder(record: dict[str, Any]) -> None:
    """Load a saved custom variable back into the builder form for editing."""
    _reset_custom_variable_builder_state()
    st.session_state.custom_var_edit_name = record.get("name")
    st.session_state.custom_var_build_type = record.get("builder_type", BUILD_TYPES[0])
    st.session_state.custom_var_name = record.get("name", "")
    st.session_state.custom_var_bucket_count = int(record.get("bucket_count", 2) or 2)
    if record.get("builder_type") == "Simple Variable":
        source_variables = list(record.get("source_variables", []))
        st.session_state.custom_var_simple_source = source_variables[0] if source_variables else ""
        st.session_state.custom_var_simple_fallback_mode = record.get("fallback_mode", "Ignore / Missing")
        st.session_state.custom_var_simple_fallback_label = record.get("fallback_label", "")
        for index, bucket in enumerate(record.get("buckets", [])):
            st.session_state[f"custom_bucket_label_{index}"] = bucket.get("label", "")
            st.session_state[f"custom_bucket_simple_choices_{index}"] = list(bucket.get("choices", []))
    else:
        st.session_state.custom_var_complex_fallback_mode = record.get("fallback_mode", "Ignore / Missing")
        st.session_state.custom_var_complex_fallback_label = record.get("fallback_label", "")
        for index, bucket in enumerate(record.get("buckets", [])):
            st.session_state[f"custom_bucket_label_{index}"] = bucket.get("label", "")
            st.session_state[f"custom_bucket_match_logic_{index}"] = bucket.get("match_logic", MATCH_LOGIC_OPTIONS[0])
            st.session_state[f"custom_bucket_condition_count_{index}"] = int(
                bucket.get("condition_count", len(bucket.get("conditions", [])) or 1)
            )
            for condition_index, condition in enumerate(bucket.get("conditions", [])):
                st.session_state[f"custom_condition_variable_{index}_{condition_index}"] = condition.get("variable", "")
                st.session_state[f"custom_condition_operator_{index}_{condition_index}"] = condition.get(
                    "operator",
                    "",
                )
                st.session_state[f"custom_condition_choices_{index}_{condition_index}"] = list(
                    condition.get("choices", [])
                )


def _build_filter_value_options(
    variable: str,
    question_lookup: dict[str, dict[str, Any]],
    custom_variables: list[dict[str, Any]],
    comparison_col: str | None = None,
    comparison_groups: dict[str, int] | None = None,
) -> list[str]:
    """Return selectable filter values for a variable."""
    if not variable:
        return []
    if comparison_col and normalize_text(variable) == normalize_text(comparison_col):
        return [group for group in (comparison_groups or {}).keys() if normalize_text(group)]
    if variable in question_lookup:
        return list(dict.fromkeys(
            normalize_text(value)
            for value in question_lookup[variable].get("answer_choices_list", [])
            if normalize_text(value)
        ))
    for record in custom_variables:
        if normalize_text(record.get("name")) == normalize_text(variable):
            return [normalize_text(bucket.get("label")) for bucket in record.get("buckets", []) if normalize_text(bucket.get("label"))]
    return []


def _build_filter_value_display_labels(
    variable: str,
    value_options: list[str],
    comparison_col: str | None = None,
    comparison_group_labels: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return display labels for selectable values without changing their meaning."""
    return {value: value for value in value_options}


def _valid_multiselect_values(values: list[Any], options: list[str]) -> list[str]:
    """Return nonblank selected values that are still available options."""
    return valid_multiselect_values(values, options)


def _sanitize_multiselect_session_values(key: str, options: list[str]) -> None:
    """Remove blank/stale values from a Streamlit multiselect before rendering."""
    sanitize_multiselect_session_values(key, options)


def _widget_key_token(value: object) -> str:
    """Return a compact token for variable-scoped Streamlit widget keys."""
    return widget_key_token(value)


def _layered_condition_default_values(
    condition_values: list[Any],
    value_options: list[str],
    variable: str,
    group_label: str,
    group_id: str,
    comparison_col: str | None,
) -> list[str]:
    """Return valid defaults, repairing blank CELL group values when possible."""
    valid_values = _valid_multiselect_values(condition_values, value_options)
    if valid_values:
        return valid_values

    is_comparison_variable = normalize_text(variable) == normalize_text(comparison_col)
    is_cell_variable = normalize_text(variable).casefold() == "cell"
    if not is_comparison_variable and not is_cell_variable:
        return []

    option_lookup = {
        normalize_text(option).casefold(): option
        for option in value_options
        if normalize_text(option)
    }
    for candidate in [group_label, group_id]:
        repaired_value = option_lookup.get(normalize_text(candidate).casefold())
        if repaired_value:
            return [repaired_value]
    return []


def _normalize_filter_targets(targets: list[str], apply_targets: list[str]) -> list[str]:
    """Normalize filter targets while keeping `All Tables` exclusive."""
    valid_targets = [target for target in targets if target in apply_targets]
    if "Total" in targets and "All Tables" not in valid_targets and "All Tables" in apply_targets:
        valid_targets = ["All Tables", *valid_targets]
    if "All Tables" in valid_targets:
        return ["All Tables"]
    return valid_targets


def _coerce_filter_rows(existing_rows: list[dict[str, Any]], desired_count: int) -> list[dict[str, Any]]:
    """Upgrade older saved filter rows and match the requested row count."""
    upgraded_rows: list[dict[str, Any]] = []
    for row in existing_rows[:desired_count]:
        if "branches" in row:
            branches = []
            for branch in row.get("branches", []):
                conditions = [
                    {
                        "variable": normalize_text(condition.get("variable")),
                        "operator": normalize_text(condition.get("operator")),
                        "values": list(condition.get("values", [])),
                    }
                    for condition in branch.get("conditions", [])
                ] or [build_default_filter_condition()]
                branches.append(
                    {
                        "name": normalize_text(branch.get("name")),
                        "match_logic": normalize_text(branch.get("match_logic")) or "ALL",
                        "conditions": conditions,
                    }
                )
            upgraded_rows.append(
                {
                    "name": normalize_text(row.get("name")),
                    "branches": branches or [build_default_filter_branch()],
                    "applies_to": list(row.get("applies_to", [])),
                }
            )
        elif "conditions" in row:
            conditions = [
                {
                    "variable": normalize_text(condition.get("variable")),
                    "operator": normalize_text(condition.get("operator")),
                    "values": list(condition.get("values", [])),
                }
                for condition in row.get("conditions", [])
            ] or [build_default_filter_condition()]
            upgraded_rows.append(
                {
                    "name": normalize_text(row.get("name")),
                    "branches": [
                        {
                            "name": "",
                            "match_logic": normalize_text(row.get("match_logic")) or "ALL",
                            "conditions": conditions,
                        }
                    ],
                    "applies_to": list(row.get("applies_to", [])),
                }
            )
        else:
            upgraded_rows.append(
                {
                    "name": "",
                    "branches": [
                        {
                            "name": "",
                            "match_logic": "ALL",
                            "conditions": [
                                {
                                    "variable": normalize_text(row.get("variable")),
                                    "operator": normalize_text(row.get("operator")),
                                    "values": list(row.get("values", [])),
                                }
                            ],
                        }
                    ],
                    "applies_to": list(row.get("applies_to", [])),
                }
            )

    while len(upgraded_rows) < desired_count:
        upgraded_rows.append(build_default_filter_row())
    return upgraded_rows[:desired_count]


def render_sidebar() -> str:
    """Render global sidebar controls and return the selected workflow step."""
    with st.sidebar:
        st.title("BLS Smart Tables Tool")
        if "nav_step" not in st.session_state or st.session_state.nav_step not in NAV_STEPS:
            st.session_state.nav_step = NAV_STEPS[0]
        current_index = NAV_STEPS.index(st.session_state.nav_step)
        step = st.radio("Workflow", NAV_STEPS, index=current_index)
        st.session_state.nav_step = step
        st.divider()
        if "confirm_new_project" not in st.session_state:
            st.session_state.confirm_new_project = False

        if st.button("Start New Project", type="secondary", use_container_width=True):
            st.session_state.confirm_new_project = True
            st.rerun()

        if st.session_state.get("confirm_new_project"):
            st.warning(
                "Starting a new project will delete your current progress and data, and return you to step 1 to upload a new file. Continue"
            )
            confirm_left, confirm_right = st.columns(2)
            with confirm_left:
                if st.button("Yes", use_container_width=True, key="confirm_start_new_project_yes"):
                    reset_project_state()
                    st.session_state.nav_step = NAV_STEPS[0]
                    st.session_state.confirm_new_project = False
                    if "qualtrics_upload" in st.session_state:
                        del st.session_state["qualtrics_upload"]
                    for key in ["data_source_radio", "snowflake_survey_select"]:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.rerun()
            with confirm_right:
                if st.button("No", use_container_width=True, key="confirm_start_new_project_no"):
                    st.session_state.confirm_new_project = False
                    st.rerun()
    return step


def can_advance_from_step(step: str) -> bool:
    """Return whether the current step is ready to move forward."""
    cleaned_df = st.session_state.get("cleaned_df")
    question_metadata = st.session_state.get("question_metadata", [])

    if step == "1. Data Intake":
        return (
            isinstance(cleaned_df, pd.DataFrame)
            and not cleaned_df.empty
            and bool(st.session_state.get("comparison_configured"))
        )
    if step == "2. Survey Question Audit":
        return bool(question_metadata)
    if step == "3. Scale Mapping & Polarity":
        scale_questions = identify_scale_questions(question_metadata)
        if not scale_questions:
            return True
        mapped_variables = set(st.session_state.get("scale_mappings", {}).keys())
        required_variables = {row["variable"] for row in scale_questions}
        return required_variables.issubset(mapped_variables)
    if step in {
        "4. Net Definitions",
        "5. Custom Variable Builder",
        "6. Banner Configuration",
        "7. Filter Configuration",
        "8. Weighting Configuration",
        "9. Statistical Setup",
    }:
        return True
    return False


def render_page_navigation(current_step: str) -> None:
    """Render previous/next page buttons for the guided workflow."""
    current_index = NAV_STEPS.index(current_step)
    left, _, right = st.columns([1, 3, 1])
    with left:
        if current_index > 0 and st.button("Back", use_container_width=True, key=f"back_{current_step}"):
            st.session_state.nav_step = NAV_STEPS[current_index - 1]
            st.rerun()
    with right:
        if current_index < len(NAV_STEPS) - 1 and can_advance_from_step(current_step):
            if st.button(
                "Next",
                use_container_width=True,
                key=f"next_{current_step}",
            ):
                st.session_state.nav_step = NAV_STEPS[current_index + 1]
                st.rerun()


def _build_cell_summary_frame(cleaned_df: pd.DataFrame, cell_col: str) -> pd.DataFrame:
    """Build a compact intake summary table with control first."""
    counts = (
        cleaned_df[cell_col]
        .astype(str)
        .str.strip()
        .value_counts()
        .rename_axis("Cell")
        .reset_index(name="N")
    )
    if counts.empty:
        return counts
    counts["sort_group"] = counts["Cell"].str.contains("control", case=False, na=False).map(
        lambda is_control: 0 if is_control else 1
    )
    counts = counts.sort_values(["sort_group", "Cell"]).drop(columns=["sort_group"]).reset_index(drop=True)
    return counts


def _resolve_default_comparison(column_names: list[str], detected_cell: str | None, preferred: str | None) -> str | None:
    """Choose the best comparison variable default for the current dataset."""
    if preferred and preferred in column_names:
        return preferred
    if detected_cell and detected_cell in column_names:
        return detected_cell
    return None


def _sort_comparison_values(values: list[str], comparison_col: str | None) -> list[str]:
    """Return comparison values in a stable and analyst-friendly order."""
    cleaned_values = [normalize_text(value) for value in values if normalize_text(value)]
    if not comparison_col:
        return sorted(cleaned_values, key=str.lower)

    if normalize_text(comparison_col).lower() == "cell":
        numeric_pairs: list[tuple[int, str]] = []
        non_numeric_values: list[str] = []
        for value in cleaned_values:
            try:
                numeric_pairs.append((int(float(value)), value))
            except (TypeError, ValueError):
                non_numeric_values.append(value)
        if numeric_pairs and len(numeric_pairs) == len(cleaned_values):
            return [value for _, value in sorted(numeric_pairs, key=lambda item: item[0])]

    if any("control" in value.lower() for value in cleaned_values):
        return sorted(
            cleaned_values,
            key=lambda value: (0 if "control" in value.lower() else 1, value.lower()),
        )
    return sorted(cleaned_values, key=str.lower)


def _default_comparison_group_labels(
    cleaned_df: pd.DataFrame,
    comparison_col: str | None,
    existing_labels: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build default analyst-facing labels for comparison groups.

    Inputs:
        cleaned_df: Current analysis dataframe.
        comparison_col: Selected comparison variable.
        existing_labels: Previously saved labels to preserve when possible.

    Outputs:
        Mapping of raw comparison values to display labels.
    """
    if not comparison_col:
        return {"Total": "Total"}

    existing_labels = {normalize_text(key): normalize_text(value) for key, value in (existing_labels or {}).items()}
    values = cleaned_df[comparison_col].dropna().map(normalize_text).tolist()
    ordered_values = _sort_comparison_values(list(dict.fromkeys(values)), comparison_col)
    labels: dict[str, str] = {}

    is_cell = normalize_text(comparison_col).lower() == "cell"
    numeric_lookup: dict[str, int] = {}
    if is_cell:
        try:
            numeric_lookup = {value: int(float(value)) for value in ordered_values}
        except (TypeError, ValueError):
            numeric_lookup = {}

    for value in ordered_values:
        preserved = existing_labels.get(value)
        if preserved:
            labels[value] = preserved
            continue
        if is_cell and value in numeric_lookup:
            number = numeric_lookup[value]
            if number == 0:
                labels[value] = "Control"
            elif len(ordered_values) == 2 and set(numeric_lookup.values()) == {0, 1} and number == 1:
                labels[value] = "Test"
            elif number >= 1:
                labels[value] = f"Test {number}"
            else:
                labels[value] = value
        else:
            labels[value] = value
    return labels


def _default_comparison_group_order(cleaned_df: pd.DataFrame, comparison_col: str | None) -> dict[str, int]:
    """Build the default row order for the selected comparison variable."""
    if not comparison_col:
        return {"Total": 1}

    values = [normalize_text(value) for value in cleaned_df[comparison_col].dropna().tolist()]
    unique_values = list(dict.fromkeys(value for value in values if value))
    ordered = _sort_comparison_values(unique_values, comparison_col)
    return {value: index for index, value in enumerate(ordered, start=1)}


def _apply_comparison_selection(comparison_col: str | None) -> None:
    """Apply the selected comparison variable and rebuild the working dataset."""
    survey_df = st.session_state.survey_df
    if not isinstance(survey_df, pd.DataFrame) or survey_df.empty:
        return

    selected_columns = st.session_state.get("included_columns", list(survey_df.columns))
    selected_columns = [column for column in selected_columns if column in survey_df.columns]
    if comparison_col and comparison_col not in selected_columns:
        selected_columns = [comparison_col, *selected_columns]
    if not selected_columns:
        raise ValueError("Select at least one included column.")

    filtered_df = survey_df.copy()
    rows_removed = 0

    if comparison_col:
        filtered_df[comparison_col] = filtered_df[comparison_col].map(normalize_text)
        blank_mask = filtered_df[comparison_col] == ""
        rows_removed = int(blank_mask.sum())
        filtered_df = filtered_df.loc[~blank_mask].reset_index(drop=True)

    filtered_df = filtered_df.loc[:, [column for column in selected_columns if column in filtered_df.columns]].copy()

    if filtered_df.empty:
        raise ValueError("The selected comparison variable removed all rows. Choose a different option.")

    st.session_state.cleaned_df = filtered_df
    previous_comparison_col = st.session_state.get("comparison_col")
    previous_scheme = sanitize_comparison_scheme(st.session_state.get("comparison_scheme", {}))
    st.session_state.comparison_col = comparison_col
    st.session_state.cell_col = comparison_col
    st.session_state.comparison_rows_removed = rows_removed
    st.session_state.comparison_configured = True
    st.session_state.comparison_group_order = _default_comparison_group_order(filtered_df, comparison_col)
    st.session_state.comparison_group_labels = _default_comparison_group_labels(
        filtered_df,
        comparison_col,
        st.session_state.get("comparison_group_labels", {}),
    )
    st.session_state.locked_cell_bases = {
        row["Raw Value"]: int(row["N"])
        for row in _build_comparison_summary_frame(filtered_df, comparison_col).to_dict(orient="records")
    }
    st.session_state.cell_sort_order = dict(st.session_state.comparison_group_order)
    st.session_state.cell_letter_map = {}
    question_text_labels = st.session_state.get("question_text_labels", {}) or st.session_state.question_labels
    st.session_state.question_metadata = build_question_metadata(
        filtered_df,
        question_text_labels,
        comparison_col,
        st.session_state.get("source_answer_choices", {}),
        st.session_state.get("source_question_types", {}),
    )
    if st.session_state.get("data_source_type") == "snowflake":
        _apply_snowflake_display_variable_names(st.session_state.question_metadata, st.session_state.question_labels)
        _sync_question_metadata_from_intake_labels(
            st.session_state.question_metadata,
            list(filtered_df.columns),
            st.session_state.question_labels,
            question_text_labels,
        )
    st.session_state.question_metadata = _order_question_metadata_by_columns(
        st.session_state.question_metadata,
        st.session_state.get("included_columns", []),
    )
    st.session_state.scale_mappings = {}
    # 2026-05-19 BD: Comparison variable changes now seed the unified layered
    # setup instead of requiring a separate "apply variable" then "layered" step.
    if not comparison_col:
        st.session_state.comparison_scheme = build_default_comparison_scheme()
    elif (
        previous_scheme.get("enabled")
        and normalize_text(previous_comparison_col) == normalize_text(comparison_col)
    ):
        st.session_state.comparison_scheme = previous_scheme
    else:
        st.session_state.comparison_scheme = _build_default_layered_scheme_from_comparison(
            filtered_df,
            comparison_col,
        )
    _append_materialized_comparison_variable()


def _build_comparison_summary_frame(cleaned_df: pd.DataFrame, comparison_col: str | None) -> pd.DataFrame:
    """Build the summary table for the selected comparison variable."""
    if not comparison_col:
        return pd.DataFrame([{"Raw Value": "Total", "Display Label": "Total", "N": respondent_count(cleaned_df)}])

    values = cleaned_df[comparison_col].map(normalize_text)
    rows = [
        {
            "Raw Value": value,
            "N": respondent_count(cleaned_df, values == value),
        }
        for value in values.dropna().unique().tolist()
        if value
    ]
    counts = pd.DataFrame(rows)
    if counts.empty:
        return pd.DataFrame(columns=["Raw Value", "N", "Display Label"])
    order_map = st.session_state.get("comparison_group_order", {})
    label_map = st.session_state.get("comparison_group_labels", {})
    counts["Display Label"] = counts["Raw Value"].map(lambda value: label_map.get(value, value))
    if order_map:
        counts["sort_order"] = counts["Raw Value"].map(lambda value: order_map.get(value, 9999))
        counts = counts.sort_values(["sort_order", "Raw Value"]).drop(columns=["sort_order"]).reset_index(drop=True)
    else:
        counts = counts.sort_values("Raw Value").reset_index(drop=True)
    return counts


def _build_comparison_order_editor(cleaned_df: pd.DataFrame, comparison_col: str | None) -> pd.DataFrame:
    """Build an editable order table for comparison groups."""
    summary = _build_comparison_summary_frame(cleaned_df, comparison_col)
    order_map = st.session_state.get("comparison_group_order", {})
    summary["Sort Order"] = summary["Raw Value"].map(lambda value: order_map.get(value, 1)).astype(int)
    return summary[["Raw Value", "Display Label", "N", "Sort Order"]]


def _coerce_layered_comparison_groups(existing_groups: list[dict[str, Any]], desired_count: int) -> list[dict[str, Any]]:
    """Return a stable number of layered comparison group rows."""
    groups = list(existing_groups[:desired_count])
    while len(groups) < desired_count:
        groups.append(build_default_comparison_group(len(groups) + 1))
    return groups[:desired_count]


def _build_default_layered_scheme_from_comparison(
    cleaned_df: pd.DataFrame,
    comparison_col: str | None,
) -> dict[str, Any]:
    """Build an exclusive layered scheme from one comparison variable."""
    if not comparison_col or comparison_col not in cleaned_df.columns:
        return build_default_comparison_scheme()

    summary = _build_comparison_summary_frame(cleaned_df, comparison_col)
    groups: list[dict[str, Any]] = []
    control_group_id = ""
    for index, row in enumerate(summary.to_dict(orient="records"), start=1):
        raw_value = normalize_text(row.get("Raw Value"))
        display_label = normalize_text(row.get("Display Label")) or raw_value
        group_id = raw_value or f"group_{index}"
        is_control = normalize_text(display_label).lower() == "control" or "control" in raw_value.lower()
        if not control_group_id and (is_control or index == 1):
            role = "control"
            control_group_id = group_id
        else:
            role = "test"
        groups.append(
            {
                "id": group_id,
                "label": display_label,
                "role": role,
                "match_logic": "ALL",
                "conditions": [
                    {
                        "variable": comparison_col,
                        "operator": "Is exactly",
                        "values": [raw_value],
                    }
                ],
            }
        )

    # 2026-05-19 BD: The simple comparison-variable path now seeds the same
    # layered scheme editor, so analysts have one Comparison Setup workflow.
    return {
        "enabled": bool(groups and control_group_id),
        "mode": "exclusive",
        "control_group_id": control_group_id,
        "groups": groups,
    }


def _append_materialized_comparison_variable() -> None:
    """Append the saved comparison setup as a visible data column."""
    cleaned_df = st.session_state.get("cleaned_df")
    scheme = sanitize_comparison_scheme(st.session_state.get("comparison_scheme", {}))
    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty or not scheme.get("enabled"):
        return
    question_lookup = build_question_lookup(
        st.session_state.get("question_metadata", []),
        st.session_state.get("net_definitions", {}),
        st.session_state.get("scale_mappings", {}),
    )
    # 2026-05-19 BD: Append the finalized comparison setup as a visible
    # `Comparison Variable` column for downstream setup screens.
    updated_df = cleaned_df.copy()
    updated_df[COMPARISON_SCHEME_DISPLAY_NAME] = materialize_comparison_variable(
        updated_df,
        scheme,
        question_lookup,
        COMPARISON_SCHEME_DISPLAY_NAME,
    )
    st.session_state.cleaned_df = updated_df


def _render_layered_comparison_editor(cleaned_df: pd.DataFrame) -> None:
    """Render the unified rule-based comparison setup in Data Intake."""
    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty:
        return

    saved_scheme = sanitize_comparison_scheme(st.session_state.get("comparison_scheme", {}))
    if not saved_scheme.get("enabled") and st.session_state.get("comparison_col"):
        saved_scheme = _build_default_layered_scheme_from_comparison(
            cleaned_df,
            st.session_state.get("comparison_col"),
        )
    if not saved_scheme.get("enabled"):
        saved_scheme = {
            "enabled": True,
            "mode": "exclusive",
            "control_group_id": "group_1",
            "groups": [
                {**build_default_comparison_group(1), "role": "control", "label": "Control"},
                {**build_default_comparison_group(2), "role": "test", "label": "Test"},
            ],
        }

    st.caption(
        "Define the comparison groups used throughout reporting. Use exclusive mode when each respondent belongs to one group, "
        "or overlapping mode when respondents may qualify for more than one group."
    )
    mode_options = ["exclusive", "overlap"]
    mode = st.selectbox(
        "Comparison Mode",
        options=mode_options,
        index=mode_options.index(saved_scheme.get("mode", "exclusive")) if saved_scheme.get("mode", "exclusive") in mode_options else 0,
        format_func=lambda value: "Exclusive groups" if value == "exclusive" else "Overlapping groups",
        key="layered_comparison_mode",
    )
    group_count = int(
        st.number_input(
            "Number of Comparison Groups",
            min_value=2,
            max_value=MAX_COMPARISON_GROUPS,
            value=min(MAX_COMPARISON_GROUPS, max(2, len(saved_scheme.get("groups", [])) or 2)),
            step=1,
            key="layered_comparison_group_count",
        )
    )
    existing_groups = _coerce_layered_comparison_groups(list(saved_scheme.get("groups", [])), group_count)
    variable_catalog = build_analysis_variable_catalog(
        st.session_state.question_metadata,
        st.session_state.custom_variables,
        st.session_state.get("comparison_col"),
        st.session_state.get("comparison_scheme", {}),
    )
    variable_options = [item["id"] for item in variable_catalog if item["id"] in cleaned_df.columns]
    variable_labels = {item["id"]: item["label"] for item in variable_catalog}
    variable_types = {item["id"]: item.get("question_type", "") for item in variable_catalog}
    question_lookup = build_question_lookup(
        st.session_state.question_metadata,
        st.session_state.get("net_definitions", {}),
        st.session_state.get("scale_mappings", {}),
    )

    rendered_groups: list[dict[str, Any]] = []
    control_ids: list[str] = []
    for group_index, group in enumerate(existing_groups):
        group_id = normalize_text(group.get("id")) or f"group_{group_index + 1}"
        with st.container(border=True):
            st.markdown(f"**Group {group_index + 1}**")
            label_col, role_col, logic_col = st.columns([2, 1, 1])
            label = label_col.text_input(
                "Display Label",
                value=group.get("label", ""),
                key=f"layered_group_label_{group_index}",
                placeholder="Control" if group_index == 0 else f"Test Group {group_index}",
            )
            role_options = ["control", "test"]
            current_role = normalize_text(group.get("role")).lower() or ("control" if group_index == 0 else "test")
            if current_role not in role_options:
                current_role = "test"
            role = role_col.selectbox(
                "Role",
                options=role_options,
                index=role_options.index(current_role),
                format_func=lambda value: value.title(),
                key=f"layered_group_role_{group_index}",
            )
            match_logic = logic_col.selectbox(
                "Match Logic",
                options=MATCH_LOGIC_OPTIONS,
                index=MATCH_LOGIC_OPTIONS.index(group.get("match_logic", "ALL")) if group.get("match_logic", "ALL") in MATCH_LOGIC_OPTIONS else 0,
                key=f"layered_group_match_logic_{group_index}",
            )
            if role == "control":
                control_ids.append(group_id)

            condition_count = int(
                st.number_input(
                    "Number of Conditions",
                    min_value=1,
                    max_value=6,
                    value=max(1, len(group.get("conditions", [])) or 1),
                    step=1,
                    key=f"layered_group_condition_count_{group_index}",
                )
            )
            conditions = list(group.get("conditions", []))
            while len(conditions) < condition_count:
                conditions.append(build_default_filter_condition())
            rendered_conditions: list[dict[str, Any]] = []
            for condition_index, condition in enumerate(conditions[:condition_count]):
                cond_cols = st.columns([2, 1.4, 2])
                current_variable = normalize_text(condition.get("variable"))
                variable_choices = ["", *variable_options]
                variable = cond_cols[0].selectbox(
                    "Variable",
                    options=variable_choices,
                    index=variable_choices.index(current_variable) if current_variable in variable_choices else 0,
                    format_func=lambda value: variable_labels.get(value, value) if value else "Select variable",
                    key=f"layered_condition_variable_{group_index}_{condition_index}",
                )
                operator_options = ["", *build_filter_operator_options(variable_types.get(variable, ""))]
                current_operator = normalize_text(condition.get("operator"))
                operator = cond_cols[1].selectbox(
                    "Operator",
                    options=operator_options,
                    index=operator_options.index(current_operator) if current_operator in operator_options else 0,
                    key=f"layered_condition_operator_{group_index}_{condition_index}",
                )
                if variable_types.get(variable) == "Numeric Data":
                    numeric_default = ", ".join(str(value) for value in condition.get("values", []))
                    numeric_value = cond_cols[2].text_input(
                        "Value",
                        value=numeric_default,
                        key=f"layered_condition_numeric_value_{group_index}_{condition_index}",
                    )
                    values = [normalize_text(numeric_value)] if normalize_text(numeric_value) else []
                else:
                    value_options = _build_filter_value_options(
                        variable,
                        question_lookup,
                        st.session_state.custom_variables,
                        comparison_col=st.session_state.get("comparison_col"),
                        comparison_groups=st.session_state.get("comparison_group_order", {}),
                    )
                    value_display_labels = _build_filter_value_display_labels(
                        variable,
                        value_options,
                        st.session_state.get("comparison_col"),
                        st.session_state.get("comparison_group_labels", {}),
                    )
                    value_key = (
                        f"layered_condition_values_"
                        f"{group_index}_{condition_index}_{_widget_key_token(variable)}"
                    )
                    default_values = _layered_condition_default_values(
                        list(condition.get("values", [])),
                        value_options,
                        variable,
                        normalize_text(label),
                        group_id,
                        st.session_state.get("comparison_col"),
                    )
                    values = safe_multiselect(
                        "Values",
                        options=value_options,
                        default=default_values,
                        key=value_key,
                        reset_invalid_to_default=True,
                        format_func=lambda value, labels=value_display_labels: labels.get(value, value),
                    )
                rendered_conditions.append(
                    {
                        "variable": variable,
                        "operator": operator,
                        "values": values,
                    }
                )
            rendered_groups.append(
                {
                    "id": group_id,
                    "label": normalize_text(label),
                    "role": role,
                    "match_logic": match_logic,
                    "conditions": rendered_conditions,
                }
            )

    rendered_scheme = {
        "enabled": True,
        "mode": mode,
        "control_group_id": control_ids[0] if control_ids else "",
        "groups": rendered_groups,
    }
    preview_groups = build_comparison_group_masks(
        cleaned_df,
        rendered_scheme,
        question_lookup,
        st.session_state.get("comparison_col"),
        st.session_state.get("comparison_group_order", {}),
        st.session_state.get("comparison_group_labels", {}),
    )
    if preview_groups:
        st.write("Group bases")
        st.dataframe(summarize_comparison_groups(preview_groups, cleaned_df), hide_index=True, use_container_width=True)
        overlaps = detect_group_overlaps(preview_groups, cleaned_df)
        if overlaps:
            st.warning(
                "Overlap detected: "
                + "; ".join(
                    f"{row['left_label']} + {row['right_label']} share {row['overlap_n']} respondent(s)"
                    for row in overlaps
                )
            )
        else:
            st.success("No group overlap detected in the current cleaned data.")
    if not control_ids:
        st.info("No Control role selected. These will be treated as test cells; lift will be skipped.")

    validation_issues: list[str] = []
    if len(control_ids) > 1:
        validation_issues.append("Select no more than one Control group.")
    for group_index, group in enumerate(rendered_groups, start=1):
        if not normalize_text(group.get("label")):
            validation_issues.append(f"Group {group_index} needs a display label.")
        valid_conditions = [
            condition
            for condition in group.get("conditions", [])
            if normalize_text(condition.get("variable"))
            and normalize_text(condition.get("operator"))
            and condition.get("values")
        ]
        if not valid_conditions:
            validation_issues.append(f"Group {group_index} needs at least one complete condition.")
    if validation_issues:
        for issue in validation_issues:
            st.warning(issue)

    save_col, reset_col = st.columns(2)
    with save_col:
        if st.button("Save Comparison Setup", type="primary", use_container_width=True, disabled=bool(validation_issues)):
            # 2026-05-19 BD: Persist the single unified comparison setup, with
            # exclusive and overlapping groups both stored as comparison_scheme.
            st.session_state.comparison_scheme = sanitize_comparison_scheme(rendered_scheme)
            _append_materialized_comparison_variable()
            st.session_state.comparison_configured = True
            _append_intake_change("Comparison setup saved.")
            st.success("Comparison setup saved.")
            st.rerun()
    with reset_col:
        if st.button("Reset Groups", use_container_width=True):
            seeded_scheme = _build_default_layered_scheme_from_comparison(
                cleaned_df,
                st.session_state.get("comparison_col"),
            )
            if not seeded_scheme.get("enabled"):
                seeded_scheme = {
                    "enabled": True,
                    "mode": "exclusive",
                    "control_group_id": "group_1",
                    "groups": [
                        {**build_default_comparison_group(1), "role": "control", "label": "Control"},
                        {**build_default_comparison_group(2), "role": "test", "label": "Test"},
                    ],
                }
            st.session_state.comparison_scheme = seeded_scheme
            _append_materialized_comparison_variable()
            _append_intake_change("Comparison setup groups reset.")
            st.success("Comparison setup reset.")
            st.rerun()


def _current_included_count() -> int:
    """Return the current number of included questions/variables in the working dataset."""
    cleaned_df = st.session_state.get("cleaned_df")
    if isinstance(cleaned_df, pd.DataFrame):
        return len(_build_question_variable_groups(
            list(cleaned_df.columns),
            st.session_state.get("question_labels", {}),
            st.session_state.get("question_text_labels", {}),
        ))
    return 0


def _current_excluded_count() -> int:
    """Return the current total number of excluded questions/variables across intake controls."""
    survey_df = st.session_state.get("survey_df")
    survey_count = (
        len(_build_question_variable_groups(
            list(survey_df.columns),
            st.session_state.get("question_labels", {}),
            st.session_state.get("question_text_labels", {}),
        ))
        if isinstance(survey_df, pd.DataFrame)
        else 0
    )
    blacklist_catalog = st.session_state.get("blacklist_catalog", [])
    restored_columns = set(st.session_state.get("restored_columns", []))
    active_blacklist_count = sum(1 for column in blacklist_catalog if column not in restored_columns)
    included_count = _current_included_count()
    hidden_included_count = max(survey_count - included_count, 0)
    return active_blacklist_count + hidden_included_count


def _move_comparison_group(group_name: str, direction: str) -> None:
    """Move a comparison group in the configured display order."""
    order_map = dict(st.session_state.get("comparison_group_order", {}))
    ordered_names = [name for name, _ in sorted(order_map.items(), key=lambda item: item[1])]
    if group_name not in ordered_names:
        return

    current_index = ordered_names.index(group_name)
    if direction == "top":
        ordered_names.insert(0, ordered_names.pop(current_index))
    elif direction == "up" and current_index > 0:
        ordered_names[current_index - 1], ordered_names[current_index] = (
            ordered_names[current_index],
            ordered_names[current_index - 1],
        )
    elif direction == "down" and current_index < len(ordered_names) - 1:
        ordered_names[current_index + 1], ordered_names[current_index] = (
            ordered_names[current_index],
            ordered_names[current_index + 1],
        )
    elif direction == "bottom":
        ordered_names.append(ordered_names.pop(current_index))

    st.session_state.comparison_group_order = {
        name: index for index, name in enumerate(ordered_names, start=1)
    }
    st.session_state.cell_sort_order = dict(st.session_state.comparison_group_order)
    st.session_state.locked_cell_bases = {
        row["Raw Value"]: int(row["N"])
        for row in _build_comparison_summary_frame(
            st.session_state.cleaned_df,
            st.session_state.comparison_col,
        ).to_dict(orient="records")
    }


def _move_comparison_scheme_group(group_id: str, direction: str) -> None:
    """Move a saved unified comparison group in display/export order."""
    scheme = sanitize_comparison_scheme(st.session_state.get("comparison_scheme", {}))
    groups = list(scheme.get("groups", []))
    group_ids = [normalize_text(group.get("id")) for group in groups]
    normalized_group_id = normalize_text(group_id)
    if normalized_group_id not in group_ids:
        return

    current_index = group_ids.index(normalized_group_id)
    if direction == "up" and current_index > 0:
        groups[current_index - 1], groups[current_index] = groups[current_index], groups[current_index - 1]
    elif direction == "down" and current_index < len(groups) - 1:
        groups[current_index + 1], groups[current_index] = groups[current_index], groups[current_index + 1]
    else:
        return

    # 2026-05-19 BD: The Comparison Group Order panel now reorders the saved
    # comparison_scheme groups directly, matching Intake Summary and export.
    st.session_state.comparison_scheme = {
        **scheme,
        "groups": groups,
    }
    _append_materialized_comparison_variable()
    _append_intake_change("Comparison group order updated.")


def _build_blacklist_editor(blacklist_used: list[str], restored_columns: list[str]) -> pd.DataFrame:
    """Build the editable blacklist state table for Step 1."""
    restored_lookup = {value.lower() for value in restored_columns}
    rows = []
    for column in blacklist_used:
        rows.append(
            {
                "Column": column,
                "Excluded": column.lower() not in restored_lookup,
            }
        )
    return pd.DataFrame(rows)


def _numbered_question_group_base(variable: str) -> str | None:
    """Return a parent variable for numbered matrix or checkbox exports."""
    normalized = normalize_text(variable)
    if normalized.endswith("_TEXT"):
        return None
    match = re.match(r"^(.+)_\d+$", normalized)
    if not match:
        return None
    return match.group(1)


def _collapse_internal_whitespace(value: object) -> str:
    """Normalize labels for grouping without changing saved metadata."""
    return re.sub(r"\s+", " ", normalize_text(value)).strip()


def _common_text_prefix(values: list[str]) -> str:
    """Return the character prefix shared by all supplied values."""
    if not values:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while prefix and not value.startswith(prefix):
            prefix = prefix[:-1]
    return prefix


def _shared_question_stem(labels: list[str]) -> str:
    """Return a shared parent-question stem for repeated SAV labels."""
    normalized_labels = [_collapse_internal_whitespace(label) for label in labels if _collapse_internal_whitespace(label)]
    if len(normalized_labels) < 2:
        return ""

    prefix = _common_text_prefix(normalized_labels)
    if len(prefix) < 16:
        return ""

    split_at = -1
    for delimiter in [" - ", ". ", "? ", "! ", ": "]:
        index = prefix.rfind(delimiter)
        if index > split_at:
            split_at = index + len(delimiter)
    if split_at <= 0:
        return ""
    return prefix[:split_at].strip(" -:;.?!")


def _friendly_question_variable_label(variable: str, question_label: str) -> str:
    """Prefer source question text over raw IDs for intake display labels."""
    variable_name = normalize_text(variable)
    label = _collapse_internal_whitespace(question_label)
    if label and label.lower() != variable_name.lower():
        return label
    return variable_name


def _build_question_variable_groups(
    all_columns: list[str],
    question_labels: dict[str, str] | None = None,
    question_text_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Group raw variables into logical questions for intake include/exclude controls."""
    all_columns = [
        column
        for column in all_columns
        if not is_internal_respondent_column(column)
    ]
    all_columns = sorted(all_columns, key=questionnaire_variable_sort_key)
    labels = question_labels or {}
    text_labels = question_text_labels or {}
    numbered_groups: dict[str, list[str]] = {}
    for column in all_columns:
        base = _numbered_question_group_base(column)
        if base:
            numbered_groups.setdefault(base, []).append(column)

    grouped_columns: set[str] = set()
    groups_by_first_column: dict[str, dict[str, Any]] = {}
    for base, columns in numbered_groups.items():
        if len(columns) < 2:
            continue
        stem = _shared_question_stem([labels.get(column, column) for column in columns])
        if not stem:
            continue
        text_stem = _shared_question_stem([
            text_labels.get(column, labels.get(column, column))
            for column in columns
        ]) or stem
        grouped_columns.update(columns)
        groups_by_first_column[columns[0]] = {
            "label": stem,
            "question_text": text_stem,
            "variables": columns,
        }

    groups: list[dict[str, Any]] = []
    for column in all_columns:
        if column in groups_by_first_column:
            groups.append(groups_by_first_column[column])
        if column in grouped_columns:
            continue
        display_source = _collapse_internal_whitespace(labels.get(column, column))
        display_label = _friendly_question_variable_label(column, display_source)
        question_text = _collapse_internal_whitespace(text_labels.get(column, ""))
        if not question_text or question_text.lower() == normalize_text(column).lower():
            question_text = display_label
        groups.append(
            {
                "label": display_label,
                "question_text": question_text,
                "variables": [column],
            }
        )
    return groups


def _flatten_question_group_variables(groups: list[dict[str, Any]]) -> list[str]:
    """Flatten ordered question groups into raw variable ids."""
    flattened: list[str] = []
    for group in groups:
        for variable in group.get("variables", []):
            normalized_variable = normalize_text(variable)
            if normalized_variable and normalized_variable not in flattened:
                flattened.append(normalized_variable)
    return flattened


def _sort_question_variable_groups_by_order(
    groups: list[dict[str, Any]],
    ordered_columns: list[str] | None,
) -> list[dict[str, Any]]:
    """Sort question groups using an ordered raw-variable list when available."""
    order_lookup = {
        normalize_text(column): index
        for index, column in enumerate(ordered_columns or [])
        if normalize_text(column)
    }
    if not order_lookup:
        return groups

    def group_order(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        default_index, group = item
        variable_orders = [
            order_lookup[normalize_text(variable)]
            for variable in group.get("variables", [])
            if normalize_text(variable) in order_lookup
        ]
        if variable_orders:
            return (0, min(variable_orders))
        return (1, default_index)

    return [
        group
        for _, group in sorted(enumerate(groups), key=group_order)
    ]


def _default_ordered_columns(
    all_columns: list[str],
    question_labels: dict[str, str] | None = None,
    question_text_labels: dict[str, str] | None = None,
) -> list[str]:
    """Return the default QNR-style question order as raw variable ids."""
    return _flatten_question_group_variables(
        _build_question_variable_groups(all_columns, question_labels, question_text_labels)
    )


def _build_included_editor(
    all_columns: list[str],
    selected_columns: list[str],
    question_labels: dict[str, str] | None = None,
    question_text_labels: dict[str, str] | None = None,
    order_columns: list[str] | None = None,
) -> pd.DataFrame:
    """Build the editable included questions/variables table for Step 1."""
    selected_lookup = set(selected_columns)
    rows = []
    groups = _build_question_variable_groups(all_columns, question_labels, question_text_labels)
    groups = _sort_question_variable_groups_by_order(groups, order_columns)
    for group in groups:
        variables = list(group["variables"])
        source_ids = ", ".join(variables)
        rows.append(
            {
                "Question / Variable": group["label"],
                "Variable ID": source_ids,
                "Question Text": group["question_text"],
                "_source_variables": SOURCE_VARIABLE_DELIMITER.join(variables),
                "Included": any(variable in selected_lookup for variable in variables),
            }
        )
    return pd.DataFrame(rows)


def _order_question_metadata_by_columns(
    metadata_rows: list[dict[str, Any]],
    ordered_columns: list[str],
) -> list[dict[str, Any]]:
    """Return metadata rows in Page 2 question order, with leftovers after."""
    order_lookup = {
        normalize_text(column): index
        for index, column in enumerate(ordered_columns)
        if normalize_text(column)
    }
    if not order_lookup:
        return list(metadata_rows)

    def row_order(item: tuple[int, dict[str, Any]]) -> tuple[int, int]:
        default_index, row = item
        variable = normalize_text(row.get("variable"))
        if variable in order_lookup:
            return (0, order_lookup[variable])
        return (1, default_index)

    return [
        row
        for _, row in sorted(enumerate(metadata_rows), key=row_order)
    ]


def _current_question_order_columns(available_columns: list[str]) -> list[str]:
    """Return the active Page 2 question order constrained to current data."""
    available_lookup = set(available_columns)
    ordered_columns = [
        column
        for column in st.session_state.get("included_columns", [])
        if column in available_lookup
    ]
    for column in st.session_state.get("question_order", []):
        if column in available_lookup and column not in ordered_columns:
            ordered_columns.append(column)
    return ordered_columns


def _sync_question_order_state(available_columns: list[str]) -> None:
    """Apply the current question order to editor, metadata, and dependent views."""
    available_lookup = set(available_columns)
    included_columns = [
        column
        for column in st.session_state.get("included_columns", [])
        if column in available_lookup
    ]
    ordered_columns = _current_question_order_columns(available_columns)
    for column in available_columns:
        if column not in ordered_columns:
            ordered_columns.append(column)

    st.session_state.question_order = ordered_columns
    st.session_state.included_columns = included_columns
    if st.session_state.get("question_metadata"):
        st.session_state.question_metadata = _order_question_metadata_by_columns(
            st.session_state.question_metadata,
            included_columns or ordered_columns,
        )
    st.session_state.topline_editor = None
    st.session_state.generated_tables = {}
    st.session_state.generated_tables_signature = ""
    st.session_state.generated_excel_bytes = None
    st.session_state.generated_excel_signature = ""


def _editor_row_source_variables(
    row: dict[str, Any],
    source_map: dict[str, list[str]] | None = None,
) -> list[str]:
    """Return raw variables stored behind one Step 2 question/variable editor row."""
    source_text = normalize_text(row.get("_source_variables"))
    if source_text:
        return [
            normalize_text(variable)
            for variable in source_text.split(SOURCE_VARIABLE_DELIMITER)
            if normalize_text(variable)
        ]
    fallback = normalize_text(row.get("Question / Variable")) or normalize_text(row.get("Column"))
    variable_id_text = normalize_text(row.get("Variable ID"))
    if variable_id_text:
        return [
            normalize_text(variable)
            for variable in variable_id_text.split(",")
            if normalize_text(variable)
        ]
    if fallback and source_map and fallback in source_map:
        return list(source_map[fallback])
    return [fallback] if fallback else []


def _included_question_order_rows(
    editor_df: pd.DataFrame,
    available_columns: list[str],
) -> list[dict[str, Any]]:
    """Return included editor rows that can be reordered."""
    available_lookup = set(available_columns)
    rows: list[dict[str, Any]] = []
    if not isinstance(editor_df, pd.DataFrame) or editor_df.empty:
        return rows
    for row in editor_df.to_dict(orient="records"):
        if not bool(row.get("Included", True)):
            continue
        variables = [
            variable
            for variable in _editor_row_source_variables(row)
            if variable in available_lookup
        ]
        if not variables:
            continue
        row_copy = dict(row)
        row_copy["_order_variables"] = variables
        row_copy["_order_key"] = SOURCE_VARIABLE_DELIMITER.join(variables)
        rows.append(row_copy)
    return rows


def _included_editor_widget_key(editor_df: pd.DataFrame) -> str:
    """Return a Streamlit key that changes when the included editor source changes."""
    if not isinstance(editor_df, pd.DataFrame) or editor_df.empty:
        return "included_editor_grid_empty"
    signature_rows = []
    for row in editor_df.to_dict(orient="records"):
        signature_rows.append(
            {
                "source": normalize_text(row.get("_source_variables"))
                or normalize_text(row.get("Variable ID"))
                or normalize_text(row.get("Question / Variable")),
                "included": bool(row.get("Included", True)),
            }
        )
    payload = json.dumps(signature_rows, sort_keys=True, default=str)
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
    return f"included_editor_grid_{digest}"


def _reorder_included_question_rows(
    rows: list[dict[str, Any]],
    source_key: str,
    direction: str,
) -> list[dict[str, Any]]:
    """Return included question rows after one ordering action."""
    current_index = next(
        (index for index, row in enumerate(rows) if row.get("_order_key") == source_key),
        None,
    )
    if current_index is None:
        return rows
    if direction == "top":
        target_index = 0
    elif direction == "up":
        target_index = current_index - 1
    elif direction == "down":
        target_index = current_index + 1
    elif direction == "bottom":
        target_index = len(rows) - 1
    else:
        return rows
    if target_index < 0 or target_index >= len(rows) or target_index == current_index:
        return rows

    reordered_rows = list(rows)
    moving_row = reordered_rows.pop(current_index)
    reordered_rows.insert(target_index, moving_row)
    return reordered_rows


def _move_included_question_order(
    source_key: str,
    direction: str,
    available_columns: list[str],
    editor_df: pd.DataFrame | None = None,
) -> bool:
    """Move one included question row and persist the new order."""
    source_editor = editor_df if isinstance(editor_df, pd.DataFrame) else st.session_state.get("included_editor")
    rows = _included_question_order_rows(source_editor, available_columns)
    reordered_rows = _reorder_included_question_rows(rows, source_key, direction)
    if reordered_rows == rows:
        return False

    included_columns = _flatten_question_group_variables(
        [{"variables": row.get("_order_variables", [])} for row in reordered_rows]
    )
    current_comparison = st.session_state.get("comparison_col")
    if current_comparison and current_comparison not in included_columns:
        included_columns = [current_comparison, *included_columns]

    st.session_state.included_columns = [
        column
        for column in dict.fromkeys(included_columns)
        if column in set(available_columns)
    ]
    _sync_question_order_state(available_columns)
    st.session_state.included_editor = _build_included_editor(
        available_columns,
        st.session_state.included_columns,
        st.session_state.get("question_labels", {}),
        st.session_state.get("question_text_labels", {}),
        st.session_state.question_order,
    )
    return True


def _apply_snowflake_display_variable_names(metadata_rows: list[dict[str, Any]], labels: dict[str, str]) -> None:
    """Use Snowflake display labels while preserving source question text."""
    for metadata_row in metadata_rows:
        variable = normalize_text(metadata_row.get("variable"))
        label = _collapse_internal_whitespace(labels.get(variable, ""))
        if label and label.lower() != variable.lower():
            metadata_row["display_variable_name"] = label


def _refresh_snowflake_label_maps_from_raw_data() -> None:
    """Refresh Snowflake label maps from the already-loaded raw dataframe."""
    if st.session_state.get("data_source_type") != "snowflake":
        return
    raw_df = st.session_state.get("raw_df")
    if not isinstance(raw_df, pd.DataFrame) or raw_df.empty:
        return

    display_labels, question_text_labels = extract_snowflake_label_maps(raw_df)
    if display_labels:
        merged_display_labels = dict(st.session_state.get("question_labels", {}))
        merged_display_labels.update(display_labels)
        st.session_state.question_labels = merged_display_labels
    if question_text_labels:
        merged_question_text_labels = dict(st.session_state.get("question_text_labels", {}))
        merged_question_text_labels.update(question_text_labels)
        st.session_state.question_text_labels = merged_question_text_labels


def _sync_question_metadata_from_intake_labels(
    metadata_rows: list[dict[str, Any]],
    all_columns: list[str],
    question_labels: dict[str, str],
    question_text_labels: dict[str, str],
) -> None:
    """Carry Page 2 labels/question text into Page 3 metadata rows."""
    groups = _build_question_variable_groups(all_columns, question_labels, question_text_labels)
    display_lookup: dict[str, str] = {}
    text_lookup: dict[str, str] = {}
    for group in groups:
        display_label = normalize_text(group.get("label"))
        question_text = normalize_text(group.get("question_text")) or display_label
        for variable in group.get("variables", []):
            normalized_variable = normalize_text(variable)
            if not normalized_variable:
                continue
            display_lookup[normalized_variable] = display_label
            text_lookup[normalized_variable] = question_text

    for row in metadata_rows:
        variable = normalize_text(row.get("variable"))
        if not variable:
            continue
        desired_display = display_lookup.get(variable)
        desired_question_text = text_lookup.get(variable)
        existing_display = get_display_variable_name(row)
        default_display_values = {
            variable.lower(),
            normalize_text(row.get("question_label")).lower(),
            normalize_text(question_labels.get(variable)).lower(),
            normalize_text(question_text_labels.get(variable)).lower(),
        }
        if desired_display and (
            not existing_display
            or existing_display.lower() in default_display_values
        ):
            row["display_variable_name"] = desired_display
        if desired_question_text:
            row["question_label"] = desired_question_text


def _apply_intake_result(result) -> None:
    """Persist a completed intake result into session state."""
    available_columns = [
        column
        for column in result.cleaned_df.columns
        if not is_internal_respondent_column(column)
    ]
    previous_survey_df = st.session_state.get("survey_df")
    previous_available_columns = (
        [
            column
            for column in previous_survey_df.columns
            if not is_internal_respondent_column(column)
        ]
        if isinstance(previous_survey_df, pd.DataFrame) and not previous_survey_df.empty
        else []
    )
    previous_included = st.session_state.get("included_columns", [])
    question_text_labels = getattr(result, "question_text_labels", {}) or result.question_labels
    default_ordered_columns = _default_ordered_columns(
        available_columns,
        result.question_labels,
        question_text_labels,
    )
    if previous_included:
        included_columns = [column for column in previous_included if column in available_columns]
        newly_available_columns = [
            column
            for column in default_ordered_columns
            if column not in previous_available_columns and column not in included_columns
        ]
        included_columns.extend(newly_available_columns)
    else:
        included_columns = default_ordered_columns.copy()

    st.session_state.raw_df = result.raw_df
    st.session_state.survey_df = result.cleaned_df.copy()
    st.session_state.cleaned_df = result.cleaned_df.copy()
    st.session_state.question_labels = result.question_labels
    st.session_state.question_text_labels = question_text_labels
    st.session_state.source_answer_choices = result.source_answer_choices
    st.session_state.source_question_types = result.source_question_types
    st.session_state.cell_col = result.cell_column
    st.session_state.comparison_col = result.cell_column
    st.session_state.comparison_options = available_columns
    st.session_state.comparison_configured = False
    st.session_state.included_columns = included_columns
    st.session_state.blacklist_used = result.blacklist_used
    st.session_state.ingestion_log = result.log_lines
    st.session_state.metadata_rows_removed = result.metadata_rows_removed
    st.session_state.removed_column_count = len(result.removed_columns)
    st.session_state.removed_columns = result.removed_columns
    st.session_state.blank_cell_rows_removed = 0
    st.session_state.comparison_rows_removed = 0
    st.session_state.sheet_name = result.sheet_name
    st.session_state.ingestion_completed_at = result.completed_at
    st.session_state.cell_config_editor = None
    st.session_state.comparison_group_order = _default_comparison_group_order(
        result.cleaned_df,
        result.cell_column,
    )
    st.session_state.comparison_group_labels = _default_comparison_group_labels(
        result.cleaned_df,
        result.cell_column,
        st.session_state.get("comparison_group_labels", {}),
    )
    st.session_state.comparison_scheme = build_default_comparison_scheme()
    st.session_state.locked_cell_bases = {}
    st.session_state.cell_sort_order = {}
    st.session_state.cell_letter_map = {}
    metadata_question_labels = st.session_state.question_text_labels or result.question_labels
    st.session_state.question_metadata = build_question_metadata(
        result.cleaned_df,
        metadata_question_labels,
        result.cell_column,
        result.source_answer_choices,
        result.source_question_types,
    )
    if st.session_state.get("data_source_type") == "snowflake":
        _apply_snowflake_display_variable_names(st.session_state.question_metadata, result.question_labels)
    st.session_state.question_order = list(dict.fromkeys([*included_columns, *default_ordered_columns]))
    st.session_state.question_metadata = _order_question_metadata_by_columns(
        st.session_state.question_metadata,
        included_columns,
    )
    st.session_state.scale_mappings = {}
    st.session_state.blacklist_editor = _build_blacklist_editor(
        st.session_state.blacklist_catalog,
        st.session_state.get("restored_columns", []),
    )
    st.session_state.included_editor = _build_included_editor(
        available_columns,
        included_columns,
        result.question_labels,
        st.session_state.question_text_labels,
        included_columns,
    )


def _apply_comparison_or_project_restore(default_comparison: str | None) -> bool:
    """Apply comparison setup, using a staged project restore when present."""
    pending_config = st.session_state.get("pending_project_config")
    restore_prep_status: dict[str, Any] = {}
    selected_comparison = default_comparison
    if pending_config:
        selected_comparison, restore_prep_status = prepare_project_config_for_loaded_data(
            pending_config,
            default_comparison,
        )

    _apply_comparison_selection(selected_comparison)

    if not pending_config:
        return False

    restore_status = apply_project_config_after_loaded_data(pending_config)
    restore_status.update(restore_prep_status)
    st.session_state.project_restore_status = restore_status
    available_columns = list(st.session_state.survey_df.columns)
    _sync_question_order_state(available_columns)
    st.session_state.included_editor = _build_included_editor(
        available_columns,
        st.session_state.get("included_columns", available_columns),
        st.session_state.get("question_labels", {}),
        st.session_state.get("question_text_labels", {}),
        st.session_state.get("question_order", []),
    )
    missing_included = restore_status.get("missing_included_variables", [])
    message = st.session_state.get("project_restore_message") or "Project settings restored from the saved file."
    if missing_included:
        message = (
            f"{message} {len(missing_included)} saved included question/variable(s) were not found "
            "in this data file."
        )
    _append_intake_change(message)
    return True


def _render_snowflake_intake() -> None:
    """Render the Snowflake data-loading UI inside the data intake page."""
    session = get_snowflake_session()
    if session is None:
        st.error(
            "Could not connect to Snowflake. Set SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, "
            "and SNOWFLAKE_PASSWORD, or use SNOWFLAKE_PRIVATE_KEY / SNOWFLAKE_PRIVATE_KEY_PATH."
        )
        return

    survey_options: dict[str, str] = {}
    try:
        surveys_df = load_available_surveys(session)
        survey_options = build_survey_options(surveys_df)
    except Exception as exc:
        st.warning(f"Could not load survey list: {exc}")

    selected_labels: list[str] = []
    if survey_options:
        option_labels = list(survey_options.keys())
        saved_labels = [
            label
            for label in st.session_state.get("snowflake_survey_labels", [])
            if label in survey_options
        ]
        selected_labels = safe_multiselect(
            "Surveys",
            options=option_labels,
            default=saved_labels,
            placeholder="Type a survey name or ID to search",
            key="snowflake_survey_select",
            reset_invalid_to_default=True,
        )
    else:
        st.caption("No surveys found in RPT_QUALTRICS__SURVEY_RESPONSE.")

    if st.button("Load from Snowflake", type="primary", use_container_width=False):
        if not selected_labels:
            st.error("Select at least one survey before loading.")
            return

        selected_keys = [
            survey_options[label]
            for label in selected_labels
            if label in survey_options and survey_options[label]
        ]
        if not selected_keys:
            st.error("The selected survey does not have a usable SURVEY_KEY.")
            return

        escaped_keys = ", ".join(
            f"'{key.replace(chr(39), chr(39) * 2)}'"
            for key in selected_keys
        )
        sql_to_run = (
            "SELECT * FROM SNOWFLAKE_EDW.EDW.RPT_QUALTRICS__SURVEY_RESPONSE "
            f"WHERE SURVEY_KEY IN ({escaped_keys})"
        )
        source_name = (
            selected_labels[0]
            if len(selected_labels) == 1
            else f"{selected_labels[0]} (+{len(selected_labels) - 1} more)"
        )

        try:
            with st.spinner("Loading survey data from Snowflake..."):
                raw_df = session.sql(sql_to_run).to_pandas()
                result = ingest_snowflake_dataframe(raw_df, source_name=source_name)
        except Exception as exc:
            st.error(f"Snowflake load failed: {exc}")
            _append_log(f"Snowflake load failed for {source_name}: {exc}")
            return

        st.session_state.data_source_type = "snowflake"
        st.session_state.uploaded_filename = source_name
        st.session_state.available_sheets = ["Snowflake"]
        st.session_state.snowflake_survey_labels = list(selected_labels)
        st.session_state.snowflake_survey_keys = list(selected_keys)
        st.session_state.blacklist_catalog = result.removed_columns.copy()
        st.session_state.restored_columns = []
        st.session_state.intake_change_log = []
        _apply_intake_result(result)
        default_comparison = _resolve_default_comparison(
            st.session_state.comparison_options,
            result.cell_column,
            result.cell_column,
        )
        restored_project = _apply_comparison_or_project_restore(default_comparison)
        if not restored_project:
            st.session_state.metadata_change_log = []
        _append_log(f"Snowflake ingestion complete for {source_name}.")
        respondent_total = respondent_count(result.cleaned_df)
        if restored_project:
            st.success(f"Loaded {respondent_total:,} respondent(s) from Snowflake and restored project settings.")
        else:
            st.success(f"Loaded {respondent_total:,} respondent(s) from Snowflake.")


def _refresh_current_intake(whitelist_columns: list[str]) -> Any:
    """Re-run cleaning for the current data source with updated column restores."""
    if st.session_state.get("data_source_type") == "snowflake":
        return ingest_snowflake_dataframe(
            df=st.session_state.raw_df,
            source_name=st.session_state.uploaded_filename or "Snowflake",
            blacklist=st.session_state.blacklist_catalog,
            whitelist_columns=whitelist_columns,
        )
    return ingest_qualtrics_dataframe(
        raw_df=st.session_state.raw_df,
        source_name=st.session_state.uploaded_filename or "uploaded_file",
        sheet_name=st.session_state.sheet_name or "Sheet1",
        blacklist=st.session_state.blacklist_catalog,
        whitelist_columns=whitelist_columns,
    )


def render_step_1() -> None:
    """Render the data intake page."""
    st.header("2. Data Intake")
    st.write(
        "Upload a Qualtrics/SPSS file or load project survey data from Snowflake."
    )

    source = st.radio(
        "Data source",
        ["Upload survey export", "Load from Snowflake"],
        horizontal=True,
        key="data_source_radio",
    )

    if source == "Load from Snowflake":
        _render_snowflake_intake()
    else:
        upload = st.file_uploader(
            "Upload survey export",
            type=["sav", "xlsx"],
            key="qualtrics_upload",
            help="Preferred format: `.sav` with labels. Fallback: a standard Qualtrics `.xlsx` export.",
        )

        if upload is not None:
            upload_extension = upload.name.rsplit(".", 1)[-1].lower() if "." in upload.name else ""
            if upload_extension == "sav":
                st.session_state.data_source_type = "sav"
                st.session_state.uploaded_filename = upload.name
                st.session_state.available_sheets = ["SAV data"]
                st.session_state.snowflake_survey_labels = []
                st.session_state.snowflake_survey_keys = []
                if st.button("Process Data", type="primary", use_container_width=False):
                    try:
                        result = ingest_qualtrics_sav(upload)
                    except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
                        st.error(f"Upload failed: {exc}")
                        _append_log(f"Upload failed for {upload.name}: {exc}")
                    else:
                        st.session_state.blacklist_catalog = result.removed_columns.copy()
                        st.session_state.restored_columns = []
                        st.session_state.intake_change_log = []
                        _apply_intake_result(result)
                        default_comparison = _resolve_default_comparison(
                            st.session_state.comparison_options,
                            result.cell_column,
                            result.cell_column,
                        )
                        restored_project = _apply_comparison_or_project_restore(default_comparison)
                        if not restored_project:
                            st.session_state.metadata_change_log = []
                        _append_log(f"Ingestion complete for {upload.name}.")
                        if restored_project:
                            st.success("SAV file processed successfully and project settings restored.")
                        else:
                            st.success("SAV file processed successfully.")
            else:
                try:
                    available_sheets = get_excel_sheet_names(upload)
                except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
                    st.error(f"Upload failed: {exc}")
                    _append_log(f"Upload failed for {upload.name}: {exc}")
                else:
                    st.session_state.data_source_type = "excel"
                    st.session_state.uploaded_filename = upload.name
                    st.session_state.available_sheets = available_sheets
                    st.session_state.snowflake_survey_labels = []
                    st.session_state.snowflake_survey_keys = []

                    if len(available_sheets) > 1:
                        st.info("This workbook has multiple sheets. Choose one sheet to process for this intake.")

                    selected_sheet = st.selectbox(
                        "Select sheet to process",
                        options=available_sheets,
                        key="selected_sheet_name",
                    )

                    if st.button("Process Data", type="primary", use_container_width=False):
                        try:
                            result = ingest_qualtrics_excel(upload, sheet_name=selected_sheet)
                        except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
                            st.error(f"Upload failed: {exc}")
                            _append_log(f"Upload failed for {upload.name}: {exc}")
                        else:
                            st.session_state.blacklist_catalog = result.removed_columns.copy()
                            st.session_state.restored_columns = []
                            st.session_state.intake_change_log = []
                            _apply_intake_result(result)
                            default_comparison = _resolve_default_comparison(
                                st.session_state.comparison_options,
                                result.cell_column,
                                result.cell_column,
                            )
                            restored_project = _apply_comparison_or_project_restore(default_comparison)
                            if not restored_project:
                                st.session_state.metadata_change_log = []
                            _append_log(f"Ingestion complete for {upload.name}.")
                            if restored_project:
                                st.success(
                                    f"File processed successfully from sheet `{selected_sheet}` and project settings restored."
                                )
                            else:
                                st.success(f"File processed successfully from sheet `{selected_sheet}`.")

    cleaned_df = st.session_state.cleaned_df
    survey_df = st.session_state.survey_df
    if isinstance(survey_df, pd.DataFrame) and not survey_df.empty:
        st.subheader("Comparison Setup")
        # 2026-05-19 BD: Remove the separate comparison-variable selector from
        # the UI. The setup is driven by group rules, seeded from detected cell
        # values when available.
        if isinstance(cleaned_df, pd.DataFrame) and not cleaned_df.empty:
            _render_layered_comparison_editor(cleaned_df)

    if isinstance(cleaned_df, pd.DataFrame) and not cleaned_df.empty and st.session_state.get("comparison_configured"):
        col1, col2 = st.columns(2)
        col1.metric("Metadata rows removed", st.session_state.get("metadata_rows_removed", 0))
        col2.metric(
            "Rows removed for blank comparison value",
            st.session_state.get("comparison_rows_removed", 0),
        )

        st.subheader("Intake Summary")
        summary_left, summary_right = st.columns([1.2, 1])
        with summary_left:
            active_scheme = sanitize_comparison_scheme(st.session_state.get("comparison_scheme", {}))
            if active_scheme.get("enabled"):
                question_lookup = build_question_lookup(
                    st.session_state.question_metadata,
                    st.session_state.get("net_definitions", {}),
                    st.session_state.get("scale_mappings", {}),
                )
                scheme_groups = build_comparison_group_masks(
                    cleaned_df,
                    active_scheme,
                    question_lookup,
                    st.session_state.get("comparison_col"),
                    st.session_state.get("comparison_group_order", {}),
                    st.session_state.get("comparison_group_labels", {}),
                )
                # 2026-05-19 BD: With one unified setup, group labels are edited
                # in Comparison Setup; Intake Summary is read-only confirmation.
                st.dataframe(
                    summarize_comparison_groups(scheme_groups, cleaned_df),
                    key="comparison_scheme_summary",
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                comparison_summary = _build_comparison_summary_frame(cleaned_df, st.session_state.comparison_col)
                edited_summary = st.data_editor(
                    comparison_summary,
                    key="comparison_summary_editor",
                    use_container_width=True,
                    hide_index=True,
                    num_rows="fixed",
                    column_config={
                        "Raw Value": st.column_config.TextColumn(disabled=True),
                        "Display Label": st.column_config.TextColumn(help="Rename the visible group label used across the app and export."),
                        "N": st.column_config.NumberColumn(disabled=True),
                    },
                )
                label_left, label_right = st.columns(2)
                with label_left:
                    if st.button("Update Labels", key="update_comparison_labels", use_container_width=True):
                        updated_labels = {
                            normalize_text(row["Raw Value"]): normalize_text(row["Display Label"]) or normalize_text(row["Raw Value"])
                            for row in edited_summary.to_dict(orient="records")
                        }
                        previous_labels = dict(st.session_state.get("comparison_group_labels", {}))
                        st.session_state.comparison_group_labels = updated_labels
                        changed_bits = []
                        for raw_value, new_label in updated_labels.items():
                            old_label = normalize_text(previous_labels.get(raw_value, raw_value)) or raw_value
                            if old_label != new_label:
                                changed_bits.append(f"{raw_value}: {old_label} -> {new_label}")
                        if changed_bits:
                            _append_intake_change("Comparison labels updated (" + "; ".join(changed_bits) + ").")
                        else:
                            _append_intake_change("Comparison labels updated (no label changes).")
                        st.success("Comparison labels updated.")
                        st.rerun()
                with label_right:
                    if st.button("Reset Labels", key="reset_comparison_labels", use_container_width=True):
                        st.session_state.comparison_group_labels = _default_comparison_group_labels(
                            cleaned_df,
                            st.session_state.comparison_col,
                            {},
                        )
                        _append_intake_change("Comparison labels reset to default labels.")
                        st.success("Comparison labels reset.")
                        st.rerun()
        with summary_right:
            st.write(f"Sheet Referenced: `{st.session_state.sheet_name}`")
            st.write(f"Questions / Variables Included: `{_current_included_count()}`")
            st.write(f"Questions / Variables Excluded: `{_current_excluded_count()}`")

        active_order_scheme = sanitize_comparison_scheme(st.session_state.get("comparison_scheme", {}))
        if active_order_scheme.get("enabled") and len(active_order_scheme.get("groups", [])) > 1:
            st.subheader("Comparison Group Order")
            st.caption("Use the move buttons to control the display order for comparison groups.")
            question_lookup = build_question_lookup(
                st.session_state.question_metadata,
                st.session_state.get("net_definitions", {}),
                st.session_state.get("scale_mappings", {}),
            )
            ordered_scheme_groups = build_comparison_group_masks(
                cleaned_df,
                active_order_scheme,
                question_lookup,
                st.session_state.get("comparison_col"),
                st.session_state.get("comparison_group_order", {}),
                st.session_state.get("comparison_group_labels", {}),
            )
            for group_index, group in enumerate(ordered_scheme_groups):
                group_id = normalize_text(group.get("comparison_group_id") or group.get("id"))
                display_label = normalize_text(group.get("label")) or group_id
                role_label = normalize_text(group.get("role")).title() or "Test"
                base_n = respondent_count(cleaned_df, group.get("mask", pd.Series(dtype=bool)))
                row_cols = st.columns([3, 1.3, 1, 0.8, 0.8])
                row_cols[0].write(display_label)
                row_cols[1].write(role_label)
                row_cols[2].write(base_n)
                if row_cols[3].button("↑", key=f"scheme_order_up_{group_id}_{group_index}", use_container_width=True):
                    _move_comparison_scheme_group(group_id, "up")
                    st.rerun()
                if row_cols[4].button("↓", key=f"scheme_order_down_{group_id}_{group_index}", use_container_width=True):
                    _move_comparison_scheme_group(group_id, "down")
                    st.rerun()
        elif st.session_state.comparison_col and len(st.session_state.comparison_group_order) > 1:
            st.subheader("Comparison Group Order")
            st.caption("Use the move buttons to control the display order for comparison groups.")
            ordered_summary = _build_comparison_summary_frame(cleaned_df, st.session_state.comparison_col)
            for row in ordered_summary.to_dict(orient="records"):
                group_name = row["Raw Value"]
                display_label = row["Display Label"]
                row_cols = st.columns([4, 1, 0.8, 0.8])
                row_cols[0].write(display_label)
                row_cols[1].write(int(row["N"]))
                if row_cols[2].button("↑", key=f"up_{group_name}", use_container_width=True):
                    _move_comparison_group(group_name, "up")
                    st.rerun()
                if row_cols[3].button("↓", key=f"down_{group_name}", use_container_width=True):
                    _move_comparison_group(group_name, "down")
                    st.rerun()

        with st.expander("Questions / Variables Included", expanded=True):
            available_columns = list(survey_df.columns)
            included_editor = st.session_state.get("included_editor")
            if (
                included_editor is None
                or not isinstance(included_editor, pd.DataFrame)
                or "Question / Variable" not in included_editor.columns
                or "Variable ID" not in included_editor.columns
            ):
                st.session_state.included_editor = _build_included_editor(
                    available_columns,
                    st.session_state.get("included_columns", available_columns),
                    st.session_state.get("question_labels", {}),
                    st.session_state.get("question_text_labels", {}),
                    _current_question_order_columns(available_columns),
                )

            edited_included = st.data_editor(
                st.session_state.included_editor,
                key=_included_editor_widget_key(st.session_state.included_editor),
                use_container_width=True,
                num_rows="fixed",
                hide_index=True,
                height=620,
                column_order=("Question / Variable", "Variable ID", "Question Text", "Included"),
                column_config={
                    "Question / Variable": st.column_config.TextColumn(disabled=True, width="large"),
                    "Variable ID": st.column_config.TextColumn(disabled=True, width="medium"),
                    "Question Text": st.column_config.TextColumn(disabled=True, width="large"),
                    "_source_variables": None,
                    "Included": st.column_config.CheckboxColumn(
                        "Included",
                        help="Checked means the question or variable stays in the working dataset.",
                        width="small",
                    ),
                },
            )

            order_rows = _included_question_order_rows(
                edited_included,
                available_columns,
            )
            if order_rows:
                st.markdown("**Question Order**")
                for row_index, row in enumerate(order_rows):
                    source_key = normalize_text(row.get("_order_key"))
                    row_label = normalize_text(row.get("Question / Variable")) or normalize_text(row.get("Variable ID"))
                    variable_id = normalize_text(row.get("Variable ID"))
                    row_cols = st.columns([0.45, 5.0, 1.5, 0.5, 0.5, 0.5, 0.5])
                    row_cols[0].write(row_index + 1)
                    row_cols[1].write(row_label)
                    row_cols[2].write(variable_id)
                    if row_cols[3].button(
                        "↑↑",
                        key=f"included_order_top_{row_index}_{widget_key_token(source_key)}",
                        disabled=row_index == 0,
                        use_container_width=True,
                        help="Send to top",
                    ):
                        if _move_included_question_order(source_key, "top", available_columns, edited_included):
                            _append_intake_change(f"Moved question/variable to top: {row_label}.")
                        st.rerun()
                    if row_cols[4].button(
                        "↑",
                        key=f"included_order_up_{row_index}_{widget_key_token(source_key)}",
                        disabled=row_index == 0,
                        use_container_width=True,
                        help="Move up",
                    ):
                        if _move_included_question_order(source_key, "up", available_columns, edited_included):
                            _append_intake_change(f"Moved question/variable up: {row_label}.")
                        st.rerun()
                    if row_cols[5].button(
                        "↓",
                        key=f"included_order_down_{row_index}_{widget_key_token(source_key)}",
                        disabled=row_index == len(order_rows) - 1,
                        use_container_width=True,
                        help="Move down",
                    ):
                        if _move_included_question_order(source_key, "down", available_columns, edited_included):
                            _append_intake_change(f"Moved question/variable down: {row_label}.")
                        st.rerun()
                    if row_cols[6].button(
                        "↓↓",
                        key=f"included_order_bottom_{row_index}_{widget_key_token(source_key)}",
                        disabled=row_index == len(order_rows) - 1,
                        use_container_width=True,
                        help="Send to bottom",
                    ):
                        if _move_included_question_order(source_key, "bottom", available_columns, edited_included):
                            _append_intake_change(f"Moved question/variable to bottom: {row_label}.")
                        st.rerun()

            include_spacer_left, include_left, include_right, include_spacer_right = st.columns([1, 1, 1, 1])

            with include_left:
                if st.button("Update Questions / Variables", key="update_included_columns", use_container_width=True):
                    previous_included_columns = list(st.session_state.get("included_columns", available_columns))
                    source_map = {
                        normalize_text(row.get("Question / Variable")): _editor_row_source_variables(row)
                        for row in st.session_state.included_editor.to_dict(orient="records")
                        if normalize_text(row.get("Question / Variable"))
                    }
                    included_columns = []
                    for row in edited_included.to_dict(orient="records"):
                        if not bool(row.get("Included", True)):
                            continue
                        included_columns.extend(_editor_row_source_variables(row, source_map))
                    included_columns = [
                        column
                        for column in dict.fromkeys(included_columns)
                        if column in available_columns
                    ]
                    current_comparison = st.session_state.get("comparison_col")
                    if current_comparison and current_comparison not in included_columns:
                        included_columns = [current_comparison, *included_columns]
                    st.session_state.included_columns = included_columns
                    _sync_question_order_state(available_columns)
                    st.session_state.included_editor = _build_included_editor(
                        available_columns,
                        included_columns,
                        st.session_state.get("question_labels", {}),
                        st.session_state.get("question_text_labels", {}),
                        st.session_state.get("question_order", []),
                    )
                    try:
                        _apply_comparison_selection(current_comparison)
                    except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
                        st.error(str(exc))
                    else:
                        added_columns = [column for column in included_columns if column not in previous_included_columns]
                        removed_columns = [column for column in previous_included_columns if column not in included_columns]
                        summary_bits = []
                        if added_columns:
                            summary_bits.append("added: " + ", ".join(added_columns))
                        if removed_columns:
                            summary_bits.append("removed: " + ", ".join(removed_columns))
                        if not summary_bits:
                            summary_bits.append("no included question/variable changes")
                        _append_intake_change("Included questions/variables updated (" + "; ".join(summary_bits) + ").")
                        st.success("Included questions/variables updated.")
                        st.rerun()

            with include_right:
                if st.button("Reset Questions / Variables", key="reset_included_columns", use_container_width=True):
                    default_included_columns = _default_ordered_columns(
                        available_columns,
                        st.session_state.get("question_labels", {}),
                        st.session_state.get("question_text_labels", {}),
                    )
                    st.session_state.included_columns = default_included_columns
                    st.session_state.question_order = default_included_columns
                    _sync_question_order_state(available_columns)
                    st.session_state.included_editor = _build_included_editor(
                        available_columns,
                        default_included_columns,
                        st.session_state.get("question_labels", {}),
                        st.session_state.get("question_text_labels", {}),
                        st.session_state.get("question_order", []),
                    )
                    try:
                        _apply_comparison_selection(st.session_state.get("comparison_col"))
                    except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
                        st.error(str(exc))
                    else:
                        _append_intake_change("Included questions/variables reset to all available questions/variables.")
                        st.success("Included questions/variables reset to all available questions/variables.")
                        st.rerun()

        with st.expander("Questions / Variables Excluded", expanded=True):
            if st.session_state.blacklist_catalog:
                if st.session_state.blacklist_editor is None:
                    st.session_state.blacklist_editor = _build_blacklist_editor(
                        st.session_state.blacklist_catalog,
                        st.session_state.get("restored_columns", []),
                    )

                edited_blacklist = st.data_editor(
                    st.session_state.blacklist_editor,
                    key="blacklist_editor_grid",
                    use_container_width=True,
                    num_rows="fixed",
                    hide_index=True,
                    height=620,
                    column_config={
                        "Column": st.column_config.TextColumn("Question / Variable", disabled=True, width="large"),
                        "Excluded": st.column_config.CheckboxColumn(
                            "Excluded",
                            help="Checked means the question or variable stays excluded from the cleaned dataset.",
                            width="small",
                        ),
                    },
                )

                btn_spacer_left, btn_left, btn_right, btn_spacer_right = st.columns([1, 1, 1, 1])

                with btn_left:
                    if st.button("Update Questions / Variables", use_container_width=True):
                        previous_restored_columns = list(st.session_state.get("restored_columns", []))
                        restored_columns = [
                            row["Column"]
                            for row in edited_blacklist.to_dict(orient="records")
                            if not bool(row.get("Excluded", True))
                        ]
                        refreshed = _refresh_current_intake(restored_columns)
                        previous_comparison = st.session_state.get("comparison_col")
                        st.session_state.restored_columns = restored_columns
                        _apply_intake_result(refreshed)
                        selected_comparison = _resolve_default_comparison(
                            st.session_state.comparison_options,
                            refreshed.cell_column,
                            previous_comparison,
                        )
                        _apply_comparison_selection(selected_comparison)
                        st.session_state.included_editor = _build_included_editor(
                            list(st.session_state.survey_df.columns),
                            st.session_state.get("included_columns", list(st.session_state.survey_df.columns)),
                            st.session_state.get("question_labels", {}),
                            st.session_state.get("question_text_labels", {}),
                            st.session_state.get("question_order", []),
                        )
                        st.session_state.blacklist_editor = _build_blacklist_editor(
                            st.session_state.blacklist_catalog,
                            restored_columns,
                        )
                        added_back = [column for column in restored_columns if column not in previous_restored_columns]
                        re_excluded = [column for column in previous_restored_columns if column not in restored_columns]
                        summary_bits = []
                        if added_back:
                            summary_bits.append("added back: " + ", ".join(added_back))
                        if re_excluded:
                            summary_bits.append("excluded again: " + ", ".join(re_excluded))
                        if not summary_bits:
                            summary_bits.append("no excluded question/variable changes")
                        _append_intake_change("Excluded questions/variables updated (" + "; ".join(summary_bits) + ").")
                        if restored_columns:
                            st.success(
                                "Updated intake. Added back question(s)/variable(s): "
                                + ", ".join(restored_columns)
                            )
                        else:
                            st.success("Updated intake. All blacklisted questions/variables remain excluded.")
                        st.rerun()

                with btn_right:
                    if st.button("Reset Questions / Variables", use_container_width=True):
                        refreshed = _refresh_current_intake([])
                        st.session_state.restored_columns = []
                        _apply_intake_result(refreshed)
                        _apply_comparison_selection(
                            _resolve_default_comparison(
                                st.session_state.comparison_options,
                                refreshed.cell_column,
                                refreshed.cell_column,
                            )
                        )
                        st.session_state.included_editor = _build_included_editor(
                            list(st.session_state.survey_df.columns),
                            st.session_state.get("included_columns", list(st.session_state.survey_df.columns)),
                            st.session_state.get("question_labels", {}),
                            st.session_state.get("question_text_labels", {}),
                            st.session_state.get("question_order", []),
                        )
                        st.session_state.blacklist_editor = _build_blacklist_editor(
                            st.session_state.blacklist_catalog,
                            [],
                        )
                        _append_intake_change("Excluded questions/variables reset to the default blacklist.")
                        st.success("Question/variable choices reset to the default blacklist.")
                        st.rerun()
            else:
                st.caption("No blacklisted questions/variables are configured for this intake.")

        st.subheader("Change Log")
        if st.session_state.get("intake_change_log"):
            for entry in reversed(st.session_state.intake_change_log[-20:]):
                st.code(entry)
        else:
            st.caption("No intake changes recorded yet.")


def render_step_3() -> None:
    """Render the question audit page."""
    st.header("3. Survey Question Audit")
    cleaned_df = st.session_state.cleaned_df
    cell_col = st.session_state.cell_col

    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty:
        st.info("Upload and process a dataset in Step 1 before auditing questions.")
        return

    if st.session_state.get("data_source_type") == "snowflake":
        _refresh_snowflake_label_maps_from_raw_data()

    question_labels = st.session_state.question_labels
    question_text_labels = st.session_state.get("question_text_labels", {}) or question_labels

    if not st.session_state.question_metadata:
        st.session_state.question_metadata = build_question_metadata(
            cleaned_df,
            question_text_labels,
            cell_col,
            st.session_state.get("source_answer_choices", {}),
            st.session_state.get("source_question_types", {}),
        )
        if st.session_state.get("data_source_type") == "snowflake":
            _apply_snowflake_display_variable_names(st.session_state.question_metadata, question_labels)

    if st.session_state.get("data_source_type") == "snowflake":
        _sync_question_metadata_from_intake_labels(
            st.session_state.question_metadata,
            list(cleaned_df.columns),
            question_labels,
            question_text_labels,
        )

    st.session_state.question_metadata = _order_question_metadata_by_columns(
        st.session_state.question_metadata,
        st.session_state.get("included_columns", []),
    )

    st.caption("Review question types, displayed variable names, and answer-choice labels where needed.")

    editor_df = prepare_metadata_editor_frame(st.session_state.question_metadata)
    edited = st.data_editor(
        editor_df,
        key="question_audit_grid",
        use_container_width=False,
        num_rows="fixed",
        hide_index=True,
        height=620,
        column_config=get_metadata_editor_columns(),
    )

    action_left, action_right = st.columns(2)
    with action_left:
        if st.button("Update Changes", type="primary", use_container_width=True):
            sanitized = merge_metadata_editor_with_source(
                edited,
                st.session_state.question_metadata,
                cleaned_df,
                st.session_state.get("source_answer_choices", {}),
            )
            previous = {row["variable"]: row for row in st.session_state.question_metadata}
            for row in sanitized:
                variable = row["variable"]
                previous_row = previous.get(variable, {})
                old_type = previous_row.get("detected_type")
                new_type = row["detected_type"]
                if old_type != new_type:
                    st.session_state.metadata_change_log.append(
                        build_metadata_change_log_entry(variable, old_type, new_type)
                    )
                old_display_name = get_display_variable_name(previous_row)
                new_display_name = get_display_variable_name(row)
                if old_display_name != new_display_name:
                    timestamp = format_timestamp()
                    st.session_state.metadata_change_log.append(
                        f"[{timestamp}] {variable}: Displayed variable name changed "
                        f"from {old_display_name or variable} to {new_display_name or variable}"
                    )
                old_choices = normalize_text(previous_row.get("answer_choices", ""))
                new_choices = normalize_text(row.get("answer_choices", ""))
                if old_choices != new_choices:
                    timestamp = format_timestamp()
                    st.session_state.metadata_change_log.append(
                        f"[{timestamp}] {variable}: Answer choices changed "
                        f"{_summarize_choice_change(old_choices, new_choices)}"
                    )
            st.session_state.question_metadata = _order_question_metadata_by_columns(
                sanitized,
                st.session_state.get("included_columns", []),
            )
            st.success("Question audit changes saved.")

    with action_right:
        if st.button("Reset Defaults", use_container_width=True):
            st.session_state.question_metadata = restore_metadata_defaults(
                cleaned_df,
                question_text_labels,
                cell_col,
                st.session_state.get("source_answer_choices", {}),
                st.session_state.get("source_question_types", {}),
            )
            if st.session_state.get("data_source_type") == "snowflake":
                _apply_snowflake_display_variable_names(st.session_state.question_metadata, question_labels)
                _sync_question_metadata_from_intake_labels(
                    st.session_state.question_metadata,
                    list(cleaned_df.columns),
                    question_labels,
                    question_text_labels,
                )
            st.session_state.question_metadata = _order_question_metadata_by_columns(
                st.session_state.question_metadata,
                st.session_state.get("included_columns", []),
            )
            st.success("Question metadata restored to defaults.")
            st.rerun()

    st.subheader("Change Log")
    if st.session_state.metadata_change_log:
        for entry in reversed(st.session_state.metadata_change_log[-15:]):
            st.code(entry)
    else:
        st.caption("No manual changes yet.")


def render_step_4() -> None:
    """Render the scale mapping and polarity page."""
    scale_seed_version = 1
    st.header("4. Scale Mapping & Polarity")
    cleaned_df = st.session_state.cleaned_df
    question_metadata = st.session_state.question_metadata

    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty:
        st.info("Upload and process a dataset in Step 1 before mapping scales.")
        return

    scale_questions = identify_scale_questions(question_metadata)
    if not scale_questions:
        st.info("No questions are currently marked as `Scale / Likert`.")
        return

    if st.session_state.get("scale_save_message"):
        st.success(st.session_state.scale_save_message)
        st.session_state.scale_save_message = ""

    st.write(
        "Review scale questions in one table. Each row is a scale question and each column is a "
        "scale point in order from 1 to n."
    )
    if (
        st.session_state.get("scale_mapping_seed_version", 0) < scale_seed_version
        and not st.session_state.get("scale_change_log")
    ):
        st.session_state.scale_mappings = {}
        st.session_state.scale_mapping_seed_version = scale_seed_version

    st.session_state.scale_mappings = ensure_scale_mappings(
        scale_questions,
        cleaned_df,
        st.session_state.scale_mappings,
    )

    editor_df = build_scale_mapping_editor_frame(
        scale_questions,
        st.session_state.scale_mappings,
    )
    scale_options = build_scale_mapping_options(st.session_state.scale_mappings)

    point_columns = [column for column in editor_df.columns if column.startswith("scale_point_")]
    column_config = {
        "variable": st.column_config.TextColumn("Raw Variable Name", disabled=True, width=180),
        "display_variable_name": st.column_config.TextColumn("Displayed Variable Name", disabled=True, width=220),
        "question_label": st.column_config.TextColumn("Question Text", disabled=True, width=420),
        "polarity": st.column_config.SelectboxColumn(
            "Polarity",
            options=["standard", "flipped"],
            width=120,
            help="Use `flipped` when the lowest score should become the highest score.",
        ),
    }
    for index, column in enumerate(point_columns, start=1):
        column_config[column] = st.column_config.SelectboxColumn(
            f"Scale Point {index}",
            options=scale_options,
            width=220,
        )

    edited = st.data_editor(
        editor_df,
        key="scale_mapping_grid",
        use_container_width=False,
        num_rows="fixed",
        hide_index=True,
        height=560,
        column_config=column_config,
    )

    if st.button("Save Mappings", type="primary", use_container_width=True):
        issues = validate_scale_mapping_editor(edited)
        if issues:
            for issue in issues:
                st.error(issue)
        else:
            previous_mappings = {
                key: value.copy()
                for key, value in st.session_state.scale_mappings.items()
            }
            st.session_state.scale_mappings = save_scale_mapping_editor(
                edited,
                previous_mappings=st.session_state.scale_mappings,
            )
            timestamp = format_timestamp()
            for change in build_scale_change_log(previous_mappings, st.session_state.scale_mappings):
                st.session_state.scale_change_log.append(f"[{timestamp}] {change}")
            st.session_state.scale_save_message = "Scale mappings saved."
            st.rerun()

    st.subheader("Change Log")
    if st.session_state.scale_change_log:
        for entry in reversed(st.session_state.scale_change_log[-15:]):
            st.code(entry)
    else:
        st.caption("No scale mapping changes yet.")


def render_step_5_nets() -> None:
    """Render the net-definition setup page."""
    st.header("5. Net Definitions")
    st.write("Choose which intra-question nets to create for each scale question.")

    cleaned_df = st.session_state.cleaned_df
    question_metadata = st.session_state.question_metadata
    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty:
        st.info("Process your data first before defining nets.")
        return

    scale_questions = identify_scale_questions(question_metadata)
    if not scale_questions:
        st.info("No `Scale / Likert` questions are currently available for net creation.")
        return

    if st.session_state.get("net_save_message"):
        st.success(st.session_state.net_save_message)
        st.session_state.net_save_message = ""

    st.session_state.scale_mappings = ensure_scale_mappings(
        scale_questions,
        cleaned_df,
        st.session_state.scale_mappings,
    )
    base_frame = build_net_editor_frame(
        scale_questions,
        st.session_state.scale_mappings,
        st.session_state.net_definitions,
    )
    current_frame = st.session_state.get("net_editor_frame")
    if (
        not isinstance(current_frame, pd.DataFrame)
        or list(current_frame.get("variable", [])) != list(base_frame.get("variable", []))
        or list(current_frame.get("display_variable_name", [])) != list(base_frame.get("display_variable_name", []))
    ):
        st.session_state.net_editor_frame = base_frame.copy()

    button_columns = st.columns(len(NET_LABELS))
    for index, net_label in enumerate(NET_LABELS):
        with button_columns[index]:
            if st.button(net_label, use_container_width=True, key=f"bulk_net_{net_label}"):
                st.session_state.net_editor_frame = toggle_net_column(
                    st.session_state.net_editor_frame,
                    net_label,
                )
                st.rerun()

    edited = st.data_editor(
        st.session_state.net_editor_frame,
        key="net_definition_grid",
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "variable": st.column_config.TextColumn("Raw Variable Name", disabled=True, width=220),
            "display_variable_name": st.column_config.TextColumn("Displayed Variable Name", disabled=True, width=260),
            "question_label": st.column_config.TextColumn("Question Text", disabled=True, width=700),
            "T2B": st.column_config.CheckboxColumn("T2B"),
            "T3B": st.column_config.CheckboxColumn("T3B"),
            "B2B": st.column_config.CheckboxColumn("B2B"),
            "B3B": st.column_config.CheckboxColumn("B3B"),
        },
    )
    st.session_state.net_editor_frame = edited.copy()

    save_col, reset_col = st.columns(2)
    with save_col:
        if st.button("Save Nets", type="primary", use_container_width=True):
            st.session_state.net_definitions = save_net_editor_frame(edited)
            st.session_state.net_save_message = "Net definitions saved."
            st.rerun()
    with reset_col:
        if st.button("Reset Nets", use_container_width=True):
            reset_frame = edited.copy()
            for net_label in NET_LABELS:
                if net_label in reset_frame.columns:
                    reset_frame[net_label] = False
            st.session_state.net_editor_frame = reset_frame
            st.session_state.net_definitions = save_net_editor_frame(reset_frame)
            st.session_state.net_save_message = "Net definitions reset."
            st.rerun()


def render_step_6() -> None:
    """Render the custom variable builder."""
    if st.session_state.get("custom_var_reset_requested"):
        _reset_custom_variable_builder_state()
        st.session_state.custom_var_reset_requested = False
    if st.session_state.get("custom_var_edit_payload"):
        _load_custom_variable_into_builder(st.session_state.custom_var_edit_payload)
        st.session_state.custom_var_edit_payload = None

    st.header("6. Custom Variable Builder")
    st.write(
        "Build either a simple variable from one source question or a complex variable using "
        "multi question condition logic."
    )
    question_lookup = build_question_lookup(
        st.session_state.question_metadata,
        st.session_state.net_definitions,
        st.session_state.scale_mappings,
    )
    question_options = list(question_lookup.keys())
    question_labels = {
        variable: (
            f"{question_lookup[variable].get('display_variable_name', variable)} - "
            f"{question_lookup[variable]['question_label']}"
        )
        for variable in question_options
    }
    if not question_options:
        st.info("No eligible source questions are available yet for custom variable building.")
        return

    editing_name = st.session_state.get("custom_var_edit_name")
    if editing_name:
        edit_left, edit_right = st.columns([4, 1])
        with edit_left:
            st.info(f"Editing custom variable: `{editing_name}`")
        with edit_right:
            if st.button("Cancel Edit", use_container_width=True):
                st.session_state.custom_var_reset_requested = True
                st.rerun()

    build_type = st.selectbox("Build Type", options=BUILD_TYPES, key="custom_var_build_type")
    name = st.text_input("Custom variable name", key="custom_var_name")

    if "custom_var_bucket_count" not in st.session_state:
        st.session_state.custom_var_bucket_count = 2

    bucket_count = st.number_input(
        "Number of Choice Options",
        min_value=2,
        max_value=8,
        step=1,
        key="custom_var_bucket_count",
    )

    bucket_definitions: list[dict[str, Any]] = []

    if build_type == "Simple Variable":
        simple_source_options = ["", *question_options]
        source_variable = st.selectbox(
            "Source Question",
            options=simple_source_options,
            format_func=lambda value: question_labels.get(value, value) if value else "Select source question",
            key="custom_var_simple_source",
            help="Use one existing question and create your own grouped buckets from it.",
        )
        source_choices = question_lookup.get(source_variable, {}).get("answer_choices_list", [])
        simple_bucket_preview: list[dict[str, Any]] = []
        for bucket_index in range(int(bucket_count)):
            st.markdown(f"### Choice Option {bucket_index + 1}")
            bucket_label = st.text_input(
                "Option Label",
                key=f"custom_bucket_label_{bucket_index}",
            )
            selected_choices: list[str] = []
            selected_choices = safe_multiselect(
                question_labels.get(source_variable, source_variable),
                options=source_choices,
                key=(
                    f"custom_bucket_simple_choices_"
                    f"{bucket_index}_{_widget_key_token(source_variable)}"
                ),
            )

            bucket_record = {
                "label": bucket_label,
                "choices": selected_choices,
            }
            bucket_definitions.append(bucket_record)
            simple_bucket_preview.append(bucket_record)

        st.subheader("Unmatched Responses")
        fallback_mode = st.selectbox(
            "For respondents not matched above",
            options=["Ignore / Missing", "Create additional option"],
            key="custom_var_simple_fallback_mode",
        )
        fallback_label = ""
        if fallback_mode == "Create additional option":
            fallback_label = st.text_input(
                "Additional Option Label",
                key="custom_var_simple_fallback_label",
            )

        if isinstance(st.session_state.cleaned_df, pd.DataFrame) and not st.session_state.cleaned_df.empty:
            bucket_counts, unmatched_count = compute_simple_variable_counts(
                st.session_state.cleaned_df,
                source_variable,
                simple_bucket_preview,
                question_lookup,
            )
            st.subheader("Preview Counts")
            preview_rows = []
            for index, bucket in enumerate(simple_bucket_preview):
                preview_rows.append(
                    {
                        "Option": bucket.get("label") or f"Choice Option {index + 1}",
                        "N": bucket_counts[index],
                    }
                )
            if fallback_mode == "Create additional option":
                preview_rows.append(
                    {
                        "Option": fallback_label or "Additional Option",
                        "N": unmatched_count,
                    }
                )
            else:
                preview_rows.append({"Option": "Unmatched", "N": unmatched_count})
            st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

            bucket_definitions = simple_bucket_preview
    else:
        complex_bucket_preview: list[dict[str, Any]] = []
        for bucket_index in range(int(bucket_count)):
            st.markdown(f"### Choice Option {bucket_index + 1}")
            bucket_label = st.text_input(
                "Option Label",
                key=f"custom_bucket_label_{bucket_index}",
            )
            bucket_match_logic = st.selectbox(
                "Show only responses where",
                options=MATCH_LOGIC_OPTIONS,
                key=f"custom_bucket_match_logic_{bucket_index}",
                format_func=lambda value: (
                    "All of the following are true" if value == "ALL" else "Any of the following are true"
                ),
            )
            condition_count = st.number_input(
                "Number of Conditions",
                min_value=1,
                max_value=6,
                step=1,
                key=f"custom_bucket_condition_count_{bucket_index}",
            )

            conditions: list[dict[str, Any]] = []
            for condition_index in range(int(condition_count)):
                st.markdown(f"Condition {condition_index + 1}")
                condition_variable = st.selectbox(
                    "Source Question",
                    options=["", *question_options],
                    format_func=lambda value: question_labels.get(value, value) if value else "Select source question",
                    key=f"custom_condition_variable_{bucket_index}_{condition_index}",
                )
                condition_operator = st.selectbox(
                    "Operator",
                    options=["", *CONDITION_OPERATORS],
                    format_func=lambda value: value if value else "Select operator",
                    key=f"custom_condition_operator_{bucket_index}_{condition_index}",
                )
                condition_choices = safe_multiselect(
                    "Selected Choices",
                    options=question_lookup.get(condition_variable, {}).get("answer_choices_list", []),
                    key=(
                        f"custom_condition_choices_"
                        f"{bucket_index}_{condition_index}_{_widget_key_token(condition_variable)}"
                    ),
                )
                conditions.append(
                    {
                        "variable": condition_variable,
                        "operator": condition_operator,
                        "choices": condition_choices,
                    }
                )

            bucket_record = {
                "label": bucket_label,
                "match_logic": bucket_match_logic,
                "condition_count": int(condition_count),
                "conditions": conditions,
            }
            bucket_definitions.append(bucket_record)
            complex_bucket_preview.append(bucket_record)

        st.subheader("Unmatched Responses")
        complex_fallback_mode = st.selectbox(
            "For respondents not matched above",
            options=["Ignore / Missing", "Create additional option"],
            key="custom_var_complex_fallback_mode",
        )
        complex_fallback_label = ""
        if complex_fallback_mode == "Create additional option":
            complex_fallback_label = st.text_input(
                "Additional Option Label",
                key="custom_var_complex_fallback_label",
            )

        if isinstance(st.session_state.cleaned_df, pd.DataFrame) and not st.session_state.cleaned_df.empty:
            bucket_counts, unmatched_count = compute_complex_variable_counts(
                st.session_state.cleaned_df,
                complex_bucket_preview,
                question_lookup,
            )
            preview_rows = []
            for index, bucket in enumerate(complex_bucket_preview):
                preview_rows.append(
                    {
                        "Option": bucket.get("label") or f"Choice Option {index + 1}",
                        "N": bucket_counts[index],
                    }
                )
            if complex_fallback_mode == "Create additional option":
                preview_rows.append(
                    {
                        "Option": complex_fallback_label or "Additional Option",
                        "N": unmatched_count,
                    }
                )
            else:
                preview_rows.append({"Option": "Unmatched", "N": unmatched_count})
            st.subheader("Preview Counts")
            st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)

    save_label = "Update Custom Variable" if editing_name else "Save Custom Variable"
    if st.button(save_label, use_container_width=False):
        if build_type == "Simple Variable":
            issues = validate_simple_variable_definition(
                name,
                st.session_state.custom_variables,
                st.session_state.get("custom_var_simple_source", ""),
                bucket_definitions,
                st.session_state.get("custom_var_simple_fallback_mode", "Ignore / Missing"),
                st.session_state.get("custom_var_simple_fallback_label", ""),
                current_name=editing_name,
            )
        else:
            issues = validate_complex_variable_definition(
                name,
                st.session_state.custom_variables,
                bucket_definitions,
                st.session_state.get("custom_var_complex_fallback_mode", "Ignore / Missing"),
                st.session_state.get("custom_var_complex_fallback_label", ""),
                current_name=editing_name,
            )
        if issues:
            for issue in issues:
                st.error(issue)
        else:
            if build_type == "Simple Variable":
                record = build_simple_variable_record(
                    name=name,
                    source_variable=st.session_state.get("custom_var_simple_source", ""),
                    buckets=bucket_definitions,
                    fallback_mode=st.session_state.get("custom_var_simple_fallback_mode", "Ignore / Missing"),
                    fallback_label=st.session_state.get("custom_var_simple_fallback_label", ""),
                )
            else:
                record = build_complex_variable_record(
                    name=name,
                    buckets=bucket_definitions,
                    fallback_mode=st.session_state.get("custom_var_complex_fallback_mode", "Ignore / Missing"),
                    fallback_label=st.session_state.get("custom_var_complex_fallback_label", ""),
                )
            st.session_state.custom_variables = upsert_custom_variable(
                st.session_state.custom_variables,
                record,
            )
            st.session_state.custom_var_reset_requested = True
            if editing_name:
                st.success(f"Updated custom variable `{name}`.")
            else:
                st.success(f"Saved custom variable `{name}`.")
            st.rerun()

    summaries = list_custom_variable_summaries(st.session_state.custom_variables)
    if summaries:
        st.subheader("Saved Custom Variables")
        st.dataframe(
            pd.DataFrame(summaries).rename(
                columns={
                    "name": "Variable Name",
                    "builder_type": "Build Type",
                    "source_questions": "Source Questions",
                    "bucket_count": "Buckets",
                    "status": "Status",
                    "created_at": "Created At",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )
        for custom_variable in reversed(st.session_state.custom_variables):
            with st.expander(custom_variable.get("name", "Custom Variable")):
                action_left, action_right = st.columns(2)
                with action_left:
                    if st.button(
                        "Edit",
                        key=f"edit_custom_var_{custom_variable.get('name', '')}",
                        use_container_width=True,
                    ):
                        st.session_state.custom_var_edit_payload = custom_variable
                        st.rerun()
                with action_right:
                    if st.button(
                        "Delete",
                        key=f"delete_custom_var_{custom_variable.get('name', '')}",
                        use_container_width=True,
                    ):
                        st.session_state.custom_variables = [
                            item
                            for item in st.session_state.custom_variables
                            if normalize_text(item.get("name")) != normalize_text(custom_variable.get("name"))
                        ]
                        if normalize_text(editing_name) == normalize_text(custom_variable.get("name")):
                            st.session_state.custom_var_reset_requested = True
                        st.success(f"Deleted custom variable `{custom_variable.get('name', '')}`.")
                        st.rerun()
                st.write(f"Build Type: `{custom_variable.get('builder_type', '')}`")
                st.write(
                    "Source Questions: "
                    + ", ".join(custom_variable.get("source_variables", []))
                )
                for index, bucket in enumerate(custom_variable.get("buckets", []), start=1):
                    st.markdown(f"**Bucket {index}: {bucket.get('label', '')}**")
                    if custom_variable.get("builder_type") == "Simple Variable":
                        source_variable = (custom_variable.get("source_variables") or [""])[0]
                        bucket_counts: list[int] = []
                        unmatched_count = 0
                        if isinstance(st.session_state.cleaned_df, pd.DataFrame) and not st.session_state.cleaned_df.empty:
                            bucket_counts, unmatched_count = compute_simple_variable_counts(
                                st.session_state.cleaned_df,
                                source_variable,
                                custom_variable.get("buckets", []),
                                question_lookup,
                            )
                        if bucket.get("choices"):
                            st.write("Choices: " + " | ".join(bucket.get("choices", [])))
                        if bucket_counts and index <= len(bucket_counts):
                            st.caption(f"N Count: {bucket_counts[index - 1]}")
                        if index == len(custom_variable.get("buckets", [])):
                            fallback_mode = custom_variable.get("fallback_mode", "Ignore / Missing")
                            if fallback_mode == "Create additional option":
                                fallback_text = custom_variable.get("fallback_label") or "Additional Option"
                            else:
                                fallback_text = "Ignore / Missing"
                            st.caption(f"Unmatched N: {unmatched_count} | Handling: {fallback_text}")
                    else:
                        bucket_counts = []
                        unmatched_count = 0
                        if isinstance(st.session_state.cleaned_df, pd.DataFrame) and not st.session_state.cleaned_df.empty:
                            bucket_counts, unmatched_count = compute_complex_variable_counts(
                                st.session_state.cleaned_df,
                                custom_variable.get("buckets", []),
                                question_lookup,
                            )
                        st.caption(
                            "Logic: "
                            + ("All of the following are true" if bucket.get("match_logic") == "ALL" else "Any of the following are true")
                        )
                        for condition in bucket.get("conditions", []):
                            condition_text = (
                                f"{condition.get('variable', '')} | {condition.get('operator', '')} | "
                                + " | ".join(condition.get("choices", []))
                            )
                            st.write(condition_text)
                        if bucket_counts and index <= len(bucket_counts):
                            st.caption(f"N Count: {bucket_counts[index - 1]}")
                        if index == len(custom_variable.get("buckets", [])):
                            fallback_mode = custom_variable.get("fallback_mode", "Ignore / Missing")
                            if fallback_mode == "Create additional option":
                                fallback_text = custom_variable.get("fallback_label") or "Additional Option"
                            else:
                                fallback_text = "Ignore / Missing"
                            st.caption(f"Unmatched N: {unmatched_count} | Handling: {fallback_text}")
    else:
        st.caption("No custom variables configured yet.")


def render_step_7() -> None:
    """Render the banner configuration page."""
    st.header("7. Banner Configuration")
    st.write("Build one or more banners with up to 3 nested levels.")

    if not st.session_state.banner_config:
        st.session_state.banner_config = build_default_banner_config()

    variable_catalog = build_analysis_variable_catalog(
        st.session_state.question_metadata,
        st.session_state.custom_variables,
        st.session_state.get("comparison_col"),
        st.session_state.get("comparison_scheme", {}),
    )
    variable_options = [item["id"] for item in variable_catalog]
    variable_labels = {item["id"]: item["label"] for item in variable_catalog}
    include_total = st.checkbox(
        "Include total column",
        value=bool(st.session_state.banner_config.get("include_total", True)),
    )
    export_style = st.selectbox(
        "Export Style",
        options=["one_per_sheet", "single_sheet"],
        index=0 if st.session_state.banner_config.get("export_style", "one_per_sheet") == "one_per_sheet" else 1,
        format_func=lambda value: "1 banner per sheet" if value == "one_per_sheet" else "All banners in single sheet",
        help="Choose whether banner exports should be split by banner or combined into one sheet.",
    )
    existing_banners = list(st.session_state.banner_config.get("banners", []))
    banner_count = int(
        st.number_input(
            "Number of Banners",
            min_value=0,
            max_value=12,
            value=max(0, len(existing_banners)),
            step=1,
            key="banner_row_count",
        )
    )
    while len(existing_banners) < banner_count:
        existing_banners.append(build_default_banner_row())
    existing_banners = existing_banners[:banner_count]

    rendered_banners: list[dict[str, str]] = []
    for index in range(banner_count):
        row = existing_banners[index]
        st.markdown(f"**Banner {index + 1}**")
        name = st.text_input(
            "Banner Name",
            value=row.get("name", ""),
            key=f"banner_name_{index}",
        )
        col1, col2, col3 = st.columns(3)
        options_with_blank = ["", *variable_options]

        level_1 = col1.selectbox(
            "Level 1",
            options=options_with_blank,
            index=(
                options_with_blank.index(row.get("level_1", ""))
                if row.get("level_1", "") in options_with_blank
                else 0
            ),
            format_func=lambda value: variable_labels.get(value, value) if value else "Select variable",
            key=f"banner_level_1_{index}",
        )

        level_2_options = ["", *[value for value in variable_options if value != level_1]]
        level_2 = col2.selectbox(
            "Level 2",
            options=level_2_options,
            index=(
                level_2_options.index(row.get("level_2", ""))
                if row.get("level_2", "") in level_2_options
                else 0
            ),
            format_func=lambda value: variable_labels.get(value, value) if value else "Optional",
            key=f"banner_level_2_{index}",
        )

        excluded_level_3 = {value for value in [level_1, level_2] if value}
        level_3_options = ["", *[value for value in variable_options if value not in excluded_level_3]]
        level_3 = col3.selectbox(
            "Level 3",
            options=level_3_options,
            index=(
                level_3_options.index(row.get("level_3", ""))
                if row.get("level_3", "") in level_3_options
                else 0
            ),
            format_func=lambda value: variable_labels.get(value, value) if value else "Optional",
            key=f"banner_level_3_{index}",
            disabled=not bool(level_2),
        )

        rendered_banners.append(
            {
                "name": name.strip(),
                "level_1": level_1,
                "level_2": level_2,
                "level_3": level_3 if level_2 else "",
            }
        )

    selected_banners = []
    for banner_row in rendered_banners:
        for level_value in [banner_row.get("level_1"), banner_row.get("level_2"), banner_row.get("level_3")]:
            if level_value and level_value not in selected_banners:
                selected_banners.append(level_value)

    st.session_state.banner_config = {
        "banner_variables": selected_banners,
        "banners": rendered_banners,
        "include_total": include_total,
        "export_style": export_style,
    }

    issues = validate_analysis_config(
        st.session_state.weighting_config or build_default_weighting_config(),
        st.session_state.banner_config,
        st.session_state.global_filters or {"rows": []},
        st.session_state.local_overrides,
    )
    banner_issues = [message for message in issues if message.startswith("Banner")]
    if banner_issues:
        for message in banner_issues:
            st.warning(message)
    else:
        st.success("Banner configuration saved.")


def render_step_8() -> None:
    """Render the filter configuration page."""
    st.header("9. Filter Configuration")

    if not st.session_state.global_filters:
        st.session_state.global_filters = {"rows": []}

    variable_catalog = build_analysis_variable_catalog(
        st.session_state.question_metadata,
        st.session_state.custom_variables,
        st.session_state.get("comparison_col"),
    )
    question_lookup = build_question_lookup(
        st.session_state.question_metadata,
        st.session_state.net_definitions,
        st.session_state.scale_mappings,
    )
    variable_options = [item["id"] for item in variable_catalog]
    variable_labels = {item["id"]: item["label"] for item in variable_catalog}
    variable_types = {item["id"]: item["question_type"] for item in variable_catalog}

    apply_targets = ["All Tables"]
    comparison_label = st.session_state.get("comparison_col")
    if comparison_label:
        apply_targets.append(comparison_label)
    for banner in st.session_state.banner_config.get("banners", []):
        banner_name = normalize_text(banner.get("name"))
        if banner_name and banner_name not in apply_targets:
            apply_targets.append(banner_name)
    for table in st.session_state.get("adhoc_crosstabs_config", {}).get("tables", []):
        table_name = normalize_text(table.get("name")) or normalize_text(table.get("variable"))
        if table_name and table_name not in apply_targets:
            apply_targets.append(table_name)

    global_filter_rows = int(
        st.number_input(
            "Number of Filters",
            min_value=0,
            max_value=6,
            value=max(0, len(st.session_state.global_filters.get("rows", []))),
            step=1,
            key="global_filter_row_count",
        )
    )
    existing_global_rows = _coerce_filter_rows(
        list(st.session_state.global_filters.get("rows", [])),
        global_filter_rows,
    )
    rendered_global_rows: list[dict[str, Any]] = []
    for index in range(global_filter_rows):
        row = existing_global_rows[index]
        st.markdown(f"### Filter {index + 1}")

        filter_name = st.text_input(
            "Filter Name",
            value=row.get("name", ""),
            key=f"global_filter_name_{index}",
        )
        branch_count = int(
            st.number_input(
                "Number of Branches",
                min_value=1,
                max_value=6,
                value=max(1, len(row.get("branches", []))),
                step=1,
                key=f"global_filter_branch_count_{index}",
            )
        )
        branch_rows = list(row.get("branches", []))
        while len(branch_rows) < branch_count:
            branch_rows.append(build_default_filter_branch())
        branch_rows = branch_rows[:branch_count]

        rendered_branches: list[dict[str, Any]] = []
        for branch_index in range(branch_count):
            branch = branch_rows[branch_index]
            st.markdown(f"**Branch {branch_index + 1}**")
            branch_name = st.text_input(
                "Branch Label",
                value=branch.get("name", ""),
                key=f"global_filter_branch_name_{index}_{branch_index}",
                help="Optional note to help distinguish branches like control vs test.",
            )
            match_logic = st.selectbox(
                "Show only responses where",
                options=MATCH_LOGIC_OPTIONS,
                index=(MATCH_LOGIC_OPTIONS.index(branch.get("match_logic", "ALL")) if branch.get("match_logic", "ALL") in MATCH_LOGIC_OPTIONS else 0),
                format_func=lambda value: "All of the following are true" if value == "ALL" else "Any of the following are true",
                key=f"global_filter_match_logic_{index}_{branch_index}",
            )
            condition_count = int(
                st.number_input(
                    "Number of Conditions",
                    min_value=1,
                    max_value=8,
                    value=max(1, len(branch.get("conditions", []))),
                    step=1,
                    key=f"global_filter_condition_count_{index}_{branch_index}",
                )
            )
            condition_rows = list(branch.get("conditions", []))
            while len(condition_rows) < condition_count:
                condition_rows.append(build_default_filter_condition())
            condition_rows = condition_rows[:condition_count]

            rendered_conditions: list[dict[str, Any]] = []
            for condition_index in range(condition_count):
                condition = condition_rows[condition_index]
                st.caption(f"Condition {condition_index + 1}")
                col1, col2, col3 = st.columns([2, 1, 2])
                variable = col1.selectbox(
                    "Variable",
                    options=["", *variable_options],
                    index=(["", *variable_options].index(condition.get("variable", "")) if condition.get("variable", "") in ["", *variable_options] else 0),
                    format_func=lambda value: variable_labels.get(value, value) if value else "Select variable",
                    key=f"global_filter_variable_{index}_{branch_index}_{condition_index}",
                )
                operator_options = ["", *build_filter_operator_options(variable_types.get(variable, ""))]
                operator = col2.selectbox(
                    "Operator",
                    options=operator_options,
                    index=(operator_options.index(condition.get("operator", "")) if condition.get("operator", "") in operator_options else 0),
                    format_func=lambda value: value if value else "Select operator",
                    key=f"global_filter_operator_{index}_{branch_index}_{condition_index}",
                )
                value_options = _build_filter_value_options(
                    variable,
                    question_lookup,
                    st.session_state.custom_variables,
                    comparison_col=st.session_state.get("comparison_col"),
                    comparison_groups=st.session_state.get("comparison_group_order", {}),
                )
                value_display_labels = _build_filter_value_display_labels(
                    variable,
                    value_options,
                    st.session_state.get("comparison_col"),
                    st.session_state.get("comparison_group_labels", {}),
                )
                value_key = (
                    f"global_filter_values_"
                    f"{index}_{branch_index}_{condition_index}_{_widget_key_token(variable)}"
                )
                values = safe_multiselect(
                    "Values",
                    options=value_options,
                    default=_valid_multiselect_values(list(condition.get("values", [])), value_options),
                    key=value_key,
                    reset_invalid_to_default=True,
                    format_func=lambda value, labels=value_display_labels: labels.get(value, value),
                    help="Select one or more values for this condition.",
                )
                rendered_conditions.append(
                    {
                        "variable": variable,
                        "operator": operator,
                        "values": values,
                    }
                )

            rendered_branches.append(
                {
                    "name": branch_name,
                    "match_logic": match_logic,
                    "conditions": rendered_conditions,
                }
            )

        default_targets = _normalize_filter_targets(row.get("applies_to", []), apply_targets)
        applies_to = safe_multiselect(
            "Applies To",
            options=apply_targets,
            default=default_targets,
            key=f"global_filter_applies_to_{index}",
            reset_invalid_to_default=True,
            help="`All Tables` is the base filter layer. Banner-level filters stack on top of it.",
        )
        applies_to = _normalize_filter_targets(applies_to, apply_targets)

        rendered_global_rows.append(
            {
                "name": filter_name,
                "branches": rendered_branches,
                "applies_to": applies_to,
            }
        )

    st.session_state.global_filters = {"rows": rendered_global_rows}

    validation = validate_analysis_config(
        st.session_state.weighting_config or build_default_weighting_config(),
        st.session_state.banner_config or build_default_banner_config(),
        st.session_state.global_filters,
        {},
    )
    filter_issues = [message for message in validation if message.startswith("Filter ")]
    if filter_issues:
        for message in filter_issues:
            st.warning(message)
    else:
        st.success("Filter configuration saved.")


def render_step_9() -> None:
    """Render the weighting configuration page."""
    st.header("10. Weighting Configuration")

    if not st.session_state.weighting_config:
        st.session_state.weighting_config = build_default_weighting_config()
    if "weights" not in st.session_state.weighting_config:
        st.session_state.weighting_config = build_default_weighting_config()

    variable_catalog = build_analysis_variable_catalog(
        st.session_state.question_metadata,
        st.session_state.custom_variables,
        st.session_state.get("comparison_col"),
    )
    variable_options = [item["id"] for item in variable_catalog]
    variable_labels = {item["id"]: item["label"] for item in variable_catalog}
    weight_variable_options = build_weight_variable_options(st.session_state.question_metadata)
    question_lookup = build_question_lookup(
        st.session_state.question_metadata,
        st.session_state.net_definitions,
        st.session_state.scale_mappings,
    )
    limit_variable_options = []
    limit_question_lookup: dict[str, dict[str, Any]] = {}
    for metadata_row in st.session_state.question_metadata:
        variable = normalize_text(metadata_row.get("variable"))
        if not variable or variable in limit_variable_options:
            continue
        if normalize_text(metadata_row.get("detected_type")) == "Open-End Text":
            continue
        limit_variable_options.append(variable)
        variable_labels.setdefault(variable, get_display_variable_name(metadata_row) or variable)
        limit_question_lookup[variable] = {
            "answer_choices_list": list(metadata_row.get("answer_choices_list", [])),
            "detected_type": normalize_text(metadata_row.get("detected_type")),
        }
    for variable in variable_options:
        if variable not in limit_variable_options:
            limit_variable_options.append(variable)
    limit_value_lookup = {**question_lookup, **limit_question_lookup}

    apply_targets = ["All Tables"]
    comparison_label = st.session_state.get("comparison_col")
    if comparison_label:
        apply_targets.extend([comparison_label, "Total", *list(st.session_state.comparison_group_order.keys())])
    for banner in st.session_state.banner_config.get("banners", []):
        banner_name = normalize_text(banner.get("name"))
        if banner_name and banner_name not in apply_targets:
            apply_targets.append(banner_name)

    weight_targets = ["Total"]
    if comparison_label:
        weight_targets.append(f"Match {comparison_label} groups")
    else:
        weight_targets.append("Average of source groups")
    weight_targets.append("Custom percentages")
    if comparison_label:
        for group_name in st.session_state.comparison_group_order.keys():
            if group_name != "Total":
                weight_targets.append(group_name)

    weight_count = int(
        st.number_input(
            "Number of Weights",
            min_value=0,
            max_value=6,
            value=max(0, len(st.session_state.weighting_config.get("weights", []))),
            step=1,
            key="weight_row_count",
        )
    )
    st.caption(
        "Use multiple Weight rows to stack separate weights; rows that apply to the same table multiply together. "
        "Use multiple Weighting Variables inside one row for joint weighting, like Gender x Age. "
        "Custom percentages currently support one Weighting Variable per row."
    )
    existing_weights = list(st.session_state.weighting_config.get("weights", []))
    while len(existing_weights) < weight_count:
        existing_weights.append(build_default_weight_row())
    existing_weights = existing_weights[:weight_count]

    rendered_weights: list[dict[str, Any]] = []
    for index in range(weight_count):
        row = existing_weights[index]
        st.markdown(f"**Weight {index + 1}**")
        name = st.text_input(
            "Weight Name",
            value=row.get("name", ""),
            key=f"weight_name_{index}",
        )
        col1, col2 = st.columns(2)
        target = col1.selectbox(
            "Target",
            options=weight_targets,
            index=(weight_targets.index(row.get("target", "Total")) if row.get("target", "Total") in weight_targets else 0),
            key=f"weight_target_{index}",
            format_func=lambda value: (
                "Combined eligible respondents"
                if value == "Total"
                else "Average of balance groups"
                if normalize_text(value).casefold() == "average of source groups"
                or normalize_text(value).casefold().startswith("match ")
                else "Custom percentages"
                if value == "Custom percentages"
                else f"One balance group: {value}"
            ),
            help=(
                "`Combined eligible respondents` uses the gender mix across all rows that pass the limit. "
                "`Average of balance groups` gives each balance group, like Control and Test, equal influence. "
                "`Custom percentages` uses manually entered targets."
            ),
        )
        source_options = ["", *variable_options]
        comparison_default_label = variable_labels.get(comparison_label, comparison_label) if comparison_label else ""
        source = col2.selectbox(
            "Balance Groups",
            options=source_options,
            index=(source_options.index(row.get("source", "")) if row.get("source", "") in source_options else 0),
            format_func=lambda value: (
                variable_labels.get(value, value)
                if value
                else f"{comparison_default_label} (comparison default)"
                if comparison_default_label
                else "Single total group"
            ),
            key=f"weight_source_{index}",
            help="The groups to make comparable, usually Cell for Control/Test balancing.",
        )
        variables = safe_multiselect(
            "Weighting Variables",
            options=weight_variable_options,
            default=[value for value in row.get("variables", []) if value in weight_variable_options],
            format_func=lambda value: variable_labels.get(value, value),
            key=f"weight_variables_{index}",
            reset_invalid_to_default=True,
            help="The respondent attribute(s) to balance within each balance group, like Gender.",
        )
        effective_source = normalize_text(source) or normalize_text(st.session_state.get("comparison_col"))
        if effective_source and effective_source in [normalize_text(value) for value in variables]:
            st.warning(
                "Balance Groups and Weighting Variables are set to the same field. "
                "For TL Control/Test gender weighting, Balance Groups should be Cell and Weighting Variables should be Gender."
            )
        if len(variables) > 1:
            st.caption(
                "Multiple Weighting Variables in one row are treated as joint cells, so every combination needs enough respondents."
            )
        custom_targets: dict[str, float] = {}
        if target == "Custom percentages":
            if len(variables) != 1:
                st.warning("Custom percentage targets currently need exactly one Weighting Variable.")
            else:
                custom_variable = variables[0]
                custom_choices = _build_filter_value_options(
                    custom_variable,
                    limit_value_lookup,
                    st.session_state.custom_variables,
                    comparison_col=st.session_state.get("comparison_col"),
                    comparison_groups=st.session_state.get("comparison_group_order", {}),
                )
                if not custom_choices:
                    custom_choices = list(row.get("custom_targets", {}).keys())
                custom_value_display_labels = _build_filter_value_display_labels(
                    custom_variable,
                    custom_choices,
                    st.session_state.get("comparison_col"),
                    st.session_state.get("comparison_group_labels", {}),
                )
                saved_custom_targets = row.get("custom_targets", {}) if isinstance(row.get("custom_targets"), dict) else {}
                default_percent = round(100.0 / len(custom_choices), 2) if custom_choices else 0.0
                st.caption(f"Custom target percentages for {variable_labels.get(custom_variable, custom_variable)}")
                custom_columns = st.columns(min(max(len(custom_choices), 1), 4))
                for choice_index, choice in enumerate(custom_choices):
                    try:
                        saved_value = float(saved_custom_targets.get(choice, default_percent))
                    except (TypeError, ValueError):
                        saved_value = default_percent
                    with custom_columns[choice_index % len(custom_columns)]:
                        custom_targets[choice] = st.number_input(
                            custom_value_display_labels.get(choice, choice),
                            min_value=0.0,
                            max_value=100.0,
                            value=float(saved_value),
                            step=0.1,
                            key=f"weight_custom_target_{index}_{_widget_key_token(custom_variable)}_{_widget_key_token(choice)}",
                        )
                custom_total = sum(custom_targets.values())
                if custom_choices and abs(custom_total - 100.0) > 0.05:
                    st.warning(f"Custom targets total {custom_total:.1f}%. They will be normalized to 100% during weighting.")
        limit_col1, limit_col2 = st.columns([1, 2])
        limit_options = ["", *limit_variable_options]
        saved_limit_variable = normalize_text(row.get("limit_variable"))
        limit_variable = limit_col1.selectbox(
            "Only Weight Rows Where",
            options=limit_options,
            index=(
                limit_options.index(saved_limit_variable)
                if saved_limit_variable in limit_options
                else 0
            ),
            format_func=lambda value: variable_labels.get(value, value) if value else "No respondent limit",
            key=f"weight_limit_variable_{index}",
            help="Optional respondent subset for this weight. Rows outside the subset keep weight 1.0.",
        )
        limit_value_options = _build_filter_value_options(
            limit_variable,
            limit_value_lookup,
            st.session_state.custom_variables,
            comparison_col=st.session_state.get("comparison_col"),
            comparison_groups=st.session_state.get("comparison_group_order", {}),
        )
        limit_value_display_labels = _build_filter_value_display_labels(
            limit_variable,
            limit_value_options,
            st.session_state.get("comparison_col"),
            st.session_state.get("comparison_group_labels", {}),
        )
        with limit_col2:
            limit_values = safe_multiselect(
                "Limit Values",
                options=limit_value_options,
                default=_valid_multiselect_values(list(row.get("limit_values", [])), limit_value_options),
                key=f"weight_limit_values_{index}_{_widget_key_token(limit_variable)}",
                reset_invalid_to_default=True,
                format_func=lambda value, labels=limit_value_display_labels: labels.get(value, value),
                help="Select the respondent value(s) that should receive calculated weight factors.",
            )
        default_targets = [target_value for target_value in row.get("applies_to", []) if target_value in apply_targets]
        if "All Tables" in default_targets and len(default_targets) > 1:
            default_targets = ["All Tables"]
        applies_to = safe_multiselect(
            "Applies To",
            options=apply_targets,
            default=default_targets,
            key=f"weight_applies_to_{index}",
            reset_invalid_to_default=True,
            help="`All Tables` is the base weight layer. Banner-level or comparison-level weights stack on top of it.",
        )
        if "All Tables" in applies_to and len(applies_to) > 1:
            applies_to = ["All Tables"]
        source_summary = variable_labels.get(effective_source, effective_source) if effective_source else "the full sample"
        weighted_variables_summary = ", ".join(variable_labels.get(value, value) for value in variables) or "no weighting variable"
        if normalize_text(target).casefold() == "custom percentages":
            target_summary = "your custom percentages"
        elif normalize_text(target).casefold() == "average of source groups" or normalize_text(target).casefold().startswith("match "):
            target_summary = f"the equal average distribution across {source_summary}"
        elif normalize_text(target).casefold() == "total":
            target_summary = "the combined eligible respondent distribution"
        else:
            target_summary = f"the distribution from {target}"
        limit_summary = (
            f"where {variable_labels.get(limit_variable, limit_variable)} is {', '.join(limit_values)}"
            if limit_variable and limit_values
            else "for all respondents"
        )
        st.caption(
            f"This weight adjusts {weighted_variables_summary} within each {source_summary} group "
            f"to match {target_summary}, {limit_summary}."
        )
        rendered_weights.append(
            {
                "name": name.strip(),
                "target": target,
                "source": source,
                "variables": variables,
                "limit_variable": limit_variable,
                "limit_values": limit_values,
                "custom_targets": custom_targets,
                "applies_to": applies_to,
            }
        )

    st.session_state.weighting_config = {
        "weights": rendered_weights,
    }

    validation = validate_analysis_config(
        st.session_state.weighting_config,
        st.session_state.banner_config or build_default_banner_config(),
        st.session_state.global_filters or {"rows": []},
        {},
    )
    weight_issues = [message for message in validation if message.startswith("Weight ")]
    if weight_issues:
        for message in weight_issues:
            st.warning(message)
    else:
        st.success("Weighting configuration saved.")


def render_step_10() -> None:
    """Render the statistical setup scaffold."""
    st.header("11. Statistical Setup")
    if not st.session_state.stat_config:
        st.session_state.stat_config = build_default_stat_config()

    stored_confidence_intervals = normalize_confidence_intervals(
        st.session_state.stat_config.get("confidence_intervals", [95])
    )
    ci_col_1, ci_col_2 = st.columns(2)
    confidence_interval_primary = ci_col_1.selectbox(
        "Confidence Interval (C.I)",
        options=CONFIDENCE_INTERVAL_OPTIONS,
        index=CONFIDENCE_INTERVAL_OPTIONS.index(stored_confidence_intervals[0]),
        format_func=lambda value: f"{value}%",
    )
    secondary_options = [""] + [
        value
        for value in CONFIDENCE_INTERVAL_OPTIONS
        if int(value) < int(confidence_interval_primary)
    ]
    secondary_default = stored_confidence_intervals[1] if len(stored_confidence_intervals) > 1 else ""
    if secondary_default not in secondary_options:
        secondary_default = ""
    confidence_interval_secondary = ci_col_2.selectbox(
        "Second C.I (Optional)",
        options=secondary_options,
        index=(secondary_options.index(secondary_default) if secondary_default in secondary_options else 0),
        format_func=lambda value: f"{value}%" if value else "None",
    )
    test_enabled = st.checkbox(
        "Enable independent two-sample z-test scaffold",
        value=bool(st.session_state.stat_config.get("enabled", True)),
    )
    include_n_count = st.checkbox(
        "Include N Count in Banner Table Export",
        value=bool(st.session_state.stat_config.get("include_n_count", False)),
        help="When checked, exported banner tables will include a second row for respondent counts under each percentage row.",
    )
    include_lift = st.checkbox(
        "Include lift",
        value=bool(st.session_state.stat_config.get("include_lift", False)),
        help="This lift setting works with the topline sheet. When both Statistical Setup and Topline Configuration include lift, topline notes will call out significant control vs test differences with point lift.",
    )

    comparison_scope_options = [("lowest_banner_level", "All banner splits within each banner")]
    comparison_col = st.session_state.get("comparison_col")
    if comparison_col:
        comparison_scope_options.insert(0, ("control_vs_test", "Control vs test within each banner"))

    current_scope = st.session_state.stat_config.get("comparison_scope", "lowest_banner_level")
    valid_scope_ids = [option_id for option_id, _ in comparison_scope_options]
    if current_scope not in valid_scope_ids:
        current_scope = valid_scope_ids[0]

    comparison_scope = st.selectbox(
        "Statistical Comparisons",
        options=valid_scope_ids,
        index=valid_scope_ids.index(current_scope),
        format_func=lambda value: dict(comparison_scope_options).get(value, value),
    )

    selected_confidence_intervals = [int(confidence_interval_primary)]
    if confidence_interval_secondary:
        selected_confidence_intervals.append(int(confidence_interval_secondary))

    st.session_state.stat_config = {
        "confidence_intervals": normalize_confidence_intervals(
            [int(value) for value in selected_confidence_intervals]
        ),
        "alpha": DEFAULT_ALPHA,
        "enabled": test_enabled,
        "include_n_count": include_n_count,
        "include_lift": include_lift,
        "comparison_scope": comparison_scope,
    }

    issues = validate_statistical_setup(st.session_state.stat_config)
    if issues:
        for issue in issues:
            st.warning(issue)
    else:
        st.success("Statistical setup scaffold is valid.")
    run_placeholder_significance()


def render_step_11() -> None:
    """Render the table generator and export scaffold."""
    st.header("12. Table Generator & Excel Export")
    readiness = describe_generation_readiness(DEFAULT_STATE, st.session_state)
    for line in readiness:
        st.write(f"- {line}")

    if st.button("Generate Placeholder Tables", type="primary"):
        st.session_state.generated_tables = generate_placeholder_tables(
            st.session_state.cleaned_df,
            st.session_state.question_metadata,
        )
        st.success("Generated placeholder table package.")

    preview = build_placeholder_table_preview(st.session_state.generated_tables)
    if not preview.empty:
        st.subheader("Preview")
        st.dataframe(preview, use_container_width=True)

    if st.session_state.generated_tables:
        export_name = dataframe_to_download_name(st.session_state.uploaded_filename, "bls_tables.xlsx")
        excel_bytes = export_tables_to_excel_bytes(st.session_state.generated_tables)
        st.download_button(
            "Download Excel Workbook",
            data=excel_bytes,
            file_name=export_name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


def main() -> None:
    """Run the Streamlit app."""
    init_session_state()
    step = render_sidebar()

    if step == "1. Data Intake":
        render_step_1()
    elif step == "2. Survey Question Audit":
        render_step_3()
    elif step == "3. Scale Mapping & Polarity":
        render_step_4()
    elif step == "4. Net Definitions":
        render_step_5_nets()
    elif step == "5. Custom Variable Builder":
        render_step_6()
    elif step == "6. Banner Configuration":
        render_step_7()
    elif step == "7. Filter Configuration":
        render_step_8()
    elif step == "8. Weighting Configuration":
        render_step_9()
    elif step == "9. Statistical Setup":
        render_step_10()
    elif step == "10. Table Generator & Excel Export":
        render_step_11()

    render_page_navigation(step)


if __name__ == "__main__":
    main()
