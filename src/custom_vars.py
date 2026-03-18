"""Custom variable builder helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.utils import normalize_text


MATCH_LOGIC_OPTIONS = ["ALL", "ANY"]


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
    match_logic: str,
    buckets: list[dict[str, Any]],
    current_name: str | None = None,
) -> list[str]:
    """Validate a custom-variable definition."""
    issues: list[str] = []
    valid_name, message = validate_custom_variable_name(name, existing, current_name=current_name)
    if not valid_name:
        issues.append(message)
    if not source_variables:
        issues.append("Select at least one source question.")
    if match_logic not in MATCH_LOGIC_OPTIONS:
        issues.append("Match logic must be `ALL` or `ANY`.")
    if not buckets:
        issues.append("Create at least one bucket.")

    bucket_labels: list[str] = []
    catch_all_count = 0
    for index, bucket in enumerate(buckets, start=1):
        label = normalize_text(bucket.get("label"))
        if not label:
            issues.append(f"Bucket {index} needs a label.")
        else:
            bucket_labels.append(label)

        catch_all = bool(bucket.get("catch_all", False))
        selections = bucket.get("selections", {})
        if catch_all:
            catch_all_count += 1
        elif not any(bool(values) for values in selections.values()):
            issues.append(f"{label or f'Bucket {index}'} needs at least one selected answer choice.")

    if len(bucket_labels) != len(set(bucket_labels)):
        issues.append("Bucket labels must be unique.")
    if catch_all_count > 1:
        issues.append("Only one bucket can be marked as `All others`.")
    return issues


def build_bucketed_variable_record(
    name: str,
    source_variables: list[str],
    match_logic: str,
    buckets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a stored record for a bucketed custom variable."""
    return {
        "name": normalize_text(name),
        "builder_type": "Bucketed Variable",
        "source_variables": source_variables,
        "match_logic": match_logic,
        "bucket_count": len(buckets),
        # Practical assumption: source-question conditions are evaluated using the
        # saved match logic per bucket, and buckets are evaluated top-to-bottom.
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
            "match_logic": item.get("match_logic", ""),
            "source_questions": len(item.get("source_variables", [])),
            "bucket_count": item.get("bucket_count", 0),
            "status": item.get("status", ""),
            "created_at": item.get("created_at", ""),
        }
        for item in existing
    ]
