"""Streamlit entrypoint for the BLS Smart Tables Tool."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.cleaning import ingest_qualtrics_dataframe, ingest_qualtrics_excel
from src.io import get_excel_sheet_names
from src.config import (
    build_default_banner_config,
    build_default_stat_config,
    build_default_weighting_config,
    validate_analysis_config,
)
from src.custom_vars import (
    add_custom_variable_stub,
    list_custom_variable_summaries,
    validate_custom_variable_name,
)
from src.mapping import (
    build_default_scale_mapping,
    flip_scale_mapping,
    identify_scale_questions,
    update_scale_mapping_from_editor,
)
from src.metadata import (
    build_metadata_change_log_entry,
    build_question_metadata,
    get_metadata_editor_columns,
    merge_metadata_editor_with_source,
    prepare_metadata_editor_frame,
    restore_metadata_defaults,
    sanitize_metadata_editor,
)
from src.state import DEFAULT_STATE, init_session_state, reset_project_state
from src.stats import (
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
from src.utils import (
    dataframe_to_download_name,
    format_timestamp,
    normalize_text,
)

st.set_page_config(
    page_title="BLS Smart Tables Tool",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


NAV_STEPS = [
    "1. Data Intake",
    "2. Survey Question Audit",
    "3. Scale Mapping & Polarity",
    "4. Custom Variable Builder",
    "5. Analysis Configuration",
    "6. Statistical Setup",
    "7. Table Generator & Excel Export",
]


def _append_log(message: str) -> None:
    """Append a timestamped log message to the session log."""
    st.session_state.ingestion_log.append(f"[{format_timestamp()}] {message}")


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
        if st.button("Reset Project", type="secondary", use_container_width=True):
            reset_project_state()
            st.rerun()

        st.caption("Project status")
        uploaded = st.session_state.uploaded_filename or "No file uploaded"
        st.write(f"File: `{uploaded}`")
        cleaned_df = st.session_state.cleaned_df
        if isinstance(cleaned_df, pd.DataFrame) and not cleaned_df.empty:
            st.write(f"Rows: `{len(cleaned_df):,}`")
            st.write(f"Columns: `{len(cleaned_df.columns):,}`")
        else:
            st.write("Rows: `0`")
            st.write("Columns: `0`")
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
        "4. Custom Variable Builder",
        "5. Analysis Configuration",
        "6. Statistical Setup",
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
    previous_included = st.session_state.get("included_columns", [])
    if previous_included:
        included_columns = [column for column in previous_included if column in available_columns]
        included_columns.extend([column for column in available_columns if column not in included_columns])
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
                        st.success("Column choices reset to the default blacklist.")
                        st.rerun()
            else:
                st.caption("No blacklisted columns are configured for this intake.")


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
                        f"[{timestamp}] {variable}: Answer choices updated"
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
    st.header("3. Scale Mapping & Polarity")
    cleaned_df = st.session_state.cleaned_df
    question_labels = st.session_state.question_labels
    question_metadata = st.session_state.question_metadata

    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty:
        st.info("Upload and process a dataset in Step 1 before mapping scales.")
        return

    scale_questions = identify_scale_questions(question_metadata)
    if not scale_questions:
        st.info("No questions are currently marked as `Scale / Likert`.")
        return

    st.write(
        "Map each response option to an ordered numeric bucket. Use `Flip Polarity` when higher "
        "numbers should represent more negative sentiment."
    )

    for question in scale_questions:
        variable = question["variable"]
        label = question["question_label"]
        st.markdown(f"### {variable}")
        st.caption(label)

        if variable not in st.session_state.scale_mappings:
            st.session_state.scale_mappings[variable] = build_default_scale_mapping(cleaned_df[variable])

        mapping_df = pd.DataFrame(st.session_state.scale_mappings[variable]["rows"])
        editor_key = f"scale_editor_{variable}"
        edited = st.data_editor(
            mapping_df,
            key=editor_key,
            use_container_width=True,
            num_rows="fixed",
            hide_index=True,
            column_config={
                "response_value": st.column_config.TextColumn("Response Value", disabled=True),
                "bucket": st.column_config.NumberColumn("Bucket", min_value=1, step=1),
                "top_box_eligible": st.column_config.CheckboxColumn("Top/Bottom Box Eligible"),
            },
        )

        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
        with btn_col1:
            if st.button("Save Mapping", key=f"save_mapping_{variable}", use_container_width=True):
                st.session_state.scale_mappings[variable] = update_scale_mapping_from_editor(
                    st.session_state.scale_mappings[variable],
                    edited,
                )
                st.success(f"Saved mapping for {variable}.")
        with btn_col2:
            if st.button("Flip Polarity", key=f"flip_mapping_{variable}", use_container_width=True):
                st.session_state.scale_mappings[variable] = flip_scale_mapping(
                    st.session_state.scale_mappings[variable]
                )
                st.success(f"Polarity flipped for {variable}.")
                st.rerun()
        with btn_col3:
            direction = st.session_state.scale_mappings[variable]["polarity"]
            st.caption(f"Current polarity: `{direction}`")


def render_step_5() -> None:
    """Render the custom variable builder scaffold."""
    st.header("4. Custom Variable Builder")
    st.write(
        "V1 includes the structure and persistent state for custom variables. "
        "Production transformation logic is intentionally deferred to a later version."
    )
    name = st.text_input("Custom variable name", key="custom_var_name")
    expression = st.text_area(
        "Logic description",
        key="custom_var_expression",
        help="Describe the rule or formula you want this derived variable to apply later.",
    )
    if st.button("Save Custom Variable", use_container_width=False):
        valid, message = validate_custom_variable_name(name, st.session_state.custom_variables)
        if not valid:
            st.error(message)
        else:
            st.session_state.custom_variables = add_custom_variable_stub(
                st.session_state.custom_variables,
                name=name,
                expression=expression,
            )
            st.success(f"Stored custom variable scaffold for `{name}`.")

    summaries = list_custom_variable_summaries(st.session_state.custom_variables)
    if summaries:
        st.dataframe(pd.DataFrame(summaries), use_container_width=True)
    else:
        st.caption("No custom variables configured yet.")


def render_step_6() -> None:
    """Render the analysis configuration scaffold."""
    st.header("5. Analysis Configuration")
    st.write(
        "V1 stores banner, weighting, and filter settings so the workflow remains coherent across reruns."
    )

    if not st.session_state.weighting_config:
        st.session_state.weighting_config = build_default_weighting_config()
    if not st.session_state.banner_config:
        st.session_state.banner_config = build_default_banner_config()

    left, right = st.columns(2)
    with left:
        weighting_enabled = st.checkbox(
            "Enable weighting scaffold",
            value=st.session_state.weighting_config.get("enabled", False),
        )
        weight_var = st.text_input(
            "Weight variable",
            value=st.session_state.weighting_config.get("weight_variable", ""),
        )
    with right:
        banner_variables = st.text_input(
            "Banner variables (comma separated)",
            value=", ".join(st.session_state.banner_config.get("banner_variables", [])),
        )
        global_filter = st.text_input(
            "Global filter expression",
            value=st.session_state.global_filters.get("expression", ""),
        )

    st.session_state.weighting_config = {
        "enabled": weighting_enabled,
        "weight_variable": weight_var.strip(),
    }
    st.session_state.banner_config = {
        "banner_variables": [value.strip() for value in banner_variables.split(",") if value.strip()],
    }
    st.session_state.global_filters = {"expression": global_filter.strip()}

    validation = validate_analysis_config(
        st.session_state.weighting_config,
        st.session_state.banner_config,
        st.session_state.global_filters,
    )
    if validation:
        for message in validation:
            st.warning(message)
    else:
        st.success("Analysis configuration scaffold is valid.")


def render_step_7() -> None:
    """Render the statistical setup scaffold."""
    st.header("6. Statistical Setup")
    if not st.session_state.stat_config:
        st.session_state.stat_config = build_default_stat_config()

    alpha = st.number_input(
        "Alpha",
        min_value=0.001,
        max_value=0.2,
        value=float(st.session_state.stat_config.get("alpha", DEFAULT_ALPHA)),
        step=0.001,
        format="%.3f",
    )
    test_enabled = st.checkbox(
        "Enable independent two-sample z-test scaffold",
        value=bool(st.session_state.stat_config.get("enabled", True)),
    )
    compare_to_control = st.checkbox(
        "Prioritize comparisons against detected control cell",
        value=bool(st.session_state.stat_config.get("compare_to_control", True)),
    )

    st.session_state.stat_config = {
        "alpha": float(alpha),
        "enabled": test_enabled,
        "compare_to_control": compare_to_control,
    }

    issues = validate_statistical_setup(st.session_state.stat_config)
    if issues:
        for issue in issues:
            st.warning(issue)
    else:
        st.success("Statistical setup scaffold is valid.")

    st.json(build_statistical_setup_summary(st.session_state.stat_config))
    run_placeholder_significance()


def render_step_8() -> None:
    """Render the table generator and export scaffold."""
    st.header("7. Table Generator & Excel Export")
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
    elif step == "4. Custom Variable Builder":
        render_step_5()
    elif step == "5. Analysis Configuration":
        render_step_6()
    elif step == "6. Statistical Setup":
        render_step_7()
    elif step == "7. Table Generator & Excel Export":
        render_step_8()

    render_page_navigation(step)


if __name__ == "__main__":
    main()
