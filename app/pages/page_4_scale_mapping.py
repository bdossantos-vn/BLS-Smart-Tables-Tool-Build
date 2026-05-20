"""Scale mapping page."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from src.mapping import (
    build_scale_change_log,
    build_scale_mapping_editor_frame,
    build_scale_mapping_options_by_variable,
    ensure_scale_mappings,
    identify_scale_questions,
    save_scale_mapping_editor,
    validate_scale_mapping_editor,
)
from src.utils import format_timestamp, normalize_text


SCALE_SEED_VERSION = 1
BASE_SCALE_COLUMNS = ["variable", "display_variable_name", "question_label", "polarity"]


def _build_scale_signature(scale_questions: list[dict[str, object]]) -> str:
    """Build a stable signature for the current scale-question schema."""
    parts: list[str] = []
    for row in scale_questions:
        variable = normalize_text(row.get("variable"))
        display_name = normalize_text(row.get("display_variable_name"))
        label = normalize_text(row.get("question_label"))
        choices = [normalize_text(choice) for choice in row.get("answer_choices_list", []) if normalize_text(choice)]
        parts.append(f"{variable}|{display_name}|{label}|{'~'.join(choices)}")
    return hashlib.md5("||".join(parts).encode("utf-8")).hexdigest()


def _normalize_editor_frame(
    editor_df: pd.DataFrame,
    scale_questions: list[dict[str, object]],
    scale_mappings: dict[str, dict[str, object]],
) -> pd.DataFrame:
    """Return an editor frame with a guaranteed stable schema and row order."""
    expected_df = build_scale_mapping_editor_frame(scale_questions, scale_mappings)
    expected_columns = list(expected_df.columns)

    if editor_df is None or editor_df.empty:
        return expected_df

    normalized_df = editor_df.copy()
    for column in expected_columns:
        if column not in normalized_df.columns:
            normalized_df[column] = expected_df[column]

    normalized_df = normalized_df[expected_columns]

    if "variable" not in normalized_df.columns:
        return expected_df

    normalized_df = normalized_df.set_index("variable", drop=False)
    expected_df = expected_df.set_index("variable", drop=False)
    normalized_df = normalized_df.reindex(expected_df.index)

    for column in expected_columns:
        normalized_df[column] = normalized_df[column].where(
            normalized_df[column].notna(),
            expected_df[column],
        )

    return normalized_df.reset_index(drop=True)


def _get_editor_key(scale_signature: str) -> str:
    """Return a session-stable editor key that refreshes when schema changes."""
    existing_signature = st.session_state.get("scale_mapping_editor_signature", "")
    if existing_signature != scale_signature:
        st.session_state.scale_mapping_editor_signature = scale_signature
        st.session_state.scale_mapping_editor_revision = 0

    revision = int(st.session_state.get("scale_mapping_editor_revision", 0))
    return f"scale_mapping_grid_{scale_signature[:10]}_{revision}"


def _selectbox_index(options: list[str], value: object) -> int:
    """Return the option index for a saved value, defaulting to blank."""
    normalized_value = normalize_text(value)
    return options.index(normalized_value) if normalized_value in options else 0


def _render_scale_mapping_controls(
    editor_df: pd.DataFrame,
    options_by_variable: dict[str, list[str]],
    editor_key: str,
) -> pd.DataFrame:
    """Render row-level scale controls with question-specific dropdown options."""
    point_columns = [column for column in editor_df.columns if column.startswith("scale_point_")]
    edited_rows: list[dict[str, object]] = []

    for row_index, row in enumerate(editor_df.to_dict(orient="records")):
        variable = normalize_text(row.get("variable"))
        display_name = normalize_text(row.get("display_variable_name")) or variable
        question_label = normalize_text(row.get("question_label"))
        row_options = options_by_variable.get(variable, [""])
        if not row_options:
            row_options = [""]

        edited_row: dict[str, object] = {
            "variable": variable,
            "display_variable_name": display_name,
            "question_label": question_label,
        }

        with st.container(border=True):
            info_col, polarity_col = st.columns([4, 1])
            with info_col:
                st.markdown(f"**{display_name}**")
                st.caption(f"Raw variable: `{variable}`")
                if question_label:
                    st.write(question_label)
            with polarity_col:
                polarity_options = ["standard", "flipped"]
                polarity = normalize_text(row.get("polarity")) or "standard"
                edited_row["polarity"] = st.selectbox(
                    "Polarity",
                    options=polarity_options,
                    index=polarity_options.index(polarity) if polarity in polarity_options else 0,
                    key=f"{editor_key}_{variable}_{row_index}_polarity",
                    help="Use `flipped` when the lowest score should become the highest score.",
                )

            for chunk_start in range(0, len(point_columns), 5):
                chunk = point_columns[chunk_start : chunk_start + 5]
                scale_cols = st.columns(len(chunk))
                for chunk_index, column in enumerate(chunk):
                    scale_number = point_columns.index(column) + 1
                    edited_row[column] = scale_cols[chunk_index].selectbox(
                        f"Scale Point {scale_number}",
                        options=row_options,
                        index=_selectbox_index(row_options, row.get(column)),
                        key=f"{editor_key}_{variable}_{row_index}_{column}",
                    )

        edited_rows.append(edited_row)

    return pd.DataFrame(edited_rows, columns=list(editor_df.columns))


def render() -> None:
    """Render the Scale Mapping page."""
    st.header("4. Scale Mapping & Polarity")

    cleaned_df = st.session_state.get("cleaned_df")
    question_metadata = st.session_state.get("question_metadata", [])

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
        "Review scale questions and set the response order from scale point 1 to n. "
        "Each question uses only its own response options."
    )

    if (
        st.session_state.get("scale_mapping_seed_version", 0) < SCALE_SEED_VERSION
        and not st.session_state.get("scale_change_log")
    ):
        st.session_state.scale_mappings = {}
        st.session_state.scale_mapping_seed_version = SCALE_SEED_VERSION

    st.session_state.scale_mappings = ensure_scale_mappings(
        scale_questions,
        cleaned_df,
        st.session_state.get("scale_mappings", {}),
    )

    editor_df = _normalize_editor_frame(
        build_scale_mapping_editor_frame(scale_questions, st.session_state.scale_mappings),
        scale_questions,
        st.session_state.scale_mappings,
    )
    scale_signature = _build_scale_signature(scale_questions)
    editor_key = _get_editor_key(scale_signature)
    scale_options_by_variable = build_scale_mapping_options_by_variable(
        scale_questions,
        cleaned_df,
        st.session_state.scale_mappings,
    )

    point_columns = [column for column in editor_df.columns if column.startswith("scale_point_")]
    ordered_columns = [*BASE_SCALE_COLUMNS, *point_columns]
    editor_df = editor_df[ordered_columns]

    edited = _render_scale_mapping_controls(
        editor_df,
        options_by_variable=scale_options_by_variable,
        editor_key=editor_key,
    )

    normalized_edited = _normalize_editor_frame(
        edited,
        scale_questions,
        st.session_state.scale_mappings,
    )

    if st.button("Save Mappings", type="primary", use_container_width=True):
        issues = validate_scale_mapping_editor(normalized_edited, scale_options_by_variable)
        if issues:
            for issue in issues:
                st.error(issue)
        else:
            previous_mappings = {
                key: value.copy()
                for key, value in st.session_state.scale_mappings.items()
            }
            st.session_state.scale_mappings = save_scale_mapping_editor(
                normalized_edited,
                previous_mappings=st.session_state.scale_mappings,
            )
            timestamp = format_timestamp()
            for change in build_scale_change_log(previous_mappings, st.session_state.scale_mappings):
                st.session_state.scale_change_log.append(f"[{timestamp}] {change}")
            st.session_state.scale_save_message = "Scale mappings saved."
            st.session_state.scale_mapping_editor_revision = (
                int(st.session_state.get("scale_mapping_editor_revision", 0)) + 1
            )
            st.rerun()

    st.subheader("Change Log")
    if st.session_state.get("scale_change_log"):
        for entry in reversed(st.session_state.scale_change_log[-15:]):
            st.code(entry)
    else:
        st.caption("No scale mapping changes yet.")
