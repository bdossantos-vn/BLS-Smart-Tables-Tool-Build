"""General utility helpers used across the application."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable
import re

import pandas as pd


def normalize_text(value: object) -> str:
    """Convert a value to a normalized, trimmed string."""
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value).strip()


def coerce_int(value: object, default: int = 0) -> int:
    """Best-effort integer coercion with a safe fallback."""
    try:
        if value is None or pd.isna(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def alpha_letter_sequence(count: int) -> list[str]:
    """Generate a sequence of significance letters: A, B, ..., Z, AA, AB, ..."""
    letters: list[str] = []
    number = 0
    while len(letters) < count:
        number += 1
        current = number
        label = ""
        while current > 0:
            current, remainder = divmod(current - 1, 26)
            label = chr(65 + remainder) + label
        letters.append(label)
    return letters


def unique_preserving_order(values: Iterable[str]) -> list[str]:
    """Deduplicate values while preserving input order."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def _natural_sort_parts(value: object) -> tuple[tuple[int, object], ...]:
    """Split text into case-insensitive string and integer sort parts."""
    normalized = normalize_text(value)
    parts = re.split(r"(\d+)", normalized)
    sort_parts: list[tuple[int, object]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            sort_parts.append((0, int(part)))
        else:
            sort_parts.append((1, part.lower()))
    return tuple(sort_parts)


def questionnaire_variable_sort_key(value: object) -> tuple[int, tuple[tuple[int, object], ...], str]:
    """Sort Qualtrics question ids naturally, with embedded/non-QID fields last."""
    normalized = normalize_text(value)
    is_questionnaire_id = re.match(r"(?i)^q(?:id)?\d+", normalized) is not None
    return (
        0 if is_questionnaire_id else 1,
        _natural_sort_parts(normalized),
        normalized.lower(),
    )


def split_text_outside_grouping(value: object, delimiter: str) -> list[str]:
    """Split text on a delimiter, ignoring delimiters inside parenthetical groups."""
    normalized_value = normalize_text(value)
    if not normalized_value:
        return []

    parts: list[str] = []
    current: list[str] = []
    grouping_depth = 0
    for char in normalized_value:
        if char in "([{":
            grouping_depth += 1
        elif char in ")]}" and grouping_depth > 0:
            grouping_depth -= 1

        if char == delimiter and grouping_depth == 0:
            part = normalize_text("".join(current))
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)

    final_part = normalize_text("".join(current))
    if final_part:
        parts.append(final_part)
    return parts


def split_multi_select_value(value: object, allow_comma: bool = True) -> list[str]:
    """Split one stored multi-select value without breaking comma-bearing labels."""
    normalized_value = normalize_text(value)
    if not normalized_value:
        return []

    semicolon_parts = split_text_outside_grouping(normalized_value, ";")
    if len(semicolon_parts) > 1:
        return semicolon_parts

    if allow_comma:
        comma_parts = split_text_outside_grouping(normalized_value, ",")
        if len(comma_parts) > 1:
            return comma_parts

    return [normalized_value]


def _contains_delimited_segment(value: str, segment: str) -> bool:
    """Return whether a segment appears with comma/semicolon boundaries."""
    start = 0
    while True:
        index = value.find(segment, start)
        if index == -1:
            return False

        before = value[:index].rstrip()
        after = value[index + len(segment):].lstrip()
        before_ok = not before or before[-1] in {",", ";"}
        after_ok = not after or after[0] in {",", ";"}
        if before_ok and after_ok:
            return True
        start = index + 1


def multi_select_value_contains_choice(value: object, choice: object) -> bool:
    """Return whether a stored multi-select value contains one selected choice."""
    normalized_value = normalize_text(value)
    normalized_choice = normalize_text(choice)
    if not normalized_value or not normalized_choice:
        return False
    if normalized_value == normalized_choice:
        return True
    if normalized_choice in split_multi_select_value(normalized_value):
        return True
    if "," not in normalized_choice and ";" not in normalized_choice:
        return False
    return _contains_delimited_segment(normalized_value, normalized_choice)


def format_timestamp() -> str:
    """Return a human-friendly timestamp for UI logs."""
    return datetime.now().strftime("%H:%M:%S")


def display_log_lines(lines: list[str]) -> None:
    """Render a lightweight log display in Streamlit."""
    import streamlit as st

    if not lines:
        st.caption("No log entries yet.")
        return
    for line in lines[-25:]:
        st.code(line)


def dataframe_to_download_name(uploaded_filename: str | None, fallback_name: str) -> str:
    """Create a deterministic export filename derived from the uploaded file name."""
    if not uploaded_filename:
        return fallback_name
    stem = uploaded_filename.rsplit(".", 1)[0].strip() or "bls_output"
    return f"{stem}_tables.xlsx"
