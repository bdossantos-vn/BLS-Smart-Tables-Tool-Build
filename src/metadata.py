"""Question metadata detection and editing helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import re

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

SCALE_LABEL_HINTS = [
    "agree or disagree",
    "how likely",
    "to what extent",
    "feel about",
    "how interested",
    "brand affinity",
    "affinity",
    "relationship with",
]

SCALE_VALUE_HINTS = [
    "very interested",
    "somewhat interested",
    "not very interested",
    "not at all interested",
    "love it",
    "like it",
    "neutral",
    "dislike it",
    "hate it",
    "very likely",
    "somewhat likely",
    "not likely",
    "very unlikely",
    "somewhat better",
    "about the same",
    "much worse",
    "much better",
    "somewhat worse",
    "very interested",
    "somewhat interested",
    "not very interested",
    "not at all interested",
]

AGE_PATTERNS = [
    ("under 18", 0),
    ("18 - 24", 1),
    ("18-24", 1),
    ("25 - 34", 2),
    ("25-34", 2),
    ("35 - 44", 3),
    ("35-44", 3),
    ("45+", 4),
    ("45 +", 4),
    ("55+", 5),
    ("55 +", 5),
    ("65+", 6),
    ("65 +", 6),
]

SCALE_ORDER_PATTERNS = [
    ("love it", 0),
    ("very likely", 0),
    ("very interested", 0),
    ("strongly agree", 0),
    ("much better", 0),
    ("somewhat likely", 1),
    ("somewhat interested", 1),
    ("somewhat agree", 1),
    ("somewhat better", 1),
    ("like it", 1),
    ("about the same", 2),
    ("neutral", 2),
    ("neither agree nor disagree", 2),
    ("somewhat worse", 3),
    ("not likely", 3),
    ("not very interested", 3),
    ("somewhat disagree", 3),
    ("dislike it", 3),
    ("much worse", 3),
    ("very unlikely", 4),
    ("not at all interested", 4),
    ("strongly disagree", 4),
    ("hate it", 4),
]

HP_INTEREST_ORDER_PATTERNS = [
    ("i am a dedicated harry potter fan", 0),
    ("i enjoyed it in the past and feel nostalgic toward it", 1),
    ("i'm new to the series but interested", 2),
    ("i’m new to the series but interested", 2),
    ("i'm not a fan", 3),
    ("i’m not a fan", 3),
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
    if any(token in label_lower for token in SCALE_LABEL_HINTS):
        if len(unique_values) <= 7:
            return True
    pattern_hits = sum(any(pattern in value for pattern in LIKERT_PATTERNS) for value in unique_values)
    if pattern_hits >= 2:
        return True
    value_hint_hits = sum(any(pattern in value for pattern in SCALE_VALUE_HINTS) for value in unique_values)
    if value_hint_hits >= 2 and len(unique_values) <= 7:
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
        "variable": st.column_config.TextColumn("Variable Name", disabled=True, width="medium"),
        "question_label": st.column_config.TextColumn("Question Text", disabled=True, width="large"),
        "detected_type": st.column_config.SelectboxColumn(
            "Question Type",
            options=QUESTION_TYPES,
            required=True,
            width="medium",
        ),
        "answer_choice_count": st.column_config.NumberColumn(
            "Answer Choices Count",
            disabled=True,
            width="medium",
        ),
        "answer_choices": st.column_config.TextColumn(
            "Answer Choices",
            width="large",
            help="Edit answer choices using a new line or `|` between labels for clear separation.",
        ),
    }


def _sort_age_choices(choices: list[str]) -> list[str]:
    """Sort common age bucket labels into ascending age order."""
    scored: list[tuple[int, str]] = []
    unmatched: list[str] = []
    for choice in choices:
        normalized = choice.lower()
        matched_score = None
        for pattern, score in AGE_PATTERNS:
            if pattern in normalized:
                matched_score = score
                break
        if matched_score is None:
            unmatched.append(choice)
        else:
            scored.append((matched_score, choice))
    if not scored:
        return choices
    ordered = [choice for _, choice in sorted(scored, key=lambda item: item[0])]
    ordered.extend(unmatched)
    return ordered


def _sort_scale_choices(choices: list[str]) -> list[str]:
    """Sort common scale labels from most positive to most negative."""
    scored: list[tuple[int, int, str]] = []
    unmatched: list[tuple[int, str]] = []
    for index, choice in enumerate(choices):
        normalized = choice.lower()
        matched_score = None
        for pattern, score in SCALE_ORDER_PATTERNS:
            if pattern in normalized:
                matched_score = score
                break
        if matched_score is None:
            unmatched.append((index, choice))
        else:
            scored.append((matched_score, index, choice))
    if not scored:
        return choices
    ordered = [choice for _, _, choice in sorted(scored, key=lambda item: (item[0], item[1]))]
    ordered.extend(choice for _, choice in unmatched)
    return ordered


def _sort_pattern_list(choices: list[str], ordered_patterns: list[tuple[str, int]]) -> list[str]:
    """Sort choices by a custom ordered pattern list, preserving unmatched items afterward."""
    scored: list[tuple[int, int, str]] = []
    unmatched: list[tuple[int, str]] = []
    for index, choice in enumerate(choices):
        normalized = choice.lower()
        matched_score = None
        for pattern, score in ordered_patterns:
            if pattern in normalized:
                matched_score = score
                break
        if matched_score is None:
            unmatched.append((index, choice))
        else:
            scored.append((matched_score, index, choice))
    if not scored:
        return choices
    ordered = [choice for _, _, choice in sorted(scored, key=lambda item: (item[0], item[1]))]
    ordered.extend(choice for _, choice in unmatched)
    return ordered


def sort_answer_choices(answer_choices: list[str], question_type: str, question_label: str = "") -> list[str]:
    """Apply practical default ordering for common answer-choice patterns."""
    if not answer_choices:
        return []

    label_lower = question_label.lower()
    if "how old" in label_lower or label_lower.strip() == "age":
        return _sort_age_choices(answer_choices)
    if "relationship with the harry potter series" in label_lower:
        return _sort_pattern_list(answer_choices, HP_INTEREST_ORDER_PATTERNS)
    if question_type == "Scale / Likert":
        return _sort_scale_choices(answer_choices)
    return answer_choices


def extract_answer_choices(series: pd.Series, question_type: str, question_label: str = "") -> list[str]:
    """Extract unique answer choices in display order for supported question types."""
    values = [normalize_text(value) for value in series.dropna().tolist()]
    if not values:
        return []

    if question_type == "Multi-Select":
        choices: list[str] = []
        for value in values:
            parts = [part.strip() for part in re.split(r"[;,]", value) if part.strip()]
            for part in parts:
                if part not in choices:
                    choices.append(part)
        return sort_answer_choices(choices, question_type, question_label)

    if question_type in {"Open-End Text", "Numeric Data", "Ignore"}:
        return []

    choices = []
    for value in values:
        if value and value not in choices:
            choices.append(value)
    return sort_answer_choices(choices, question_type, question_label)


def serialize_answer_choices(answer_choices: list[str]) -> str:
    """Serialize answer choices into an editable display string."""
    return " | ".join(answer_choices)


def parse_answer_choices(answer_choices_text: str) -> list[str]:
    """Parse edited answer-choice text back into a normalized list."""
    parts = [part.strip() for part in re.split(r"\||\n", answer_choices_text) if part.strip()]
    return parts


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
        answer_choices = extract_answer_choices(df[column], question_type, question_labels.get(column, column))
        metadata.append(
            {
                "variable": column,
                "question_label": question_labels.get(column, column),
                "detected_type": question_type,
                "answer_choices": serialize_answer_choices(answer_choices),
                "answer_choices_list": answer_choices,
                "include": DEFAULT_INCLUDE_VALUE if question_type != "Ignore" else False,
                "notes": "System split variable" if column == cell_col else "",
            }
        )
    return metadata


def prepare_metadata_editor_frame(metadata_rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert metadata rows to a dataframe for `st.data_editor`."""
    editor_rows = []
    for row in metadata_rows:
        editor_rows.append(
            {
                "variable": row.get("variable", ""),
                "question_label": row.get("question_label", ""),
                "detected_type": row.get("detected_type", "Single-Select"),
                "answer_choice_count": len(row.get("answer_choices_list", [])),
                "answer_choices": row.get("answer_choices", ""),
            }
        )
    return pd.DataFrame(editor_rows)


def sanitize_metadata_editor(editor_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Normalize edited metadata rows into a safe JSON-serializable structure."""
    if editor_df.empty:
        return []
    sanitized: list[dict[str, Any]] = []
    for row in editor_df.to_dict(orient="records"):
        detected_type = normalize_text(row.get("detected_type")) or "Single-Select"
        if detected_type not in QUESTION_TYPES:
            detected_type = "Single-Select"
        answer_choices_text = normalize_text(row.get("answer_choices"))
        sanitized.append(
            {
                "variable": normalize_text(row.get("variable")),
                "question_label": normalize_text(row.get("question_label")),
                "detected_type": detected_type,
                "answer_choice_count": len(parse_answer_choices(answer_choices_text)),
                "answer_choices": answer_choices_text,
                "answer_choices_list": parse_answer_choices(answer_choices_text),
                "include": detected_type != "Ignore",
                "notes": "",
            }
        )
    return sanitized


def merge_metadata_editor_with_source(
    editor_df: pd.DataFrame,
    previous_metadata: list[dict[str, Any]],
    source_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Merge edited metadata with source data, recalculating answer choices when type changes."""
    sanitized = sanitize_metadata_editor(editor_df)
    previous_lookup = {row.get("variable"): row for row in previous_metadata}
    merged: list[dict[str, Any]] = []

    for row in sanitized:
        variable = row["variable"]
        previous_row = previous_lookup.get(variable, {})
        old_type = previous_row.get("detected_type")
        new_type = row["detected_type"]
        previous_answer_text = normalize_text(previous_row.get("answer_choices", ""))
        edited_answer_text = normalize_text(row.get("answer_choices", ""))

        if (
            variable in source_df.columns
            and old_type != new_type
            and edited_answer_text == previous_answer_text
        ):
            recalculated_choices = extract_answer_choices(
                source_df[variable],
                new_type,
                row.get("question_label", variable),
            )
            row["answer_choice_count"] = len(recalculated_choices)
            row["answer_choices"] = serialize_answer_choices(recalculated_choices)
            row["answer_choices_list"] = recalculated_choices

        merged.append(row)

    return merged


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
