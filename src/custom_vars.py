"""Custom variable builder scaffolding for V1."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.utils import normalize_text


def validate_custom_variable_name(name: str, existing: list[dict[str, Any]]) -> tuple[bool, str]:
    """Validate a new custom variable name."""
    cleaned = normalize_text(name)
    if not cleaned:
        return False, "Custom variable name is required."
    existing_names = {normalize_text(item.get("name")) for item in existing}
    if cleaned in existing_names:
        return False, "Custom variable name must be unique."
    return True, ""


def add_custom_variable_stub(
    existing: list[dict[str, Any]],
    name: str,
    expression: str,
) -> list[dict[str, Any]]:
    """Add a stored custom-variable scaffold entry."""
    updated = list(existing)
    updated.append(
        {
            "name": normalize_text(name),
            "expression": normalize_text(expression),
            "status": "scaffolded",
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    return updated


def list_custom_variable_summaries(existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a compact summary table for the UI."""
    return [
        {
            "name": item.get("name", ""),
            "status": item.get("status", ""),
            "created_at": item.get("created_at", ""),
        }
        for item in existing
    ]
