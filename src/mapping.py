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


def build_default_scale_mapping(series: pd.Series, preferred_order: list[str] | None = None) -> dict[str, Any]:
    """Build the default response-to-bucket mapping for a scale question."""
    ordered_values: list[str] = []

    preferred_order = preferred_order or []
    for value in preferred_order:
        if value and value not in ordered_values:
            ordered_values.append(value)

    unique_values = [normalize_text(value) for value in series.dropna().tolist()]
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


def _reconcile_scale_mapping(
    mapping: dict[str, Any],
    canonical_values: list[str],
) -> dict[str, Any]:
    """Align one saved scale mapping to the canonical question choice order.

    This keeps persisted mappings resilient when older app versions seeded a
    bad order. If the saved rows contain the same set of answer choices as the
    canonical question metadata, we normalize them back to canonical order
    while respecting polarity.
    """
    normalized_canonical = [normalize_text(value) for value in canonical_values if normalize_text(value)]
    if not normalized_canonical:
        return mapping

    saved_rows = sorted(mapping.get("rows", []), key=lambda item: int(item.get("bucket", 0)))
    saved_values = [normalize_text(row.get("response_value")) for row in saved_rows if normalize_text(row.get("response_value"))]
    if not saved_values:
        return mapping

    if set(saved_values) != set(normalized_canonical):
        return mapping

    polarity = normalize_text(mapping.get("polarity", "standard")) or "standard"
    ordered_values = list(normalized_canonical)
    if polarity == "flipped":
        ordered_values = list(reversed(ordered_values))

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
        "polarity": polarity if polarity in {"standard", "flipped"} else "standard",
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
        if variable not in cleaned_df.columns:
            continue
        canonical_mapping = build_default_scale_mapping(
            cleaned_df[variable],
            preferred_order=question.get("answer_choices_list", []),
        )
        if variable not in mappings:
            mappings[variable] = canonical_mapping
        else:
            mappings[variable] = _reconcile_scale_mapping(
                mappings[variable],
                [row.get("response_value", "") for row in canonical_mapping.get("rows", [])],
            )
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


def build_scale_mapping_options(scale_mappings: dict[str, dict[str, Any]]) -> list[str]:
    """Build a global option list for scale-point dropdowns."""
    options: list[str] = [""]
    for mapping in scale_mappings.values():
        for row in mapping.get("rows", []):
            value = normalize_text(row.get("response_value"))
            if value and value not in options:
                options.append(value)
    return options


def validate_scale_mapping_editor(editor_df: pd.DataFrame) -> list[str]:
    """Validate that each row uses unique scale-point values."""
    issues: list[str] = []
    for row in editor_df.to_dict(orient="records"):
        variable = normalize_text(row.get("variable"))
        selected_values: list[str] = []
        for key, value in row.items():
            if key.startswith("scale_point_"):
                text = normalize_text(value)
                if text:
                    selected_values.append(text)
        if len(selected_values) != len(set(selected_values)):
            issues.append(f"{variable}: Each scale point must use a unique response option.")
    return issues


def save_scale_mapping_editor(
    editor_df: pd.DataFrame,
    previous_mappings: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Convert the wide editor frame back into the stored mapping structure."""
    mappings: dict[str, dict[str, Any]] = {}
    previous_mappings = previous_mappings or {}
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

        previous_polarity = normalize_text(previous_mappings.get(variable, {}).get("polarity", "standard")) or "standard"
        if previous_polarity != polarity and len(deduped_values) > 1:
            deduped_values = list(reversed(deduped_values))

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


def build_scale_change_log(
    previous_mappings: dict[str, dict[str, Any]],
    current_mappings: dict[str, dict[str, Any]],
) -> list[str]:
    """Build specific before/after change-log entries for scale mapping edits."""
    change_log: list[str] = []
    for variable, current_mapping in current_mappings.items():
        previous_mapping = previous_mappings.get(variable, {})
        previous_polarity = normalize_text(previous_mapping.get("polarity", "standard")) or "standard"
        current_polarity = normalize_text(current_mapping.get("polarity", "standard")) or "standard"

        previous_values = [
            normalize_text(row.get("response_value"))
            for row in sorted(previous_mapping.get("rows", []), key=lambda item: int(item.get("bucket", 0)))
            if normalize_text(row.get("response_value"))
        ]
        current_values = [
            normalize_text(row.get("response_value"))
            for row in sorted(current_mapping.get("rows", []), key=lambda item: int(item.get("bucket", 0)))
            if normalize_text(row.get("response_value"))
        ]

        if previous_polarity != current_polarity:
            change_log.append(
                f"{variable}: Polarity changed from {previous_polarity} to {current_polarity}"
            )
        if previous_values != current_values:
            previous_text = " | ".join(previous_values) or "(blank)"
            current_text = " | ".join(current_values) or "(blank)"
            if len(previous_text) + len(current_text) <= 180:
                change_log.append(
                    f'{variable}: Scale points changed "{previous_text}" -> "{current_text}"'
                )
            else:
                change_log.append(
                    f"{variable}: Scale points changed {len(previous_values)} option(s) -> {len(current_values)} option(s)"
                )
    return change_log


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
