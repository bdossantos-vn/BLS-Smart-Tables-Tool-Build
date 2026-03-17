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


def ensure_scale_mappings(
    scale_questions: list[dict[str, Any]],
    cleaned_df: pd.DataFrame,
    current_mappings: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Ensure every scale question has a mapping object."""
    mappings = dict(current_mappings)
    for question in scale_questions:
        variable = question["variable"]
        if variable not in mappings and variable in cleaned_df.columns:
            mappings[variable] = build_default_scale_mapping(cleaned_df[variable])
    return mappings


def build_scale_mapping_editor_frame(
    scale_questions: list[dict[str, Any]],
    scale_mappings: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    """Build a single wide editor frame with one row per scale question."""
    max_points = 0
    for question in scale_questions:
        variable = question["variable"]
        rows = scale_mappings.get(variable, {}).get("rows", [])
        max_points = max(max_points, len(rows))
    max_points = max(max_points, 5)

    editor_rows: list[dict[str, Any]] = []
    for question in scale_questions:
        variable = question["variable"]
        mapping = scale_mappings.get(variable, {"rows": [], "polarity": "standard"})
        ordered_rows = sorted(mapping.get("rows", []), key=lambda item: int(item.get("bucket", 0)))
        row: dict[str, Any] = {
            "variable": variable,
            "question_label": question.get("question_label", ""),
            "polarity": mapping.get("polarity", "standard"),
        }
        for index in range(max_points):
            key = f"scale_point_{index + 1}"
            row[key] = ordered_rows[index]["response_value"] if index < len(ordered_rows) else ""
        editor_rows.append(row)

    return pd.DataFrame(editor_rows)


def save_scale_mapping_editor(editor_df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Convert the wide editor frame back into the stored mapping structure."""
    mappings: dict[str, dict[str, Any]] = {}
    for row in editor_df.to_dict(orient="records"):
        variable = normalize_text(row.get("variable"))
        polarity = normalize_text(row.get("polarity")) or "standard"
        ordered_values: list[str] = []
        for key, value in row.items():
            if key.startswith("scale_point_"):
                text = normalize_text(value)
                if text:
                    ordered_values.append(text)

        deduped_values: list[str] = []
        for value in ordered_values:
            if value not in deduped_values:
                deduped_values.append(value)

        rows = []
        for index, value in enumerate(deduped_values, start=1):
            rows.append(
                {
                    "response_value": value,
                    "bucket": index,
                    "top_box_eligible": index in {1, len(deduped_values)},
                }
            )

        mappings[variable] = {
            "rows": rows,
            "polarity": polarity if polarity in {"standard", "flipped"} else "standard",
        }
    return mappings


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
