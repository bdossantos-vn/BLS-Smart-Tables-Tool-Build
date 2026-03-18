"""Custom variable builder helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
import re

import pandas as pd

from src.utils import normalize_text


BUILD_TYPES = [
    "Simple Variable",
    "Complex Variable",
]

MATCH_LOGIC_OPTIONS = ["ALL", "ANY"]
CONDITION_OPERATORS = [
    "Includes any",
    "Includes all",
    "Is exactly",
]


def build_question_catalog(question_metadata: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a source-question catalog for the custom variable builder."""
    catalog: list[dict[str, Any]] = []
    for row in question_metadata:
        question_type = row.get("detected_type", "")
        if question_type in {"Ignore", "Open-End Text"}:
            continue
        catalog.append(
            {
                "variable": normalize_text(row.get("variable")),
                "question_label": normalize_text(row.get("question_label")),
                "question_type": normalize_text(question_type),
                "answer_choices_list": list(row.get("answer_choices_list", [])),
            }
        )
    return catalog


def build_question_lookup(question_metadata: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build a fast variable-to-question lookup."""
    return {
        item["variable"]: item
        for item in build_question_catalog(question_metadata)
    }


def validate_custom_variable_name(
    name: str,
    existing: list[dict[str, Any]],
    current_name: str | None = None,
) -> tuple[bool, str]:
    """Validate a custom variable name."""
    cleaned = normalize_text(name)
    if not cleaned:
        return False, "Custom variable name is required."
    existing_names = {
        normalize_text(item.get("name"))
        for item in existing
        if normalize_text(item.get("name")) != normalize_text(current_name)
    }
    if cleaned in existing_names:
        return False, "Custom variable name must be unique."
    return True, ""


def validate_simple_variable_definition(
    name: str,
    existing: list[dict[str, Any]],
    source_variable: str,
    buckets: list[dict[str, Any]],
    current_name: str | None = None,
) -> list[str]:
    """Validate a simple-variable definition."""
    issues: list[str] = []
    valid_name, message = validate_custom_variable_name(name, existing, current_name=current_name)
    if not valid_name:
        issues.append(message)
    if not normalize_text(source_variable):
        issues.append("Select a source question.")
    if not buckets:
        issues.append("Create at least one bucket.")

    labels: list[str] = []
    catch_all_count = 0
    for index, bucket in enumerate(buckets, start=1):
        label = normalize_text(bucket.get("label"))
        if not label:
            issues.append(f"Bucket {index} needs a label.")
        else:
            labels.append(label)
        if bucket.get("catch_all"):
            catch_all_count += 1
        elif not bucket.get("choices"):
            issues.append(f"{label or f'Bucket {index}'} needs at least one selected choice.")

    if len(labels) != len(set(labels)):
        issues.append("Bucket labels must be unique.")
    if catch_all_count > 1:
        issues.append("Only one bucket can be marked as `All others`.")
    return issues


def validate_complex_variable_definition(
    name: str,
    existing: list[dict[str, Any]],
    buckets: list[dict[str, Any]],
    current_name: str | None = None,
) -> list[str]:
    """Validate a complex-variable definition."""
    issues: list[str] = []
    valid_name, message = validate_custom_variable_name(name, existing, current_name=current_name)
    if not valid_name:
        issues.append(message)
    if not buckets:
        issues.append("Create at least one output bucket.")

    labels: list[str] = []
    catch_all_count = 0
    for index, bucket in enumerate(buckets, start=1):
        label = normalize_text(bucket.get("label"))
        if not label:
            issues.append(f"Bucket {index} needs a label.")
        else:
            labels.append(label)

        if bucket.get("catch_all"):
            catch_all_count += 1
            continue

        if normalize_text(bucket.get("match_logic")) not in MATCH_LOGIC_OPTIONS:
            issues.append(f"{label or f'Bucket {index}'} needs `ALL` or `ANY` logic.")

        conditions = bucket.get("conditions", [])
        if not conditions:
            issues.append(f"{label or f'Bucket {index}'} needs at least one condition.")
            continue

        for condition_index, condition in enumerate(conditions, start=1):
            variable = normalize_text(condition.get("variable"))
            operator = normalize_text(condition.get("operator"))
            choices = condition.get("choices", [])
            if not variable:
                issues.append(
                    f"{label or f'Bucket {index}'} condition {condition_index} needs a source question."
                )
            if operator not in CONDITION_OPERATORS:
                issues.append(
                    f"{label or f'Bucket {index}'} condition {condition_index} needs a valid operator."
                )
            if not choices:
                issues.append(
                    f"{label or f'Bucket {index}'} condition {condition_index} needs selected choices."
                )

    if len(labels) != len(set(labels)):
        issues.append("Bucket labels must be unique.")
    if catch_all_count > 1:
        issues.append("Only one bucket can be marked as `All others`.")
    return issues


def build_simple_variable_record(
    name: str,
    source_variable: str,
    buckets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a stored record for a simple custom variable."""
    return {
        "name": normalize_text(name),
        "builder_type": "Simple Variable",
        "source_variables": [normalize_text(source_variable)],
        "bucket_count": len(buckets),
        "buckets": buckets,
        "status": "configured",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_complex_variable_record(
    name: str,
    buckets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a stored record for a complex custom variable."""
    source_variables: list[str] = []
    for bucket in buckets:
        for condition in bucket.get("conditions", []):
            variable = normalize_text(condition.get("variable"))
            if variable and variable not in source_variables:
                source_variables.append(variable)
    return {
        "name": normalize_text(name),
        "builder_type": "Complex Variable",
        "source_variables": source_variables,
        "bucket_count": len(buckets),
        "buckets": buckets,
        "status": "configured",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def upsert_custom_variable(
    existing: list[dict[str, Any]],
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    """Insert or replace a custom variable by name."""
    updated = [
        item
        for item in existing
        if normalize_text(item.get("name")) != normalize_text(record.get("name"))
    ]
    updated.append(record)
    return updated


def list_custom_variable_summaries(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a compact summary table for the UI."""
    return [
        {
            "name": item.get("name", ""),
            "builder_type": item.get("builder_type", ""),
            "source_questions": len(item.get("source_variables", [])),
            "bucket_count": item.get("bucket_count", 0),
            "status": item.get("status", ""),
            "created_at": item.get("created_at", ""),
        }
        for item in existing
    ]


def _value_matches_selected_choices(value: object, selected_choices: list[str]) -> bool:
    """Return whether a respondent value matches any selected choice."""
    normalized_value = normalize_text(value)
    if not normalized_value:
        return False
    normalized_choices = {normalize_text(choice) for choice in selected_choices if normalize_text(choice)}
    if not normalized_choices:
        return False
    if normalized_value in normalized_choices:
        return True

    parts = {
        normalize_text(part)
        for part in re.split(r"[;,]", normalized_value)
        if normalize_text(part)
    }
    return bool(parts & normalized_choices)


def compute_simple_variable_counts(
    df: pd.DataFrame,
    source_variable: str,
    buckets: list[dict[str, Any]],
) -> tuple[list[int], int]:
    """Compute top-down bucket counts and unmatched count for a simple variable."""
    if source_variable not in df.columns:
        return [0 for _ in buckets], 0

    remaining_mask = pd.Series(True, index=df.index)
    bucket_counts: list[int] = []

    for bucket in buckets:
        if bucket.get("catch_all"):
            count = int(remaining_mask.sum())
            bucket_counts.append(count)
            remaining_mask = pd.Series(False, index=df.index)
            continue

        selected_choices = bucket.get("choices", [])
        matched_mask = df[source_variable].map(
            lambda value: _value_matches_selected_choices(value, selected_choices)
        )
        bucket_mask = remaining_mask & matched_mask.fillna(False)
        bucket_counts.append(int(bucket_mask.sum()))
        remaining_mask = remaining_mask & ~bucket_mask

    return bucket_counts, int(remaining_mask.sum())
