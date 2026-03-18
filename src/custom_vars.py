"""Custom variable builder helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.utils import normalize_text


BUILDER_TYPES = [
    "Bucketed Variable",
    "Boolean Flag",
    "Simple Copy",
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


def validate_bucketed_variable_definition(
    name: str,
    existing: list[dict[str, Any]],
    source_variables: list[str],
    buckets: list[dict[str, Any]],
) -> list[str]:
    """Validate a bucketed custom-variable definition."""
    issues: list[str] = []
    valid_name, message = validate_custom_variable_name(name, existing)
    if not valid_name:
        issues.append(message)
    if not source_variables:
        issues.append("Select at least one source question.")
    if not buckets:
        issues.append("Create at least one bucket.")

    bucket_labels: list[str] = []
    any_selected = False
    for index, bucket in enumerate(buckets, start=1):
        label = normalize_text(bucket.get("label"))
        if not label:
            issues.append(f"Bucket {index} needs a label.")
        else:
            bucket_labels.append(label)
        selections = bucket.get("selections", {})
        bucket_has_selection = any(bool(values) for values in selections.values())
        any_selected = any_selected or bucket_has_selection
        if not bucket_has_selection:
            issues.append(f"{label or f'Bucket {index}'} needs at least one selected answer choice.")

    if len(bucket_labels) != len(set(bucket_labels)):
        issues.append("Bucket labels must be unique.")
    if not any_selected:
        issues.append("At least one answer choice must be selected across the custom variable.")
    return issues


def validate_simple_copy_definition(
    name: str,
    existing: list[dict[str, Any]],
    source_variable: str,
) -> list[str]:
    """Validate a simple-copy custom variable definition."""
    issues: list[str] = []
    valid_name, message = validate_custom_variable_name(name, existing)
    if not valid_name:
        issues.append(message)
    if not normalize_text(source_variable):
        issues.append("Select a source question.")
    return issues


def validate_boolean_flag_definition(
    name: str,
    existing: list[dict[str, Any]],
    source_variables: list[str],
    true_label: str,
    false_label: str,
    selections: dict[str, list[str]],
) -> list[str]:
    """Validate a boolean custom-variable definition."""
    issues: list[str] = []
    valid_name, message = validate_custom_variable_name(name, existing)
    if not valid_name:
        issues.append(message)
    if not source_variables:
        issues.append("Select at least one source question.")
    if not normalize_text(true_label):
        issues.append("True label is required.")
    if not normalize_text(false_label):
        issues.append("False label is required.")
    if normalize_text(true_label) and normalize_text(true_label) == normalize_text(false_label):
        issues.append("True and false labels must be different.")
    if not any(bool(values) for values in selections.values()):
        issues.append("Select at least one answer choice that should evaluate to true.")
    return issues


def build_bucketed_variable_record(
    name: str,
    source_variables: list[str],
    buckets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a stored record for a bucketed custom variable."""
    return {
        "name": normalize_text(name),
        "builder_type": "Bucketed Variable",
        "source_variables": source_variables,
        "bucket_count": len(buckets),
        # Practical assumption: selections are OR'ed across source questions
        # within a bucket, and buckets are evaluated in the saved order later.
        "buckets": buckets,
        "status": "configured",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_simple_copy_record(name: str, source_variable: str) -> dict[str, Any]:
    """Build a stored record for a simple-copy custom variable."""
    return {
        "name": normalize_text(name),
        "builder_type": "Simple Copy",
        "source_variables": [normalize_text(source_variable)],
        "bucket_count": 0,
        "buckets": [],
        "status": "configured",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def build_boolean_flag_record(
    name: str,
    source_variables: list[str],
    true_label: str,
    false_label: str,
    selections: dict[str, list[str]],
) -> dict[str, Any]:
    """Build a stored record for a boolean flag custom variable."""
    return {
        "name": normalize_text(name),
        "builder_type": "Boolean Flag",
        "source_variables": source_variables,
        "bucket_count": 2,
        "true_label": normalize_text(true_label),
        "false_label": normalize_text(false_label),
        # Practical assumption: any selected answer choice across source variables
        # evaluates this variable to the true label; everything else maps to false.
        "selections": selections,
        "buckets": [],
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
