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
    DEFAULT_INCLUDE_VALUE,
    build_metadata_change_log_entry,
    build_question_metadata,
    detect_question_types,
    get_metadata_editor_columns,
    prepare_metadata_editor_frame,
    restore_metadata_defaults,
    sanitize_metadata_editor,
    summarize_included_questions,
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
    alpha_letter_sequence,
    coerce_int,
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
    "2. Base Size & Cell Distribution",
    "3. Survey Question Audit",
    "4. Scale Mapping & Polarity",
    "5. Custom Variable Builder",
    "6. Analysis Configuration",
    "7. Statistical Setup",
    "8. Table Generator & Excel Export",
]


def _append_log(message: str) -> None:
    """Append a timestamped log message to the session log."""
    st.session_state.ingestion_log.append(f"[{format_timestamp()}] {message}")


def render_sidebar() -> str:
    """Render global sidebar controls and return the selected workflow step."""
    with st.sidebar:
        st.title("BLS Smart Tables Tool")
        step = st.radio("Workflow", NAV_STEPS, key="nav_step")
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


def render_page_navigation(current_step: str) -> None:
    """Render previous/next page buttons for the guided workflow."""
    current_index = NAV_STEPS.index(current_step)
    left, _, right = st.columns([1, 3, 1])
    with left:
        if current_index > 0 and st.button("Back", use_container_width=True, key=f"back_{current_step}"):
            st.session_state.nav_step = NAV_STEPS[current_index - 1]
            st.rerun()
    with right:
        if current_index < len(NAV_STEPS) - 1 and st.button(
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


def _build_blacklist_editor(blacklist_used: list[str], restored_columns: list[str]) -> pd.DataFrame:
    """Build the editable blacklist state table for Step 1."""
    restored_lookup = {value.lower() for value in restored_columns}
    rows = []
    for column in blacklist_used:
        rows.append(
            {
                "Column": column,
                "Blacklisted": column.lower() not in restored_lookup,
            }
        )
    return pd.DataFrame(rows)


def _apply_intake_result(result) -> None:
    """Persist a completed intake result into session state."""
    st.session_state.raw_df = result.raw_df
    st.session_state.cleaned_df = result.cleaned_df
    st.session_state.question_labels = result.question_labels
    st.session_state.cell_col = result.cell_column
    st.session_state.blacklist_used = result.blacklist_used
    st.session_state.ingestion_log = result.log_lines
    st.session_state.metadata_rows_removed = result.metadata_rows_removed
    st.session_state.removed_column_count = len(result.removed_columns)
    st.session_state.removed_columns = result.removed_columns
    st.session_state.blank_cell_rows_removed = result.blank_cell_rows_removed
    st.session_state.sheet_name = result.sheet_name
    st.session_state.ingestion_completed_at = result.completed_at
    st.session_state.cell_config_editor = None
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


def render_step_1() -> None:
    """Render the data intake page."""
    st.header("1. Data Intake")
    st.write(
        "Upload a Qualtrics Excel export. The app will preserve question labels, "
        "remove metadata rows, drop configurable technical columns, and require a valid `cell` column."
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

            if st.button("Process Intake", type="primary", use_container_width=False):
                try:
                    result = ingest_qualtrics_excel(upload, sheet_name=selected_sheet)
                except Exception as exc:  # pragma: no cover - defensive Streamlit boundary
                    st.error(f"Upload failed: {exc}")
                    _append_log(f"Upload failed for {upload.name}: {exc}")
                else:
                    st.session_state.blacklist_catalog = result.removed_columns.copy()
                    st.session_state.restored_columns = []
                    _apply_intake_result(result)
                    st.session_state.metadata_change_log = []
                    _append_log(f"Ingestion complete for {upload.name}.")
                    st.success(f"File processed successfully from sheet `{selected_sheet}`.")

    cleaned_df = st.session_state.cleaned_df
    if isinstance(cleaned_df, pd.DataFrame) and not cleaned_df.empty:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Metadata rows removed", st.session_state.get("metadata_rows_removed", 0))
        col2.metric("Columns removed", st.session_state.get("removed_column_count", 0))
        col3.metric(
            "Respondents removed for blank cell",
            st.session_state.get("blank_cell_rows_removed", 0),
        )
        col4.metric("Columns retained", len(cleaned_df.columns))

        st.subheader("Intake Summary")
        summary_left, summary_right = st.columns([1.2, 1])
        with summary_left:
            if st.session_state.cell_col:
                st.dataframe(
                    _build_cell_summary_frame(cleaned_df, st.session_state.cell_col),
                    use_container_width=True,
                    hide_index=True,
                )
        with summary_right:
            st.write(f"Sheet referenced: `{st.session_state.sheet_name}`")
            st.write(f"Columns currently counted: `{len(cleaned_df.columns)}`")
            st.write(f"Blacklisted columns removed: `{st.session_state.removed_column_count}`")
            st.write(f"Time of completed intake: `{st.session_state.ingestion_completed_at}`")

        with st.expander("Blacklisted Columns", expanded=True):
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
                        "Blacklisted": st.column_config.CheckboxColumn(
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
                            if not bool(row.get("Blacklisted", True))
                        ]
                        refreshed = ingest_qualtrics_dataframe(
                            raw_df=st.session_state.raw_df,
                            source_name=st.session_state.uploaded_filename or "uploaded_file",
                            sheet_name=st.session_state.sheet_name or "Sheet1",
                            blacklist=st.session_state.blacklist_catalog,
                            whitelist_columns=restored_columns,
                        )
                        st.session_state.restored_columns = restored_columns
                        _apply_intake_result(refreshed)
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
                        st.session_state.blacklist_editor = _build_blacklist_editor(
                            st.session_state.blacklist_catalog,
                            [],
                        )
                        st.success("Column choices reset to the default blacklist.")
                        st.rerun()
            else:
                st.caption("No blacklisted columns are configured for this intake.")


def _default_cell_config(cleaned_df: pd.DataFrame, cell_col: str) -> pd.DataFrame:
    """Build the default editable cell configuration table."""
    cell_counts = (
        cleaned_df[cell_col]
        .astype(str)
        .map(lambda x: x.strip())
        .value_counts(dropna=False)
        .sort_index()
    )
    letters = alpha_letter_sequence(len(cell_counts))
    rows = []
    for index, (cell_name, base_n) in enumerate(cell_counts.items(), start=1):
        rows.append(
            {
                "Cell Name": cell_name,
                "Locked N": int(base_n),
                "Letter": letters[index - 1],
                "Sort Order": index,
            }
        )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        control_mask = frame["Cell Name"].astype(str).str.contains("control", case=False, na=False)
        if control_mask.any():
            first_control = frame[control_mask].index[0]
            frame.loc[first_control, "Notes"] = "Auto-detected control cell"
        else:
            frame["Notes"] = ""
    return frame


def render_step_2() -> None:
    """Render the base size and cell distribution page."""
    st.header("2. Base Size & Cell Distribution")
    cleaned_df = st.session_state.cleaned_df
    cell_col = st.session_state.cell_col

    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty or not cell_col:
        st.info("Upload and process a dataset in Step 1 before configuring cell bases.")
        return

    st.write(
        "This step locks the permanent starting base size for each cell before any later filtering. "
        "These values are stored separately and are never recalculated automatically."
    )

    col1, col2, col3 = st.columns(3)
    col1.metric("Total N", f"{len(cleaned_df):,}")
    col2.metric("Questions detected", f"{len(cleaned_df.columns):,}")
    col3.metric("Unique cells", f"{cleaned_df[cell_col].nunique(dropna=True):,}")

    if "cell_config_editor" not in st.session_state:
        st.session_state.cell_config_editor = _default_cell_config(cleaned_df, cell_col)

    edited = st.data_editor(
        st.session_state.cell_config_editor,
        key="cell_config_grid",
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "Cell Name": st.column_config.TextColumn(disabled=True),
            "Locked N": st.column_config.NumberColumn(min_value=0, step=1, required=True),
            "Letter": st.column_config.TextColumn(required=True, max_chars=3),
            "Sort Order": st.column_config.NumberColumn(min_value=1, step=1, required=True),
            "Notes": st.column_config.TextColumn(disabled=True),
        },
    )

    validation_errors: list[str] = []
    if not edited.empty:
        letters = [normalize_text(value) for value in edited["Letter"].tolist()]
        sort_orders = [coerce_int(value, default=-1) for value in edited["Sort Order"].tolist()]
        if "" in letters:
            validation_errors.append("Each cell needs a non-empty significance letter.")
        if len(letters) != len(set(letters)):
            validation_errors.append("Cell letters must be unique.")
        if len(sort_orders) != len(set(sort_orders)):
            validation_errors.append("Sort order values must be unique.")
        if any(value < 1 for value in sort_orders):
            validation_errors.append("Sort order values must be positive integers.")

    if validation_errors:
        for error in validation_errors:
            st.error(error)
    else:
        st.session_state.cell_config_editor = edited.copy()
        ordered = edited.sort_values("Sort Order").reset_index(drop=True)
        st.session_state.cell_letter_map = dict(
            zip(ordered["Cell Name"].astype(str), ordered["Letter"].astype(str))
        )
        st.session_state.locked_cell_bases = dict(
            zip(ordered["Cell Name"].astype(str), ordered["Locked N"].astype(int))
        )
        st.session_state.cell_sort_order = dict(
            zip(ordered["Cell Name"].astype(str), ordered["Sort Order"].astype(int))
        )
        st.success("Locked bases and significance letters saved.")


def render_step_3() -> None:
    """Render the question audit page."""
    st.header("3. Survey Question Audit")
    cleaned_df = st.session_state.cleaned_df
    question_labels = st.session_state.question_labels
    cell_col = st.session_state.cell_col

    if not isinstance(cleaned_df, pd.DataFrame) or cleaned_df.empty:
        st.info("Upload and process a dataset in Step 1 before auditing questions.")
        return

    if not st.session_state.question_metadata:
        st.session_state.question_metadata = build_question_metadata(cleaned_df, question_labels, cell_col)

    detected_types = detect_question_types(cleaned_df, question_labels, cell_col)
    st.caption(
        f"Included questions: {summarize_included_questions(st.session_state.question_metadata)}. "
        f"Defaults use the heuristic classifier in `src/metadata.py`."
    )

    editor_df = prepare_metadata_editor_frame(st.session_state.question_metadata)
    edited = st.data_editor(
        editor_df,
        key="question_audit_grid",
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        column_config=get_metadata_editor_columns(),
    )

    log_col, action_col = st.columns([2, 1])
    with action_col:
        if st.button("Update Changes", type="primary", use_container_width=True):
            sanitized = sanitize_metadata_editor(edited)
            previous = {row["variable"]: row for row in st.session_state.question_metadata}
            for row in sanitized:
                variable = row["variable"]
                old_type = previous.get(variable, {}).get("detected_type")
                new_type = row["detected_type"]
                if old_type != new_type:
                    st.session_state.metadata_change_log.append(
                        build_metadata_change_log_entry(variable, old_type, new_type)
                    )
            st.session_state.question_metadata = sanitized
            st.success("Question audit changes saved.")

        if st.button("Reset Defaults", use_container_width=True):
            st.session_state.question_metadata = restore_metadata_defaults(
                cleaned_df,
                question_labels,
                cell_col,
            )
            st.success("Question metadata restored to defaults.")
            st.rerun()

    with log_col:
        st.subheader("Heuristic Summary")
        summary_df = pd.DataFrame(
            {
                "variable": list(detected_types.keys()),
                "detected_type": list(detected_types.values()),
            }
        )
        st.dataframe(summary_df, use_container_width=True, height=220)

    st.subheader("Change Log")
    if st.session_state.metadata_change_log:
        for entry in reversed(st.session_state.metadata_change_log[-15:]):
            st.code(entry)
    else:
        st.caption("No manual changes yet.")


def render_step_4() -> None:
    """Render the scale mapping and polarity page."""
    st.header("4. Scale Mapping & Polarity")
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
    st.header("5. Custom Variable Builder")
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
    st.header("6. Analysis Configuration")
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
    st.header("7. Statistical Setup")
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
    st.header("8. Table Generator & Excel Export")
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
    elif step == "2. Base Size & Cell Distribution":
        render_step_2()
    elif step == "3. Survey Question Audit":
        render_step_3()
    elif step == "4. Scale Mapping & Polarity":
        render_step_4()
    elif step == "5. Custom Variable Builder":
        render_step_5()
    elif step == "6. Analysis Configuration":
        render_step_6()
    elif step == "7. Statistical Setup":
        render_step_7()
    elif step == "8. Table Generator & Excel Export":
        render_step_8()

    render_page_navigation(step)


if __name__ == "__main__":
    main()
