"""General utility helpers used across the application."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

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
