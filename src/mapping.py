"""Scale mapping and polarity helpers."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.utils import normalize_text


def identify_scale_questions(question_metadata: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return metadata rows that are currently marked as scale questions."""
    return [
        row
        for row in question_metadata
        if row.get("detected_type") == "Scale / Likert" and row.get("include", True)
    ]


def build_default_scale_mapping(series: pd.Series) -> dict[str, Any]:
    """Build the default response-to-bucket mapping for a scale question."""
    unique_values = [normalize_text(value) for value in series.dropna().tolist()]
    ordered_values: list[str] = []
    for value in unique_values:
        if value and value not in ordered_values:
            ordered_values.append(value)

    rows = []
    for index, value in enumerate(ordered_values, start=1):
        rows.append(
            {
                "response_value": value,
                "bucket": index,
                "top_box_eligible": index in {1, len(ordered_values)},
            }
        )

    return {
        "rows": rows,
        "polarity": "standard",
    }


def update_scale_mapping_from_editor(current_mapping: dict[str, Any], editor_df: pd.DataFrame) -> dict[str, Any]:
    """Persist edited bucket assignments back into the mapping structure."""
    updated_rows = []
    for row in editor_df.to_dict(orient="records"):
        updated_rows.append(
            {
                "response_value": normalize_text(row.get("response_value")),
                "bucket": int(row.get("bucket", 1)),
                "top_box_eligible": bool(row.get("top_box_eligible", False)),
            }
        )
    return {
        "rows": updated_rows,
        "polarity": current_mapping.get("polarity", "standard"),
    }


def flip_scale_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    """Reverse bucket order while preserving response value membership."""
    rows = mapping.get("rows", [])
    if not rows:
        return {"rows": [], "polarity": "standard"}

    max_bucket = max(int(row["bucket"]) for row in rows)
    flipped_rows = []
    for row in rows:
        flipped_rows.append(
            {
                "response_value": row["response_value"],
                "bucket": max_bucket - int(row["bucket"]) + 1,
                "top_box_eligible": row.get("top_box_eligible", False),
            }
        )

    new_polarity = "flipped" if mapping.get("polarity") == "standard" else "standard"
    flipped_rows = sorted(flipped_rows, key=lambda item: int(item["bucket"]))
    return {
        "rows": flipped_rows,
        "polarity": new_polarity,
    }

