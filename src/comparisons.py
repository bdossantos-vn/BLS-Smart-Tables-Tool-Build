"""Comparison-scheme helpers for layered control-vs-group analysis."""

from __future__ import annotations

from itertools import combinations
from typing import Any

import pandas as pd

from src.utils import normalize_text


COMPARISON_SCHEME_LEVEL = "__comparison_scheme__"
COMPARISON_SCHEME_DISPLAY_NAME = "Comparison Variable"


def build_default_comparison_scheme() -> dict[str, Any]:
    """Return the default comparison scheme payload."""
    return {
        "enabled": False,
        "mode": "exclusive",
        "control_group_id": "",
        "groups": [],
    }


def build_default_comparison_group(index: int = 1) -> dict[str, Any]:
    """Return one blank comparison-scheme group."""
    return {
        "id": f"group_{index}",
        "label": "",
        "role": "test",
        "match_logic": "ALL",
        "conditions": [
            {
                "variable": "",
                "operator": "",
                "values": [],
            }
        ],
    }


def is_layered_comparison_scheme(scheme: dict[str, Any] | None) -> bool:
    """Return whether the saved comparison scheme is active and usable."""
    if not isinstance(scheme, dict) or not bool(scheme.get("enabled")):
        return False
    groups = [group for group in scheme.get("groups", []) if normalize_text(group.get("id"))]
    return bool(groups)


def sanitize_comparison_scheme(scheme: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a stored comparison scheme without evaluating it."""
    if not isinstance(scheme, dict):
        return build_default_comparison_scheme()
    groups: list[dict[str, Any]] = []
    for index, group in enumerate(scheme.get("groups", []), start=1):
        group_id = normalize_text(group.get("id")) or f"group_{index}"
        label = normalize_text(group.get("label")) or group_id
        role = normalize_text(group.get("role")).lower()
        if role not in {"control", "test"}:
            role = "test"
        match_logic = normalize_text(group.get("match_logic")).upper() or "ALL"
        if match_logic not in {"ALL", "ANY"}:
            match_logic = "ALL"
        conditions: list[dict[str, Any]] = []
        for condition in group.get("conditions", []):
            variable = normalize_text(condition.get("variable"))
            operator = normalize_text(condition.get("operator"))
            values = [normalize_text(value) for value in condition.get("values", []) if normalize_text(value)]
            conditions.append(
                {
                    "variable": variable,
                    "operator": operator,
                    "values": values,
                }
            )
        groups.append(
            {
                "id": group_id,
                "label": label,
                "role": role,
                "match_logic": match_logic,
                "conditions": conditions,
            }
        )

    control_group_id = normalize_text(scheme.get("control_group_id"))
    if not control_group_id:
        control_group = next((group for group in groups if group.get("role") == "control"), None)
        control_group_id = normalize_text(control_group.get("id")) if control_group else ""

    mode = normalize_text(scheme.get("mode")).lower()
    if mode not in {"exclusive", "overlap"}:
        mode = "exclusive"
    return {
        "enabled": bool(scheme.get("enabled")),
        "mode": mode,
        "control_group_id": control_group_id,
        "groups": groups,
    }


def _value_matches_any(value: object, selected_choices: list[str]) -> bool:
    normalized_value = normalize_text(value)
    normalized_choices = {normalize_text(choice) for choice in selected_choices if normalize_text(choice)}
    if not normalized_value or not normalized_choices:
        return False
    if normalized_value in normalized_choices:
        return True
    split_parts = {
        normalize_text(part)
        for delimiter in [";", ","]
        for part in normalized_value.split(delimiter)
        if normalize_text(part)
    }
    if not split_parts:
        split_parts = {normalized_value}
    return bool(split_parts & normalized_choices)


def _value_matches_all(value: object, selected_choices: list[str]) -> bool:
    normalized_value = normalize_text(value)
    normalized_choices = [normalize_text(choice) for choice in selected_choices if normalize_text(choice)]
    if not normalized_value or not normalized_choices:
        return False
    split_parts = {
        normalize_text(part)
        for delimiter in [";", ","]
        for part in normalized_value.split(delimiter)
        if normalize_text(part)
    }
    if not split_parts:
        split_parts = {normalized_value}
    return set(normalized_choices).issubset(split_parts)


def _expand_selected_choices(
    variable: str,
    selected_choices: list[str],
    question_lookup: dict[str, dict[str, Any]],
) -> list[str]:
    expansion_map = question_lookup.get(variable, {}).get("choice_expansion_map", {})
    expanded: list[str] = []
    for choice in selected_choices:
        normalized_choice = normalize_text(choice)
        if not normalized_choice:
            continue
        for value in expansion_map.get(normalized_choice, [normalized_choice]):
            normalized_value = normalize_text(value)
            if normalized_value and normalized_value not in expanded:
                expanded.append(normalized_value)
    return expanded


def evaluate_condition(
    df: pd.DataFrame,
    condition: dict[str, Any],
    question_lookup: dict[str, dict[str, Any]] | None = None,
) -> pd.Series:
    """Evaluate one rule condition against a dataframe."""
    question_lookup = question_lookup or {}
    variable = normalize_text(condition.get("variable"))
    operator = normalize_text(condition.get("operator"))
    choices = _expand_selected_choices(variable, list(condition.get("values", [])), question_lookup)
    if variable not in df.columns:
        return pd.Series(False, index=df.index)

    series = df[variable]
    if operator == "Includes any":
        return series.map(lambda value: _value_matches_any(value, choices)).fillna(False)
    if operator == "Includes all":
        return series.map(lambda value: _value_matches_all(value, choices)).fillna(False)
    if operator == "Excludes all":
        return series.map(lambda value: not _value_matches_any(value, choices)).fillna(False)
    if operator == "Is exactly":
        normalized_choices = {normalize_text(choice) for choice in choices if normalize_text(choice)}
        return series.map(lambda value: normalize_text(value) in normalized_choices).fillna(False)
    if operator in {"Equals", "Does not equal", "Greater than", "Less than"}:
        numeric_series = pd.to_numeric(series, errors="coerce")
        numeric_choices = pd.to_numeric(pd.Series(choices), errors="coerce").dropna().tolist()
        if not numeric_choices:
            return pd.Series(False, index=df.index)
        target = numeric_choices[0]
        if operator == "Equals":
            return (numeric_series == target).fillna(False)
        if operator == "Does not equal":
            return (numeric_series != target).fillna(False)
        if operator == "Greater than":
            return (numeric_series > target).fillna(False)
        if operator == "Less than":
            return (numeric_series < target).fillna(False)
    return pd.Series(False, index=df.index)


def evaluate_rule_group(
    df: pd.DataFrame,
    group: dict[str, Any],
    question_lookup: dict[str, dict[str, Any]] | None = None,
) -> pd.Series:
    """Evaluate one layered comparison group into a respondent mask."""
    conditions = [condition for condition in group.get("conditions", []) if normalize_text(condition.get("variable"))]
    if not conditions:
        return pd.Series(False, index=df.index)
    masks = [evaluate_condition(df, condition, question_lookup) for condition in conditions]
    match_logic = normalize_text(group.get("match_logic")).upper() or "ALL"
    combined = masks[0]
    for mask in masks[1:]:
        combined = (combined | mask) if match_logic == "ANY" else (combined & mask)
    return combined.fillna(False)


def build_comparison_group_masks(
    df: pd.DataFrame,
    scheme: dict[str, Any] | None,
    question_lookup: dict[str, dict[str, Any]] | None = None,
    comparison_col: str | None = None,
    comparison_group_order: dict[str, int] | None = None,
    comparison_group_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build respondent masks for layered or simple comparison groups."""
    question_lookup = question_lookup or {}
    comparison_group_order = comparison_group_order or {}
    comparison_group_labels = comparison_group_labels or {}
    comparison_variable = normalize_text(comparison_col) or COMPARISON_SCHEME_LEVEL

    # 2026-05-19 BD: Layered comparison schemes keep raw group ids for logic and
    # use labels only for display/export so the team can merge this behavior.
    sanitized = sanitize_comparison_scheme(scheme)
    if is_layered_comparison_scheme(sanitized):
        groups: list[dict[str, Any]] = []
        for index, group in enumerate(sanitized.get("groups", []), start=1):
            group_id = normalize_text(group.get("id")) or f"group_{index}"
            label = normalize_text(group.get("label")) or group_id
            role = "control" if group_id == sanitized.get("control_group_id") or group.get("role") == "control" else "test"
            mask = evaluate_rule_group(df, group, question_lookup)
            groups.append(
                {
                    "id": group_id,
                    "comparison_group_id": group_id,
                    "label": label,
                    "role": role,
                    "mask": mask,
                    "values": {comparison_variable: group_id},
                    "display_values": {comparison_variable: label},
                    "comparison_mode": sanitized.get("mode", "exclusive"),
                    "comparison_scheme": True,
                }
            )
        return groups

    if not comparison_variable or comparison_variable not in df.columns:
        return []

    values = df[comparison_variable].map(normalize_text)
    unique_values = [value for value in values.dropna().unique().tolist() if value]
    if comparison_group_order:
        unique_values = sorted(unique_values, key=lambda value: comparison_group_order.get(value, 9999))
    groups = []
    for value in unique_values:
        display_label = comparison_group_labels.get(value, value)
        role = "control" if normalize_text(display_label).lower() == "control" or "control" in value.lower() else "test"
        groups.append(
            {
                "id": value,
                "comparison_group_id": value,
                "label": display_label,
                "role": role,
                "mask": (values == value).fillna(False),
                "values": {comparison_variable: value},
                "display_values": {comparison_variable: display_label},
                "comparison_mode": "exclusive",
            }
        )
    return groups


def materialize_comparison_variable(
    df: pd.DataFrame,
    scheme: dict[str, Any] | None,
    question_lookup: dict[str, dict[str, Any]] | None = None,
    column_name: str = COMPARISON_SCHEME_DISPLAY_NAME,
) -> pd.Series:
    """Return a display column for saved comparison-group membership."""
    sanitized = sanitize_comparison_scheme(scheme)
    if not is_layered_comparison_scheme(sanitized):
        return pd.Series([""] * len(df), index=df.index, dtype="object")

    memberships = pd.Series([""] * len(df), index=df.index, dtype="object")
    # 2026-05-19 BD: Materialize the finalized comparison setup as a visible
    # variable for setup screens while overlap-aware banners still use masks.
    for group in sanitized.get("groups", []):
        label = normalize_text(group.get("label")) or normalize_text(group.get("id"))
        if not label:
            continue
        mask = evaluate_rule_group(df, group, question_lookup).fillna(False)
        memberships.loc[mask] = memberships.loc[mask].map(
            lambda existing: f"{existing}; {label}" if normalize_text(existing) else label
        )
    return memberships.rename(column_name)


def detect_group_overlaps(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return pairwise overlap counts for non-total groups."""
    overlaps: list[dict[str, Any]] = []
    indexed_groups = [(index, group) for index, group in enumerate(groups) if group.get("label") != "Total"]
    for (left_index, left_group), (right_index, right_group) in combinations(indexed_groups, 2):
        overlap_count = int((left_group["mask"] & right_group["mask"]).sum())
        if overlap_count:
            overlaps.append(
                {
                    "left_index": left_index,
                    "right_index": right_index,
                    "left_label": normalize_text(left_group.get("label")),
                    "right_label": normalize_text(right_group.get("label")),
                    "overlap_n": overlap_count,
                }
            )
    return overlaps


def build_control_comparison_pairs(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build Control-vs-each-non-control pair metadata."""
    non_total_indexes = [index for index, group in enumerate(groups) if group.get("label") != "Total"]
    if len(non_total_indexes) < 2:
        return []
    control_index = next(
        (
            index
            for index in non_total_indexes
            if normalize_text(groups[index].get("role")).lower() == "control"
        ),
        None,
    )
    if control_index is None:
        control_index = next(
            (
                index
                for index in non_total_indexes
                if normalize_text(groups[index].get("label")).lower() == "control"
            ),
            None,
        )
    if control_index is None:
        return []

    pairs: list[dict[str, Any]] = []
    for right_index in non_total_indexes:
        if right_index == control_index:
            continue
        left_group = groups[control_index]
        right_group = groups[right_index]
        overlaps = bool((left_group["mask"] & right_group["mask"]).sum())
        pairs.append(
            {
                "left_index": control_index,
                "right_index": right_index,
                "subgroup_label": "Total",
                "left_label": normalize_text(left_group.get("label")) or "Control",
                "right_label": normalize_text(right_group.get("label")) or "Test",
                "overlap": overlaps,
                "test_type": "paired_overlap" if overlaps else "independent",
                "parent_key": (),
            }
        )
    return pairs


def summarize_comparison_groups(groups: list[dict[str, Any]]) -> pd.DataFrame:
    """Build a compact group-base summary dataframe for setup screens."""
    rows = []
    for group in groups:
        rows.append(
            {
                "Group": normalize_text(group.get("label")),
                "Role": normalize_text(group.get("role")).title() or "Test",
                "Base N": int(group.get("mask", pd.Series(dtype=bool)).sum()),
            }
        )
    return pd.DataFrame(rows)
