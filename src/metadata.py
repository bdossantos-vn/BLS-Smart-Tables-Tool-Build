"""Question metadata detection and editing helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.utils import normalize_text


DEFAULT_INCLUDE_VALUE = True
QUESTION_TYPES = [
    "Single-Select",
    "Multi-Select",
    "Scale / Likert",
    "Numeric Data",
    "Open-End Text",
    "Ignore",
]

LIKERT_PATTERNS = [
    "strongly disagree",
    "disagree",
    "neutral",
    "agree",
    "strongly agree",
    "very dissatisfied",
    "dissatisfied",
    "satisfied",
    "very satisfied",
]


def _is_multi_select(series: pd.Series) -> bool:
    values = series.dropna().astype(str).str.strip()
    if values.empty:
        return False
    delimiter_ratio = values.str.contains(r"[;,]").mean()
    return float(delimiter_ratio) >= 0.3


def _is_scale(series: pd.Series, question_label: str = "") -> bool:
    values = [normalize_text(value).lower() for value in series.dropna().tolist() if normalize_text(value)]
    if not values:
        return False
    unique_values = sorted(set(values))
    if len(unique_values) > 11:
        return False
    label_lower = question_label.lower()
    if any(token in label_lower for token in ["agree or disagree", "how likely", "to what extent", "feel about"]):
        if len(unique_values) <= 7:
            return True
    pattern_hits = sum(any(pattern in value for pattern in LIKERT_PATTERNS) for value in unique_values)
    if pattern_hits >= 2:
        return True
    numeric_like = pd.to_numeric(pd.Series(unique_values), errors="coerce")
    if numeric_like.notna().all() and len(unique_values) <= 10:
        return True
    return False


def _is_numeric(series: pd.Series) -> bool:
    coerced = pd.to_numeric(series, errors="coerce")
    non_null_ratio = coerced.notna().mean()
    unique_values = coerced.dropna().nunique()
    return float(non_null_ratio) >= 0.8 and int(unique_values) >= 8


def _is_open_text(series: pd.Series) -> bool:
    values = series.dropna().astype(str).str.strip()
    if values.empty:
        return False
    unique_ratio = values.nunique() / max(len(values), 1)
    avg_length = values.map(len).mean()
    return float(unique_ratio) >= 0.5 and float(avg_length) >= 15


def guess_question_type(series: pd.Series, question_label: str = "") -> str:
    """Classify a survey variable using value-level heuristics only."""
    label_lower = question_label.lower()
    if "select all that apply" in label_lower or _is_multi_select(series):
        return "Multi-Select"
    if _is_scale(series, question_label):
        return "Scale / Likert"
    if _is_numeric(series):
        return "Numeric Data"
    if _is_open_text(series):
        return "Open-End Text"
    return "Single-Select"


def get_metadata_editor_columns() -> dict[str, Any]:
    """Build Streamlit column config lazily so the heuristics remain UI-independent."""
    import streamlit as st

    return {
        "variable": st.column_config.TextColumn("variable name", disabled=True),
        "question_label": st.column_config.TextColumn("question label", disabled=True),
        "detected_type": st.column_config.SelectboxColumn("detected type", options=QUESTION_TYPES, required=True),
        "include": st.column_config.CheckboxColumn("include/exclude toggle"),
        "notes": st.column_config.TextColumn("notes"),
    }


def detect_question_types(
    df: pd.DataFrame,
    question_labels: dict[str, str],
    cell_col: str | None = None,
) -> dict[str, str]:
    """Detect default question types for all relevant variables."""
    detected: dict[str, str] = {}
    for column in df.columns:
        if column == cell_col:
            detected[column] = "Ignore"
            continue
        detected[column] = guess_question_type(df[column], question_labels.get(column, ""))
    return detected


def build_question_metadata(
    df: pd.DataFrame,
    question_labels: dict[str, str],
    cell_col: str | None = None,
) -> list[dict[str, Any]]:
    """Build the default editable metadata package for the audit page."""
    detected = detect_question_types(df, question_labels, cell_col)
    metadata: list[dict[str, Any]] = []
    for column in df.columns:
        question_type = detected[column]
        metadata.append(
            {
                "variable": column,
                "question_label": question_labels.get(column, column),
                "detected_type": question_type,
                "include": DEFAULT_INCLUDE_VALUE if question_type != "Ignore" else False,
                "notes": "System split variable" if column == cell_col else "",
            }
        )
    return metadata


def prepare_metadata_editor_frame(metadata_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert metadata rows to a dataframe for `st.data_editor`."""
    return pd.DataFrame(metadata_rows)


def sanitize_metadata_editor(editor_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Normalize edited metadata rows into a safe JSON-serializable structure."""
    if editor_df.empty:
        return []
    sanitized: list[dict[str, Any]] = []
    for row in editor_df.to_dict(orient="records"):
        detected_type = normalize_text(row.get("detected_type")) or "Single-Select"
        if detected_type not in QUESTION_TYPES:
            detected_type = "Single-Select"
        sanitized.append(
            {
                "variable": normalize_text(row.get("variable")),
                "question_label": normalize_text(row.get("question_label")),
                "detected_type": detected_type,
                "include": bool(row.get("include", DEFAULT_INCLUDE_VALUE)),
                "notes": normalize_text(row.get("notes")),
            }
        )
    return sanitized


def restore_metadata_defaults(
    df: pd.DataFrame,
    question_labels: dict[str, str],
    cell_col: str | None = None,
) -> list[dict[str, Any]]:
    """Rebuild question metadata using the default heuristics."""
    return build_question_metadata(df, question_labels, cell_col)


def build_metadata_change_log_entry(variable: str, old_type: str | None, new_type: str) -> str:
    """Build a timestamped audit log entry."""
    timestamp = datetime.now().strftime("%H:%M")
    return f"[{timestamp}] {variable}: Type changed from {old_type or 'Unknown'} to {new_type}"


def summarize_included_questions(metadata_rows: list[dict[str, Any]]) -> str:
    """Return a simple included-question count summary."""
    total = len(metadata_rows)
    included = sum(1 for row in metadata_rows if row.get("include"))
    return f"{included}/{total}"
