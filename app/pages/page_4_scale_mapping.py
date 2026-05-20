"""Scale mapping page."""

from __future__ import annotations

import hashlib

import pandas as pd
import streamlit as st

from src.mapping import (
    build_scale_change_log,
    build_scale_mapping_editor_frame,
    build_scale_mapping_options,
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
        st.session_state.scale_mapping_editor_key = f"scale_mapping_grid_{scale_signature[:10]}"
    return st.session_state.get("scale_mapping_editor_key", f"scale_mapping_grid_{scale_signature[:10]}")


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
        "Review scale questions in one table. Each row is a scale question and each column is a "
        "scale point in order from 1 to n."
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
    scale_options = build_scale_mapping_options(st.session_state.scale_mappings)

    point_columns = [column for column in editor_df.columns if column.startswith("scale_point_")]
    ordered_columns = [*BASE_SCALE_COLUMNS, *point_columns]
    editor_df = editor_df[ordered_columns]

    column_config = {
        "variable": st.column_config.TextColumn("Raw Variable Name", disabled=True, width="medium"),
        "display_variable_name": st.column_config.TextColumn("Displayed Variable Name", disabled=True, width="medium"),
        "question_label": st.column_config.TextColumn("Question Text", disabled=True, width="large"),
        "polarity": st.column_config.SelectboxColumn(
            "Polarity",
            options=["standard", "flipped"],
            width="small",
            help="Use `flipped` when the lowest score should become the highest score.",
        ),
    }
    for index, column in enumerate(point_columns, start=1):
        column_config[column] = st.column_config.SelectboxColumn(
            f"Scale Point {index}",
            options=scale_options,
            width="medium",
        )

    edited = st.data_editor(
        editor_df,
        key=editor_key,
        use_container_width=True,
        num_rows="fixed",
        hide_index=True,
        height=560,
        column_order=ordered_columns,
        column_config=column_config,
    )

    normalized_edited = _normalize_editor_frame(
        edited,
        scale_questions,
        st.session_state.scale_mappings,
    )

    if st.button("Save Mappings", type="primary", use_container_width=True):
        issues = validate_scale_mapping_editor(normalized_edited)
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
            st.rerun()

    st.subheader("Change Log")
    if st.session_state.get("scale_change_log"):
        for entry in reversed(st.session_state.scale_change_log[-15:]):
            st.code(entry)
    else:
        st.caption("No scale mapping changes yet.")
