"""Helpers for configuring and resolving intra-question nets."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.metadata import get_display_variable_name
from src.utils import normalize_text


NET_LABELS = ["T2B", "T3B", "B2B", "B3B"]
NET_SIZES = {
    "T2B": 2,
    "T3B": 3,
    "B2B": 2,
    "B3B": 3,
}


def build_net_editor_frame(
    scale_questions: list[dict[str, Any]],
    scale_mappings: dict[str, dict[str, Any]],
    current_net_definitions: dict[str, dict[str, bool]] | None = None,
) -> pd.DataFrame:
    """Build a one-row-per-scale-question net configuration frame."""
    if not isinstance(current_net_definitions, dict):
        current_net_definitions = {}
    rows: list[dict[str, Any]] = []
    for question in scale_questions:
        variable = normalize_text(question.get("variable"))
        row: dict[str, Any] = {
            "variable": variable,
            "display_variable_name": get_display_variable_name(question),
            "question_label": normalize_text(question.get("question_label")),
        }
        mapping_rows = scale_mappings.get(variable, {}).get("rows", [])
        point_count = len(mapping_rows)
        saved = current_net_definitions.get(variable, {})
        for net_label in NET_LABELS:
            row[net_label] = bool(saved.get(net_label, False) and point_count >= NET_SIZES[net_label])
        rows.append(row)
    return pd.DataFrame(rows)


def toggle_net_column(editor_df: pd.DataFrame, net_label: str) -> pd.DataFrame:
    """Toggle a net checkbox column for all visible rows."""
    if editor_df.empty or net_label not in editor_df.columns:
        return editor_df
    updated = editor_df.copy()
    should_enable = not bool(updated[net_label].all())
    updated[net_label] = should_enable
    return updated


def save_net_editor_frame(editor_df: pd.DataFrame) -> dict[str, dict[str, bool]]:
    """Convert the editable net frame to a stored net-definition mapping."""
    definitions: dict[str, dict[str, bool]] = {}
    for row in editor_df.to_dict(orient="records"):
        variable = normalize_text(row.get("variable"))
        definitions[variable] = {
            net_label: bool(row.get(net_label, False))
            for net_label in NET_LABELS
        }
    return definitions


def build_enabled_net_choice_map(
    variable: str,
    net_definitions: dict[str, dict[str, bool]] | None,
    scale_mappings: dict[str, dict[str, Any]] | None,
) -> dict[str, list[str]]:
    """Return enabled net labels mapped to the raw response values they represent."""
    if not isinstance(net_definitions, dict):
        net_definitions = {}
    if not isinstance(scale_mappings, dict):
        scale_mappings = {}
    mapping_rows = sorted(
        scale_mappings.get(variable, {}).get("rows", []),
        key=lambda item: int(item.get("bucket", 0)),
    )
    ordered_values = [
        normalize_text(row.get("response_value"))
        for row in mapping_rows
        if normalize_text(row.get("response_value"))
    ]
    if not ordered_values:
        return {}

    enabled_map: dict[str, list[str]] = {}
    variable_defs = net_definitions.get(variable, {})
    for net_label in NET_LABELS:
        if not variable_defs.get(net_label, False):
            continue
        box_size = NET_SIZES[net_label]
        if len(ordered_values) < box_size:
            continue
        if net_label.startswith("T"):
            enabled_map[net_label] = ordered_values[:box_size]
        else:
            enabled_map[net_label] = ordered_values[-box_size:]
    return enabled_map
