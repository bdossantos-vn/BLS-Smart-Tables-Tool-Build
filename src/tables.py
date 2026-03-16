"""Table generation scaffolding for V1."""

from __future__ import annotations

from typing import Any

import pandas as pd


def describe_generation_readiness(default_state: dict, current_state: dict) -> list[str]:
    """Explain whether the project is ready for placeholder table generation."""
    messages: list[str] = []
    if current_state.get("cleaned_df") is None:
        messages.append("No cleaned dataset is available yet.")
    else:
        messages.append("A cleaned dataset is available.")
    if not current_state.get("question_metadata"):
        messages.append("Question metadata has not been configured yet.")
    else:
        messages.append("Question metadata is available.")
    if not current_state.get("locked_cell_bases"):
        messages.append("Locked cell bases have not been finalized yet.")
    else:
        messages.append("Locked cell bases are stored.")
    return messages


def generate_placeholder_tables(
    cleaned_df: pd.DataFrame | None,
    question_metadata: list[dict[str, Any]],
) -> dict[str, pd.DataFrame]:
    """Generate a minimal placeholder workbook payload for export testing."""
    summary_rows = [
        {"metric": "rows", "value": 0 if cleaned_df is None else len(cleaned_df)},
        {"metric": "questions", "value": len(question_metadata)},
        {"metric": "status", "value": "placeholder"},
    ]
    metadata_rows = pd.DataFrame(question_metadata)
    return {
        "Summary": pd.DataFrame(summary_rows),
        "Question Metadata": metadata_rows,
    }


def build_placeholder_table_preview(generated_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a compact preview frame for the first generated worksheet."""
    if not generated_tables:
        return pd.DataFrame()
    first_key = next(iter(generated_tables))
    return generated_tables[first_key]
