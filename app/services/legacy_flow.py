"""Legacy page rendering logic preserved during the architecture refactor."""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from src.cleaning import ingest_qualtrics_dataframe, ingest_qualtrics_excel
from src.io import get_excel_sheet_names
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
    run_placeholder_significance,
    validate_statistical_setup,
)
from src.tables import (
    build_placeholder_table_preview,
    describe_generation_readiness,
    generate_placeholder_tables,
)
from src.exporter import export_tables_to_excel_bytes
from src.utils import dataframe_to_download_name, format_timestamp, normalize_text


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
        return list(question_lookup[variable].get("answer_choices_list", []))
    for record in custom_variables:
        if normalize_text(record.get("name")) == normalize_text(variable):
            return [normalize_text(bucket.get("label")) for bucket in record.get("buckets", []) if normalize_text(bucket.get("label"))]
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


def _default_comparison_group_order(cleaned_df: pd.DataFrame, comparison_col: str | None) -> dict[str, int]:
    """Build the default row order for the selected comparison variable."""
    if not comparison_col:
        return {"Total": 1}

    values = [normalize_text(value) for value in cleaned_df[comparison_col].dropna().tolist()]
    unique_values = sorted({value for value in values if value})
    if comparison_col.lower() == "cell" and any("control" in value.lower() for value in unique_values):
        ordered = sorted(unique_values, key=lambda value: (0 if "control" in value.lower() else 1, value.lower()))
    else:
        ordered = sorted(unique_values, key=str.lower)
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
    st.session_state.comparison_col = comparison_col
    st.session_state.cell_col = comparison_col
    st.session_state.comparison_rows_removed = rows_removed
    st.session_state.comparison_configured = True
    st.session_state.comparison_group_order = _default_comparison_group_order(filtered_df, comparison_col)
    st.session_state.locked_cell_bases = {
        row["Cell"]: int(row["N"])
        for row in _build_comparison_summary_frame(filtered_df, comparison_col).to_dict(orient="records")
    }
    st.session_state.cell_sort_order = dict(st.session_state.comparison_group_order)
    st.session_state.cell_letter_map = {}
    st.session_state.question_metadata = build_question_metadata(
        filtered_df,
        st.session_state.question_labels,
        comparison_col,
    )
    st.session_state.scale_mappings = {}


def _build_comparison_summary_frame(cleaned_df: pd.DataFrame, comparison_col: str | None) -> pd.DataFrame:
    """Build the summary table for the selected comparison variable."""
    if not comparison_col:
        return pd.DataFrame([{"Cell": "Total", "N": int(len(cleaned_df))}])

    counts = cleaned_df[comparison_col].astype(str).str.strip().value_counts().rename_axis("Cell").reset_index(name="N")
    order_map = st.session_state.get("comparison_group_order", {})
    if order_map:
        counts["sort_order"] = counts["Cell"].map(lambda value: order_map.get(value, 9999))
        counts = counts.sort_values(["sort_order", "Cell"]).drop(columns=["sort_order"]).reset_index(drop=True)
    else:
        counts = counts.sort_values("Cell").reset_index(drop=True)
    return counts


def _build_comparison_order_editor(cleaned_df: pd.DataFrame, comparison_col: str | None) -> pd.DataFrame:
    """Build an editable order table for comparison groups."""
    summary = _build_comparison_summary_frame(cleaned_df, comparison_col)
    order_map = st.session_state.get("comparison_group_order", {})
    summary["Sort Order"] = summary["Cell"].map(lambda value: order_map.get(value, 1)).astype(int)
    return summary[["Cell", "N", "Sort Order"]]


def _current_included_count() -> int:
    """Return the current number of included columns in the working dataset."""
    cleaned_df = st.session_state.get("cleaned_df")
    if isinstance(cleaned_df, pd.DataFrame):
        return len(cleaned_df.columns)
    return 0


def _current_excluded_count() -> int:
    """Return the current total number of excluded columns across all intake controls."""
    survey_df = st.session_state.get("survey_df")
    survey_column_count = len(survey_df.columns) if isinstance(survey_df, pd.DataFrame) else 0
    blacklist_catalog = st.session_state.get("blacklist_catalog", [])
    restored_columns = set(st.session_state.get("restored_columns", []))
    active_blacklist_count = sum(1 for column in blacklist_catalog if column not in restored_columns)
    included_count = _current_included_count()
    hidden_included_count = max(survey_column_count - included_count, 0)
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
        row["Cell"]: int(row["N"])
        for row in _build_comparison_summary_frame(
            st.session_state.cleaned_df,
            st.session_state.comparison_col,
        ).to_dict(orient="records")
    }


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


def _build_included_editor(all_columns: list[str], selected_columns: list[str]) -> pd.DataFrame:
    """Build the editable included-columns table for Step 1."""
    selected_lookup = set(selected_columns)
    rows = []
    for column in all_columns:
        rows.append(
            {
                "Column": column,
                "Included": column in selected_lookup,
            }
        )
    return pd.DataFrame(rows)


def _apply_intake_result(result) -> None:
    """Persist a completed intake result into session state."""
    available_columns = [column for column in result.cleaned_df.columns]
    previous_survey_df = st.session_state.get("survey_df")
    previous_available_columns = (
        list(previous_survey_df.columns)
        if isinstance(previous_survey_df, pd.DataFrame) and not previous_survey_df.empty
        else []
    )
    previous_included = st.session_state.get("included_columns", [])
    if previous_included:
        included_columns = [column for column in previous_included if column in available_columns]
        newly_available_columns = [
            column
            for column in available_columns
            if column not in previous_available_columns and column not in included_columns
        ]
        included_columns.extend(newly_available_columns)
    else:
        included_columns = available_columns.copy()

    st.session_state.raw_df = result.raw_df
    st.session_state.survey_df = result.cleaned_df.copy()
    st.session_state.cleaned_df = result.cleaned_df.copy()
    st.session_state.question_labels = result.question_labels
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
    st.session_state.locked_cell_bases = {}
    st.session_state.cell_sort_order = {}
    st.session_state.cell_letter_map = {}
    st.session_state.question_metadata = build_question_metadata(
        result.cleaned_df,
        result.question_labels,
        result.cell_column,
    )
    st.session_state.scale_mappings = {}
    st.session_state.blacklist_editor = _build_blacklist_editor(
        st.session_state.blacklist_catalog,
        st.session_state.get("restored_columns", []),
    )
    st.session_state.included_editor = _build_included_editor(
        available_columns,
        included_columns,
    )


def render_step_1() -> None:
    """Render the data intake page."""
    st.header("1. Data Intake")
    st.write(
        "Upload your Excel file to get started."
    )

    upload = st.file_uploader(
        "Upload Qualtrics Excel export",
        type=["xlsx"],
        key="qualtrics_upload",
        help="Expected format: a standard Qualtrics `.xlsx` export.",
    )

    if upload is not None:
        try:
            available_sheets = get_excel_sheet_names(upload)
        except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
            st.error(f"Upload failed: {exc}")
            _append_log(f"Upload failed for {upload.name}: {exc}")
        else:
            st.session_state.uploaded_filename = upload.name
            st.session_state.available_sheets = available_sheets

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
                    _apply_comparison_selection(default_comparison)
                    st.session_state.metadata_change_log = []
                    _append_log(f"Ingestion complete for {upload.name}.")
                    st.success(f"File processed successfully from sheet `{selected_sheet}`.")

    cleaned_df = st.session_state.cleaned_df
    survey_df = st.session_state.survey_df
    if isinstance(survey_df, pd.DataFrame) and not survey_df.empty:
        st.subheader("Comparison Setup")
        comparison_options = ["None / Total only", *st.session_state.comparison_options]
        default_option = st.session_state.get("comparison_col") or "None / Total only"
        if default_option not in comparison_options:
            default_option = "None / Total only"

        selected_option = st.selectbox(
            "Comparison Variable",
            options=comparison_options,
            index=comparison_options.index(default_option),
            help="`cell` is auto-selected when present, but you can choose another variable or total-only analysis.",
        )
        if st.button("Apply Comparison Variable", use_container_width=False):
            selected_comparison = None if selected_option == "None / Total only" else selected_option
            try:
                _apply_comparison_selection(selected_comparison)
            except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
                st.error(str(exc))
            else:
                label = selected_comparison or "Total only"
                _append_intake_change(f"Comparison variable updated to {label}.")
                if selected_comparison is None:
                    st.success("Comparison variable updated. The project is now set to total-only analysis.")
                else:
                    st.success(f"Comparison variable updated to `{selected_comparison}`.")
                st.rerun()

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
            st.dataframe(
                _build_comparison_summary_frame(cleaned_df, st.session_state.comparison_col),
                use_container_width=True,
                hide_index=True,
            )
        with summary_right:
            st.write(f"Sheet Referenced: `{st.session_state.sheet_name}`")
            st.write(f"Columns Included: `{_current_included_count()}`")
            st.write(f"Columns Excluded: `{_current_excluded_count()}`")
            current_comparison = st.session_state.comparison_col or "Total only"
            st.write(f"Comparison Variable: `{current_comparison}`")

        if st.session_state.comparison_col and len(st.session_state.comparison_group_order) > 1:
            st.subheader("Comparison Group Order")
            st.caption("Use the move buttons to control the display order for comparison groups.")
            ordered_summary = _build_comparison_summary_frame(cleaned_df, st.session_state.comparison_col)
            for row in ordered_summary.to_dict(orient="records"):
                group_name = row["Cell"]
                row_cols = st.columns([4, 1, 0.8, 0.8])
                row_cols[0].write(group_name)
                row_cols[1].write(int(row["N"]))
                if row_cols[2].button("↑", key=f"up_{group_name}", use_container_width=True):
                    _move_comparison_group(group_name, "up")
                    st.rerun()
                if row_cols[3].button("↓", key=f"down_{group_name}", use_container_width=True):
                    _move_comparison_group(group_name, "down")
                    st.rerun()

        with st.expander("Columns Included", expanded=True):
            available_columns = list(survey_df.columns)
            if st.session_state.included_editor is None:
                st.session_state.included_editor = _build_included_editor(
                    available_columns,
                    st.session_state.get("included_columns", available_columns),
                )

            edited_included = st.data_editor(
                st.session_state.included_editor,
                key="included_editor_grid",
                use_container_width=True,
                num_rows="fixed",
                hide_index=True,
                column_config={
                    "Column": st.column_config.TextColumn(disabled=True),
                    "Included": st.column_config.CheckboxColumn(
                        help="Checked means the column stays in the working dataset."
                    ),
                },
            )

            include_left, include_right = st.columns(2)
            include_rows = edited_included.to_dict(orient="records")

            with include_left:
                if st.button("Update Columns", key="update_included_columns", use_container_width=True):
                    previous_included_columns = list(st.session_state.get("included_columns", available_columns))
                    included_columns = [
                        row["Column"]
                        for row in include_rows
                        if bool(row.get("Included", True))
                    ]
                    current_comparison = st.session_state.get("comparison_col")
                    if current_comparison and current_comparison not in included_columns:
                        included_columns = [current_comparison, *included_columns]
                    st.session_state.included_columns = included_columns
                    st.session_state.included_editor = _build_included_editor(
                        available_columns,
                        included_columns,
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
                            summary_bits.append("no included-column changes")
                        _append_intake_change("Included columns updated (" + "; ".join(summary_bits) + ").")
                        st.success("Included columns updated.")
                        st.rerun()

            with include_right:
                if st.button("Reset Columns", key="reset_included_columns", use_container_width=True):
                    st.session_state.included_columns = available_columns.copy()
                    st.session_state.included_editor = _build_included_editor(
                        available_columns,
                        available_columns,
                    )
                    try:
                        _apply_comparison_selection(st.session_state.get("comparison_col"))
                    except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
                        st.error(str(exc))
                    else:
                        _append_intake_change("Included columns reset to all available columns.")
                        st.success("Included columns reset to all available columns.")
                        st.rerun()

        with st.expander("Columns Excluded", expanded=True):
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
                    column_config={
                        "Column": st.column_config.TextColumn(disabled=True),
                        "Excluded": st.column_config.CheckboxColumn(
                            help="Checked means the column stays excluded from the cleaned dataset."
                        ),
                    },
                )

                btn_left, btn_right = st.columns(2)
                blacklist_rows = edited_blacklist.to_dict(orient="records")

                with btn_left:
                    if st.button("Update Columns", use_container_width=True):
                        previous_restored_columns = list(st.session_state.get("restored_columns", []))
                        restored_columns = [
                            row["Column"]
                            for row in blacklist_rows
                            if not bool(row.get("Excluded", True))
                        ]
                        refreshed = ingest_qualtrics_dataframe(
                            raw_df=st.session_state.raw_df,
                            source_name=st.session_state.uploaded_filename or "uploaded_file",
                            sheet_name=st.session_state.sheet_name or "Sheet1",
                            blacklist=st.session_state.blacklist_catalog,
                            whitelist_columns=restored_columns,
                        )
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
                        )
                        st.session_state.blacklist_editor = edited_blacklist.copy()
                        added_back = [column for column in restored_columns if column not in previous_restored_columns]
                        re_excluded = [column for column in previous_restored_columns if column not in restored_columns]
                        summary_bits = []
                        if added_back:
                            summary_bits.append("added back: " + ", ".join(added_back))
                        if re_excluded:
                            summary_bits.append("excluded again: " + ", ".join(re_excluded))
                        if not summary_bits:
                            summary_bits.append("no excluded-column changes")
                        _append_intake_change("Excluded columns updated (" + "; ".join(summary_bits) + ").")
                        if restored_columns:
                            st.success(
                                "Updated intake. Added back column(s): "
                                + ", ".join(restored_columns)
                            )
                        else:
                            st.success("Updated intake. All blacklisted columns remain excluded.")
                        st.rerun()

                with btn_right:
                    if st.button("Reset Columns", use_container_width=True):
                        refreshed = ingest_qualtrics_dataframe(
                            raw_df=st.session_state.raw_df,
                            source_name=st.session_state.uploaded_filename or "uploaded_file",
                            sheet_name=st.session_state.sheet_name or "Sheet1",
                            blacklist=st.session_state.blacklist_catalog,
                            whitelist_columns=[],
                        )
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
                        )
                        st.session_state.blacklist_editor = _build_blacklist_editor(
                            st.session_state.blacklist_catalog,
                            [],
                        )
                        _append_intake_change("Excluded columns reset to the default blacklist.")
                        st.success("Column choices reset to the default blacklist.")
                        st.rerun()
            else:
                st.caption("No blacklisted columns are configured for this intake.")

        st.subheader("Change Log")
        if st.session_state.get("intake_change_log"):
            for entry in reversed(st.session_state.intake_change_log[-20:]):
                st.code(entry)
        else:
            st.caption("No intake changes recorded yet.")


def render_step_3() -> None:
    """Render the question audit page."""
    st.header("2. Survey Question Audit")
    cleaned_df = st.session_state.cleaned_df
    question_labels = st.session_state.question_labels
    cell_col = st.session_state.cell_col

    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty:
        st.info("Upload and process a dataset in Step 1 before auditing questions.")
        return

    if not st.session_state.question_metadata:
        st.session_state.question_metadata = build_question_metadata(cleaned_df, question_labels, cell_col)

    st.caption("Review question types and edit answer-choice labels where needed.")

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
                old_choices = normalize_text(previous_row.get("answer_choices", ""))
                new_choices = normalize_text(row.get("answer_choices", ""))
                if old_choices != new_choices:
                    timestamp = format_timestamp()
                    st.session_state.metadata_change_log.append(
                        f"[{timestamp}] {variable}: Answer choices changed "
                        f"{_summarize_choice_change(old_choices, new_choices)}"
                    )
            st.session_state.question_metadata = sanitized
            st.success("Question audit changes saved.")

    with action_right:
        if st.button("Reset Defaults", use_container_width=True):
            st.session_state.question_metadata = restore_metadata_defaults(
                cleaned_df,
                question_labels,
                cell_col,
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
    st.header("3. Scale Mapping & Polarity")
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
        "variable": st.column_config.TextColumn("Variable Name", disabled=True, width=180),
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
    st.header("4. Net Definitions")
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
            "variable": st.column_config.TextColumn("Variable Name", disabled=True, width=220),
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

    st.header("5. Custom Variable Builder")
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
        variable: f"{variable} - {question_lookup[variable]['question_label']}"
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
            selected_choices = st.multiselect(
                question_labels.get(source_variable, source_variable),
                options=source_choices,
                key=f"custom_bucket_simple_choices_{bucket_index}",
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
                condition_choices = st.multiselect(
                    "Selected Choices",
                    options=question_lookup.get(condition_variable, {}).get("answer_choices_list", []),
                    key=f"custom_condition_choices_{bucket_index}_{condition_index}",
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
    st.header("6. Banner Configuration")
    st.write("Build one or more banners with up to 3 nested levels.")

    if not st.session_state.banner_config:
        st.session_state.banner_config = build_default_banner_config()

    variable_catalog = build_analysis_variable_catalog(
        st.session_state.question_metadata,
        st.session_state.custom_variables,
        st.session_state.get("comparison_col"),
    )
    variable_options = [item["id"] for item in variable_catalog]
    variable_labels = {item["id"]: item["label"] for item in variable_catalog}
    include_total = st.checkbox(
        "Include total column",
        value=bool(st.session_state.banner_config.get("include_total", True)),
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
    st.header("7. Filter Configuration")

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
                values = col3.multiselect(
                    "Values",
                    options=value_options,
                    default=[value for value in condition.get("values", []) if value in value_options],
                    key=f"global_filter_values_{index}_{branch_index}_{condition_index}",
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
        applies_to = st.multiselect(
            "Applies To",
            options=apply_targets,
            default=default_targets,
            key=f"global_filter_applies_to_{index}",
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
    st.header("8. Weighting Configuration")

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
            help="Choose what this weight should match against.",
        )
        source_options = ["", *[value for value in variable_options if value != st.session_state.get("comparison_col")]]
        source = col2.selectbox(
            "Source Variable",
            options=source_options,
            index=(source_options.index(row.get("source", "")) if row.get("source", "") in source_options else 0),
            format_func=lambda value: variable_labels.get(value, value) if value else "Optional source variable",
            key=f"weight_source_{index}",
            help="Optional source variable or metric you want to weight on.",
        )
        variables = st.multiselect(
            "Weighting Variables",
            options=weight_variable_options,
            default=[value for value in row.get("variables", []) if value in weight_variable_options],
            key=f"weight_variables_{index}",
            help="Select one or more variables to use in the weighting scheme.",
        )
        default_targets = [target_value for target_value in row.get("applies_to", []) if target_value in apply_targets]
        if "All Tables" in default_targets and len(default_targets) > 1:
            default_targets = ["All Tables"]
        applies_to = st.multiselect(
            "Applies To",
            options=apply_targets,
            default=default_targets,
            key=f"weight_applies_to_{index}",
            help="`All Tables` is the base weight layer. Banner-level or comparison-level weights stack on top of it.",
        )
        if "All Tables" in applies_to and len(applies_to) > 1:
            applies_to = ["All Tables"]
        rendered_weights.append(
            {
                "name": name.strip(),
                "target": target,
                "source": source,
                "variables": variables,
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
    st.header("8. Statistical Setup")
    if not st.session_state.stat_config:
        st.session_state.stat_config = build_default_stat_config()

    stored_confidence_intervals = [
        value
        for value in st.session_state.stat_config.get("confidence_intervals", [95])
        if value in CONFIDENCE_INTERVAL_OPTIONS
    ] or [95]
    ci_col_1, ci_col_2 = st.columns(2)
    confidence_interval_primary = ci_col_1.selectbox(
        "Confidence Interval (C.I)",
        options=CONFIDENCE_INTERVAL_OPTIONS,
        index=CONFIDENCE_INTERVAL_OPTIONS.index(stored_confidence_intervals[0]),
        format_func=lambda value: f"{value}%",
    )
    secondary_default = stored_confidence_intervals[1] if len(stored_confidence_intervals) > 1 else ""
    confidence_interval_secondary = ci_col_2.selectbox(
        "Second C.I (Optional)",
        options=["", *CONFIDENCE_INTERVAL_OPTIONS],
        index=(["", *CONFIDENCE_INTERVAL_OPTIONS].index(secondary_default) if secondary_default in ["", *CONFIDENCE_INTERVAL_OPTIONS] else 0),
        format_func=lambda value: f"{value}%" if value else "None",
    )
    test_enabled = st.checkbox(
        "Enable independent two-sample z-test scaffold",
        value=bool(st.session_state.stat_config.get("enabled", True)),
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
        if int(confidence_interval_secondary) != int(confidence_interval_primary):
            selected_confidence_intervals.append(int(confidence_interval_secondary))
        else:
            st.warning("Primary and secondary confidence intervals must be different.")

    st.session_state.stat_config = {
        "confidence_intervals": sorted(int(value) for value in selected_confidence_intervals),
        "alpha": DEFAULT_ALPHA,
        "enabled": test_enabled,
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
    st.header("10. Table Generator & Excel Export")
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
