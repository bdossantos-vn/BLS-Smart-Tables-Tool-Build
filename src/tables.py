"""Core table-generation helpers for the BLS Smart Tables Tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from scipy.stats import norm

from src.comparisons import (
    COMPARISON_SCHEME_DISPLAY_NAME,
    COMPARISON_SCHEME_LEVEL,
    build_comparison_group_masks,
    build_control_comparison_pairs,
    detect_group_overlaps,
    is_layered_comparison_scheme,
    sanitize_comparison_scheme,
)
from src.custom_vars import build_question_lookup
from src.metadata import build_display_variable_lookup, get_display_variable_name
from src.nets import build_enabled_net_choice_map
from src.stats import normalize_confidence_intervals
from src.utils import alpha_letter_sequence, normalize_text


@dataclass
class SheetTable:
    """One rendered question table destined for a workbook sheet."""

    variable: str
    question_label: str
    sections: list[dict[str, Any]]
    display_variable_name: str = ""
    banner_name: str = ""
    levels: list[str] = field(default_factory=list)
    level_labels: dict[str, str] = field(default_factory=dict)
    groups: list[dict[str, Any]] = field(default_factory=list)
    comparison_pairs: list[dict[str, Any]] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    include_percentage: bool = True
    include_n_count: bool = False
    include_stat_testing: bool = True
    notation_location: str = "appended_to_metric"


@dataclass
class WorkbookSheet:
    """One workbook sheet with banner metadata and rendered tables."""

    name: str
    banner_name: str
    levels: list[str]
    groups: list[dict[str, Any]]
    tables: list[SheetTable]
    level_labels: dict[str, str] = field(default_factory=dict)
    comparison_pairs: list[dict[str, Any]] = field(default_factory=list)
    footnotes: list[str] = field(default_factory=list)
    include_percentage: bool = True
    include_n_count: bool = False
    include_stat_testing: bool = True
    notation_location: str = "appended_to_metric"


@dataclass
class ToplineSheet:
    """One flat topline sheet used for quick analyst summaries.

    This sheet is intentionally flatter than the banner sheets. It is meant to
    surface the most useful control-vs-test comparison rows and short notes in
    one place.
    """

    rows: list[dict[str, Any]]
    footnotes: list[str] = field(default_factory=list)


def describe_generation_readiness(default_state: dict, current_state: dict) -> list[str]:
    """Explain whether the project is ready to generate export tables."""
    messages: list[str] = []
    cleaned_df = current_state.get("cleaned_df")
    question_metadata = current_state.get("question_metadata", [])
    if cleaned_df is None or getattr(cleaned_df, "empty", True):
        messages.append("No cleaned dataset is available yet.")
    else:
        messages.append("A cleaned dataset is available.")
    if not question_metadata:
        messages.append("Question metadata has not been configured yet.")
    else:
        messages.append("Question metadata is available.")
    banner_count = len(current_state.get("banner_config", {}).get("banners", []))
    if banner_count:
        export_style = normalize_text(current_state.get("banner_config", {}).get("export_style")) or "one_per_sheet"
        if export_style == "single_sheet":
            messages.append(f"{banner_count} banner table(s) are configured to export on 1 combined banner sheet.")
        else:
            messages.append(f"{banner_count} banner sheet(s) are configured.")
    else:
        messages.append("No banners configured. Export will use a single `All Tables` sheet.")
    adhoc_count = len(current_state.get("adhoc_crosstabs_config", {}).get("tables", []))
    if adhoc_count:
        messages.append(f"{adhoc_count} AdHoc Crosstab(s) are configured.")
    return messages


def _include_percentage(stat_config: dict[str, Any]) -> bool:
    """Return whether percent rows should be exported for this table family."""
    return bool(stat_config.get("include_percentage", True))


def _include_stat_testing(stat_config: dict[str, Any]) -> bool:
    """Return whether significance letters should be calculated and exported."""
    comparison_scope = normalize_text(stat_config.get("comparison_scope"))
    return bool(stat_config.get("enabled", True)) and comparison_scope != "none"


def _effective_comparison_scope(stat_config: dict[str, Any], fallback: str = "lowest_banner_level") -> str:
    """Return the comparison scope that should be used by table calculations."""
    if not _include_stat_testing(stat_config):
        return "none"
    return normalize_text(stat_config.get("comparison_scope")) or fallback


def _comparison_scope_for_groups(requested_scope: str, groups: list[dict[str, Any]]) -> str:
    """Return a usable significance scope for the currently visible groups."""
    scope = normalize_text(requested_scope) or "lowest_banner_level"
    if scope == "none":
        return "none"
    if scope != "control_vs_test":
        return "lowest_banner_level"
    has_control = any(
        normalize_text(group.get("role")).lower() == "control"
        or normalize_text(group.get("label")).casefold() == "control"
        for group in groups
        if group.get("label") != "Total"
    )
    return "control_vs_test" if has_control else "lowest_banner_level"


def _topline_comparison_scope(
    topline_config: dict[str, Any],
    banner_scope: str,
    groups: list[dict[str, Any]],
) -> str:
    """Return the comparison scope requested for the topline sheet."""
    requested_scope = normalize_text(topline_config.get("comparison_scope")) or banner_scope
    if requested_scope not in {"control_vs_test", "lowest_banner_level", "none"}:
        requested_scope = banner_scope
    return _comparison_scope_for_groups(requested_scope, groups)


def _notation_location(stat_config: dict[str, Any]) -> str:
    """Return a supported significance notation placement."""
    value = normalize_text(stat_config.get("notation_location"))
    return value if value in {"appended_to_metric", "below_metric"} else "appended_to_metric"


def _normalize_banner_rows(
    banner_config: dict[str, Any],
    variable_display_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return banner rows that have at least one configured level."""
    variable_display_names = variable_display_names or {}
    rows: list[dict[str, Any]] = []
    for row in banner_config.get("banners", []):
        levels = [
            normalize_text(row.get("level_1")),
            normalize_text(row.get("level_2")),
            normalize_text(row.get("level_3")),
        ]
        if levels[0]:
            rows.append(
                {
                    "name": normalize_text(row.get("name")) or variable_display_names.get(levels[0], levels[0]),
                    "levels": [value for value in levels if value],
                    "level_labels": {
                        value: COMPARISON_SCHEME_DISPLAY_NAME
                        if normalize_text(value) == COMPARISON_SCHEME_LEVEL
                        else variable_display_names.get(value, value)
                        for value in levels
                        if value
                    },
                }
            )
    return rows


def _materialize_custom_variables(
    df: pd.DataFrame,
    custom_variables: list[dict[str, Any]],
    question_lookup: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    """Create an analysis dataframe that includes saved custom-variable columns."""
    materialized = df.copy()
    for record in custom_variables:
        variable_name = normalize_text(record.get("name"))
        if not variable_name:
            continue
        builder_type = normalize_text(record.get("builder_type"))
        if builder_type == "Simple Variable":
            materialized[variable_name] = _evaluate_simple_custom_variable(
                materialized,
                record,
                question_lookup,
            )
        elif builder_type == "Complex Variable":
            materialized[variable_name] = _evaluate_complex_custom_variable(
                materialized,
                record,
                question_lookup,
            )
    return materialized


def _value_matches_selected_choices(value: object, selected_choices: list[str]) -> bool:
    """Return whether a respondent value matches any selected choice."""
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


def _value_matches_all_selected_choices(value: object, selected_choices: list[str]) -> bool:
    """Return whether a respondent value matches all selected choices."""
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
    """Expand net labels into their underlying response options."""
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


def _condition_matches(
    series: pd.Series,
    operator: str,
    choices: list[str],
) -> pd.Series:
    """Evaluate one complex-variable condition against a pandas series."""
    if operator == "Includes any":
        return series.map(lambda value: _value_matches_selected_choices(value, choices)).fillna(False)
    if operator == "Includes all":
        return series.map(lambda value: _value_matches_all_selected_choices(value, choices)).fillna(False)
    if operator == "Excludes all":
        return series.map(lambda value: not _value_matches_selected_choices(value, choices)).fillna(False)
    if operator == "Is exactly":
        normalized_choices = {normalize_text(choice) for choice in choices if normalize_text(choice)}
        return series.map(lambda value: normalize_text(value) in normalized_choices).fillna(False)
    if operator in {"Equals", "Does not equal", "Greater than", "Less than"}:
        numeric_series = pd.to_numeric(series, errors="coerce")
        numeric_choices = pd.to_numeric(pd.Series(choices), errors="coerce").dropna().tolist()
        if not numeric_choices:
            return pd.Series(False, index=series.index)
        target = numeric_choices[0]
        if operator == "Equals":
            return (numeric_series == target).fillna(False)
        if operator == "Does not equal":
            return (numeric_series != target).fillna(False)
        if operator == "Greater than":
            return (numeric_series > target).fillna(False)
        if operator == "Less than":
            return (numeric_series < target).fillna(False)
    return pd.Series(False, index=series.index)


def _evaluate_simple_custom_variable(
    df: pd.DataFrame,
    record: dict[str, Any],
    question_lookup: dict[str, dict[str, Any]],
) -> pd.Series:
    """Assign each respondent to one simple custom-variable bucket."""
    source_variable = normalize_text((record.get("source_variables") or [""])[0])
    if source_variable not in df.columns:
        return pd.Series([None] * len(df), index=df.index, dtype="object")

    result = pd.Series([None] * len(df), index=df.index, dtype="object")
    remaining_mask = pd.Series(True, index=df.index)
    for bucket in record.get("buckets", []):
        bucket_label = normalize_text(bucket.get("label"))
        selected_choices = _expand_selected_choices(
            source_variable,
            list(bucket.get("choices", [])),
            question_lookup,
        )
        if not bucket_label or not selected_choices:
            continue
        matched_mask = df[source_variable].map(
            lambda value: _value_matches_selected_choices(value, selected_choices)
        ).fillna(False)
        bucket_mask = remaining_mask & matched_mask
        result.loc[bucket_mask] = bucket_label
        remaining_mask = remaining_mask & ~bucket_mask

    if normalize_text(record.get("fallback_mode")) == "Create additional option":
        fallback_label = normalize_text(record.get("fallback_label")) or "Other"
        result.loc[remaining_mask] = fallback_label
    return result


def _evaluate_complex_custom_variable(
    df: pd.DataFrame,
    record: dict[str, Any],
    question_lookup: dict[str, dict[str, Any]],
) -> pd.Series:
    """Assign each respondent to one complex custom-variable bucket."""
    result = pd.Series([None] * len(df), index=df.index, dtype="object")
    remaining_mask = pd.Series(True, index=df.index)

    for bucket in record.get("buckets", []):
        bucket_label = normalize_text(bucket.get("label"))
        conditions = list(bucket.get("conditions", []))
        match_logic = normalize_text(bucket.get("match_logic")) or "ALL"
        if not bucket_label or not conditions:
            continue

        condition_masks: list[pd.Series] = []
        for condition in conditions:
            variable = normalize_text(condition.get("variable"))
            operator = normalize_text(condition.get("operator"))
            expanded_choices = _expand_selected_choices(
                variable,
                list(condition.get("choices", [])),
                question_lookup,
            )
            if variable not in df.columns:
                condition_masks.append(pd.Series(False, index=df.index))
                continue
            condition_masks.append(_condition_matches(df[variable], operator, expanded_choices))

        if not condition_masks:
            continue
        combined_mask = condition_masks[0].copy()
        for mask in condition_masks[1:]:
            if match_logic == "ANY":
                combined_mask = combined_mask | mask
            else:
                combined_mask = combined_mask & mask

        bucket_mask = remaining_mask & combined_mask.fillna(False)
        result.loc[bucket_mask] = bucket_label
        remaining_mask = remaining_mask & ~bucket_mask

    if normalize_text(record.get("fallback_mode")) == "Create additional option":
        fallback_label = normalize_text(record.get("fallback_label")) or "Other"
        result.loc[remaining_mask] = fallback_label
    return result


def _build_variable_order_lookup(
    variable: str,
    question_lookup: dict[str, dict[str, Any]],
    custom_variables: list[dict[str, Any]],
    comparison_col: str | None,
    comparison_group_order: dict[str, int],
) -> list[str]:
    """Return the preferred display order for a banner variable."""
    if variable == normalize_text(comparison_col):
        return [
            group
            for group, _ in sorted(comparison_group_order.items(), key=lambda item: item[1])
        ]
    if variable in question_lookup:
        return list(question_lookup[variable].get("answer_choices_list", []))
    for record in custom_variables:
        if normalize_text(record.get("name")) == variable:
            bucket_labels = [normalize_text(bucket.get("label")) for bucket in record.get("buckets", []) if normalize_text(bucket.get("label"))]
            if normalize_text(record.get("fallback_mode")) == "Create additional option":
                bucket_labels.append(normalize_text(record.get("fallback_label")) or "Other")
            return bucket_labels
    return []


def _build_custom_variable_question_row(
    variable: str,
    custom_variables: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build question-like metadata for a materialized custom variable."""
    for record in custom_variables:
        if normalize_text(record.get("name")) != variable:
            continue
        answer_choices = [normalize_text(bucket.get("label")) for bucket in record.get("buckets", []) if normalize_text(bucket.get("label"))]
        if normalize_text(record.get("fallback_mode")) == "Create additional option":
            answer_choices.append(normalize_text(record.get("fallback_label")) or "Other")
        return {
            "variable": variable,
            "display_variable_name": variable,
            "question_label": variable,
            "detected_type": "Single-Select",
            "answer_choices_list": answer_choices,
        }
    return None


def _apply_selected_response_filter(
    question_row: dict[str, Any],
    selected_responses: list[str],
) -> dict[str, Any]:
    """Return a question row limited to a chosen response subset when available."""
    allowed = {normalize_text(value) for value in selected_responses if normalize_text(value)}
    if not allowed:
        return question_row

    filtered_choices = [
        choice
        for choice in question_row.get("answer_choices_list", [])
        if normalize_text(choice) in allowed
    ]
    if not filtered_choices:
        return question_row

    updated_question_row = dict(question_row)
    updated_question_row["answer_choices_list"] = filtered_choices
    return updated_question_row


def _build_adhoc_multiselect_groups(
    df: pd.DataFrame,
    variable: str,
    include_total: bool,
    question_lookup: dict[str, dict[str, Any]],
    comparison_col: str | None,
    comparison_group_labels: dict[str, str],
) -> list[dict[str, Any]]:
    """Build selected/not-selected column groups for AdHoc multi-select crosstabs."""
    groups: list[dict[str, Any]] = []
    if include_total:
        groups.append(
            {
                "label": "Total",
                "mask": pd.Series(True, index=df.index),
                "values": {},
            }
        )
    question_row = question_lookup.get(variable, {})
    answer_choices = list(question_row.get("answer_choices_list", []))
    series = df[variable] if variable in df.columns else pd.Series([None] * len(df), index=df.index)
    for choice in answer_choices:
        normalized_choice = normalize_text(choice)
        selected_label = comparison_group_labels.get(normalized_choice, choice) if variable == normalize_text(comparison_col) else choice
        selected_mask = series.map(lambda value: _value_matches_selected_choices(value, [normalized_choice])).fillna(False)
        not_selected_mask = (~selected_mask).fillna(False)
        groups.append(
            {
                "label": f"{selected_label} - Selected",
                "mask": selected_mask,
                "values": {variable: normalized_choice, "__selection_status__": "Selected"},
                "display_values": {variable: selected_label, "__selection_status__": "Selected"},
            }
        )
        groups.append(
            {
                "label": f"{selected_label} - Not Selected",
                "mask": not_selected_mask,
                "values": {variable: normalized_choice, "__selection_status__": "Not Selected"},
                "display_values": {variable: selected_label, "__selection_status__": "Not Selected"},
            }
        )
    return groups


def _sort_group_rows(
    rows: list[dict[str, Any]],
    levels: list[str],
    question_lookup: dict[str, dict[str, Any]],
    custom_variables: list[dict[str, Any]],
    comparison_col: str | None,
    comparison_group_order: dict[str, int],
) -> list[dict[str, Any]]:
    """Sort banner group combinations using known answer-choice order when possible."""
    order_maps: dict[str, dict[str, int]] = {}
    for level in levels:
        ordered_values = _build_variable_order_lookup(
            level,
            question_lookup,
            custom_variables,
            comparison_col,
            comparison_group_order,
        )
        order_maps[level] = {normalize_text(value): index for index, value in enumerate(ordered_values)}

    def _sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        key_parts: list[Any] = []
        for level in levels:
            value = normalize_text(row["values"].get(level))
            order_map = order_maps.get(level, {})
            key_parts.append(order_map.get(value, 9999))
            key_parts.append(value.lower())
        return tuple(key_parts)

    return sorted(rows, key=_sort_key)


def _build_banner_groups(
    df: pd.DataFrame,
    banner_row: dict[str, Any] | None,
    include_total: bool,
    question_lookup: dict[str, dict[str, Any]],
    custom_variables: list[dict[str, Any]],
    comparison_col: str | None,
    comparison_group_order: dict[str, int],
    comparison_group_labels: dict[str, str],
) -> list[dict[str, Any]]:
    """Build the display groups for one banner sheet."""
    groups: list[dict[str, Any]] = []
    if include_total:
        groups.append(
            {
                "label": "Total",
                "mask": pd.Series(True, index=df.index),
                "values": {},
            }
        )

    if not banner_row:
        return groups

    levels = list(banner_row.get("levels", []))
    if not levels:
        return groups

    working = df[levels].copy()
    for level in levels:
        working[level] = working[level].map(normalize_text)
    working = working.loc[(working != "").all(axis=1)]
    if working.empty:
        return groups

    distinct_rows = working.drop_duplicates().to_dict(orient="records")
    sorted_rows = _sort_group_rows(
        [{"values": row} for row in distinct_rows],
        levels,
        question_lookup,
        custom_variables,
        comparison_col,
        comparison_group_order,
    )
    for row in sorted_rows:
        values = row["values"]
        mask = pd.Series(True, index=df.index)
        for level in levels:
            mask = mask & (df[level].map(normalize_text) == normalize_text(values[level]))
        label_parts: list[str] = []
        for level in levels:
            raw_value = normalize_text(values[level])
            if normalize_text(level) == normalize_text(comparison_col):
                label_parts.append(comparison_group_labels.get(raw_value, raw_value))
            else:
                label_parts.append(raw_value)
        label = " | ".join(label_parts)
        groups.append(
            {
                "label": label,
                "mask": mask.fillna(False),
                "values": values,
                "display_values": {
                    level: (
                        comparison_group_labels.get(normalize_text(values[level]), normalize_text(values[level]))
                        if normalize_text(level) == normalize_text(comparison_col)
                        else normalize_text(values[level])
                    )
                    for level in levels
                },
            }
        )
    return groups


def _build_total_comparison_groups(
    df: pd.DataFrame,
    comparison_col: str | None,
    comparison_group_order: dict[str, int],
    comparison_group_labels: dict[str, str],
) -> list[dict[str, Any]]:
    """Build plain total-level comparison groups with no banner nesting.

    Inputs:
        df: Current analysis dataframe.
        comparison_col: The selected comparison variable, usually `cell`.
        comparison_group_order: Preferred order for comparison groups.

    Outputs:
        A list of plain groups like `control` and `test`, each spanning the
        total sample only.
    """
    comparison_variable = normalize_text(comparison_col)
    if not comparison_variable or comparison_variable not in df.columns:
        return []

    values = df[comparison_variable].map(normalize_text)
    unique_values = [value for value in values.dropna().unique().tolist() if value]
    if comparison_group_order:
        unique_values = sorted(
            unique_values,
            key=lambda value: comparison_group_order.get(value, 9999),
        )
    groups: list[dict[str, Any]] = []
    for value in unique_values:
        groups.append(
            {
                "id": value,
                "comparison_group_id": value,
                "label": comparison_group_labels.get(value, value),
                "role": "control" if comparison_group_labels.get(value, value).lower() == "control" or "control" in value.lower() else "test",
                "mask": (values == value).fillna(False),
                "values": {comparison_variable: value},
                "display_values": {comparison_variable: comparison_group_labels.get(value, value)},
                "comparison_mode": "exclusive",
            }
        )
    return groups


def _comparison_level_key(comparison_col: str | None, layered_scheme_active: bool = False) -> str:
    """Return the column/key used to represent comparison groups."""
    if layered_scheme_active:
        return normalize_text(comparison_col) or COMPARISON_SCHEME_LEVEL
    return normalize_text(comparison_col)


def _layered_banner_levels(banner_row: dict[str, Any] | None, comparison_col: str | None) -> list[str]:
    """Return banner levels with the layered comparison group as the lowest split."""
    comparison_variable = normalize_text(comparison_col)
    parent_levels = [
        level
        for level in list((banner_row or {}).get("levels", []))
        if normalize_text(level)
        and normalize_text(level) not in {comparison_variable, COMPARISON_SCHEME_LEVEL}
    ]
    return [*parent_levels, _comparison_level_key(comparison_col, True)]


def _build_layered_banner_groups(
    df: pd.DataFrame,
    banner_row: dict[str, Any] | None,
    include_total: bool,
    comparison_groups: list[dict[str, Any]],
    comparison_col: str | None,
    question_lookup: dict[str, dict[str, Any]],
    custom_variables: list[dict[str, Any]],
    comparison_group_order: dict[str, int],
) -> list[dict[str, Any]]:
    """Build groups that cross each banner subgroup with layered cells."""
    groups: list[dict[str, Any]] = []
    if include_total:
        groups.append(
            {
                "label": "Total",
                "mask": pd.Series(True, index=df.index),
                "values": {},
                "display_values": {},
            }
        )

    if not comparison_groups:
        return groups

    comparison_variable = _comparison_level_key(comparison_col, True)
    parent_levels = [
        level
        for level in list((banner_row or {}).get("levels", []))
        if normalize_text(level)
        and normalize_text(level) not in {normalize_text(comparison_col), COMPARISON_SCHEME_LEVEL}
    ]

    # 2026-05-19 BD: Layered schemes are appended as the lowest banner level so
    # every banner compares Control against each saved non-control group.
    if not parent_levels:
        for comparison_group in comparison_groups:
            copied_group = dict(comparison_group)
            copied_group["values"] = {comparison_variable: comparison_group.get("comparison_group_id", comparison_group.get("id", ""))}
            copied_group["display_values"] = {comparison_variable: comparison_group.get("label", "")}
            copied_group["parent_key"] = ()
            groups.append(copied_group)
        return groups

    available_parent_levels = [level for level in parent_levels if level in df.columns]
    if len(available_parent_levels) != len(parent_levels):
        return groups

    working = df[parent_levels].copy()
    for level in parent_levels:
        working[level] = working[level].map(normalize_text)
    working = working.loc[(working != "").all(axis=1)]
    if working.empty:
        return groups

    distinct_rows = working.drop_duplicates().to_dict(orient="records")
    sorted_rows = _sort_group_rows(
        [{"values": row} for row in distinct_rows],
        parent_levels,
        question_lookup,
        custom_variables,
        comparison_col,
        comparison_group_order,
    )
    for row in sorted_rows:
        parent_values = {level: normalize_text(row["values"].get(level)) for level in parent_levels}
        parent_mask = pd.Series(True, index=df.index)
        for level, value in parent_values.items():
            parent_mask = parent_mask & (df[level].map(normalize_text) == value)
        parent_label_parts = [value for value in parent_values.values() if value]
        parent_key = tuple((level, value) for level, value in parent_values.items())
        for comparison_group in comparison_groups:
            comparison_group_id = normalize_text(
                comparison_group.get("comparison_group_id") or comparison_group.get("id")
            )
            comparison_label = normalize_text(comparison_group.get("label")) or comparison_group_id
            values = {**parent_values, comparison_variable: comparison_group_id}
            display_values = {**parent_values, comparison_variable: comparison_label}
            groups.append(
                {
                    "id": "|".join([*parent_label_parts, comparison_group_id]),
                    "comparison_group_id": comparison_group_id,
                    "label": " | ".join([*parent_label_parts, comparison_label]),
                    "role": comparison_group.get("role", "test"),
                    "mask": (parent_mask & comparison_group["mask"]).fillna(False),
                    "values": values,
                    "display_values": display_values,
                    "comparison_mode": comparison_group.get("comparison_mode", "exclusive"),
                    "comparison_scheme": True,
                    "parent_key": parent_key,
                }
            )
    return groups


def _target_matches(applies_to: list[str], target_names: list[str]) -> bool:
    """Return whether one config row applies to the current export target."""
    normalized_targets = {normalize_text(value) for value in target_names if normalize_text(value)}
    normalized_applies = {normalize_text(value) for value in applies_to if normalize_text(value)}
    if not normalized_applies or "all tables" in normalized_applies:
        return True
    return bool(normalized_targets & normalized_applies)


def _evaluate_filter_branch(
    df: pd.DataFrame,
    branch: dict[str, Any],
    question_lookup: dict[str, dict[str, Any]],
) -> pd.Series:
    """Evaluate one saved filter branch against the analysis dataframe."""
    conditions = list(branch.get("conditions", []))
    if not conditions:
        return pd.Series(True, index=df.index)
    match_logic = normalize_text(branch.get("match_logic")) or "ALL"
    branch_mask: pd.Series | None = None
    for condition in conditions:
        variable = normalize_text(condition.get("variable"))
        operator = normalize_text(condition.get("operator"))
        choices = list(condition.get("values", []))
        if variable not in df.columns:
            condition_mask = pd.Series(False, index=df.index)
        else:
            expanded_choices = _expand_selected_choices(variable, choices, question_lookup)
            condition_mask = _condition_matches(df[variable], operator, expanded_choices)
        if branch_mask is None:
            branch_mask = condition_mask
        elif match_logic == "ANY":
            branch_mask = branch_mask | condition_mask
        else:
            branch_mask = branch_mask & condition_mask
    return (branch_mask if branch_mask is not None else pd.Series(True, index=df.index)).fillna(False)


def _apply_targeted_filters(
    df: pd.DataFrame,
    global_filters: dict[str, Any],
    target_names: list[str],
    question_lookup: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, list[str]]:
    """Apply saved filter rows that target the current sheet/table."""
    filtered_df = df.copy()
    applied_filters: list[str] = []
    for row in global_filters.get("rows", []):
        if not _target_matches(list(row.get("applies_to", [])), target_names):
            continue
        branch_masks: list[pd.Series] = []
        for branch in row.get("branches", []):
            branch_masks.append(_evaluate_filter_branch(filtered_df, branch, question_lookup))
        if not branch_masks:
            continue
        combined_mask = branch_masks[0]
        for mask in branch_masks[1:]:
            combined_mask = combined_mask | mask
        filtered_df = filtered_df.loc[combined_mask.fillna(False)].copy()
        applied_filters.append(normalize_text(row.get("name")) or "Unnamed Filter")
    return filtered_df, applied_filters


def _resolve_weighting_footnotes(weighting_config: dict[str, Any], target_names: list[str]) -> list[str]:
    """Summarize weighting rows that target the current sheet/table."""
    notes: list[str] = []
    for row in weighting_config.get("weights", []):
        if not _target_matches(list(row.get("applies_to", [])), target_names):
            continue
        weight_name = normalize_text(row.get("name")) or "Unnamed Weight"
        notes.append(f"Weighting configured: {weight_name}")
    return notes


def _build_table_footnotes(
    stat_config: dict[str, Any],
    applied_filters: list[str],
    weighting_notes: list[str],
    layered_scheme_active: bool = False,
    has_overlaps: bool = False,
    comparison_scope_override: str | None = None,
) -> list[str]:
    """Build export footnotes for one sheet or table."""
    footnotes: list[str] = []
    comparison_scope = normalize_text(comparison_scope_override) or normalize_text(stat_config.get("comparison_scope"))
    if comparison_scope == "none" or not bool(stat_config.get("enabled", True)):
        footnotes.append("Stat testing: None")
    else:
        ci_values = normalize_confidence_intervals(stat_config.get("confidence_intervals", [95]))
        ci_text = ", ".join(f"{value}%" for value in ci_values) if ci_values else "95%"
        if layered_scheme_active:
            # 2026-05-19 BD: Layered comparisons auto-select independent or
            # overlap-aware paired tests and apply Holm correction per row.
            if comparison_scope == "control_vs_test":
                footnotes.append(f"Stat testing: automatic Control-vs-group proportion tests at {ci_text}")
            else:
                footnotes.append(f"Stat testing: automatic all-cell proportion tests at {ci_text}")
            footnotes.append(
                "Independent tests are used for disjoint pairs; paired overlap-aware tests are used for overlapping pairs; Holm-adjusted across layered comparisons."
            )
            if has_overlaps:
                footnotes.append("Layered comparison groups overlap; group bases may not sum to the total sample.")
        else:
            footnotes.append(f"Stat testing: independent two-sample z-test at {ci_text}")
            footnotes.append("Significance letters compare within each section only.")
    if applied_filters:
        footnotes.append(f"Filters applied: {', '.join(applied_filters)}")
    else:
        footnotes.append("Filters applied: None")
    if weighting_notes:
        footnotes.extend(weighting_notes)
    else:
        footnotes.append("Weighting applied: None")
    return footnotes


def _compute_choice_count(series: pd.Series, choice: str) -> pd.Series:
    """Return a boolean mask for respondents who selected one choice."""
    normalized_choice = normalize_text(choice)
    return series.map(lambda value: _value_matches_selected_choices(value, [normalized_choice])).fillna(False)


def _get_question_rows(
    variable: str,
    question_row: dict[str, Any],
    net_definitions: dict[str, dict[str, bool]],
    scale_mappings: dict[str, dict[str, Any]],
    comparison_col: str | None = None,
    comparison_group_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Return the ordered output rows for one question table."""
    rows: list[dict[str, Any]] = []
    question_type = normalize_text(question_row.get("detected_type"))
    answer_choices = list(question_row.get("answer_choices_list", []))
    comparison_variable = normalize_text(comparison_col)
    label_map = comparison_group_labels or {}
    if question_type == "Scale / Likert":
        net_choice_map = build_enabled_net_choice_map(variable, net_definitions, scale_mappings)
        for net_label in ["T2B", "T3B", "B2B", "B3B"]:
            if net_label in net_choice_map:
                rows.append(
                    {
                        "label": net_label,
                        "choices": list(net_choice_map[net_label]),
                        "kind": "net",
                    }
                )
    if bool(question_row.get("adhoc_multiselect_binary")) and question_type == "Multi-Select":
        for choice in answer_choices:
            rows.append(
                {
                    "label": f"{choice} - Selected",
                    "source_label": choice,
                    "choices": [choice],
                    "kind": "choice",
                    "match_mode": "selected",
                }
            )
            rows.append(
                {
                    "label": f"{choice} - Not Selected",
                    "source_label": choice,
                    "choices": [choice],
                    "kind": "choice",
                    "match_mode": "not_selected",
                }
            )
        return rows
    for choice in answer_choices:
        row_label = choice
        if normalize_text(variable) == comparison_variable:
            normalized_choice = normalize_text(choice)
            row_label = label_map.get(normalized_choice, choice)
        rows.append(
            {
                "label": row_label,
                "source_label": choice,
                "choices": [choice],
                "kind": "choice",
            }
        )
    return rows


def _pooled_two_sample_z_test(
    numerator_a: int,
    denominator_a: int,
    numerator_b: int,
    denominator_b: int,
    alpha: float,
) -> bool:
    """Return whether proportion A is significantly higher than proportion B."""
    if denominator_a <= 0 or denominator_b <= 0:
        return False
    proportion_a = numerator_a / denominator_a
    proportion_b = numerator_b / denominator_b
    pooled = (numerator_a + numerator_b) / (denominator_a + denominator_b)
    standard_error = (pooled * (1 - pooled) * ((1 / denominator_a) + (1 / denominator_b))) ** 0.5
    if standard_error <= 0:
        return False
    z_value = (proportion_a - proportion_b) / standard_error
    critical = norm.ppf(1 - alpha / 2)
    return z_value > critical


def _pooled_two_sample_z_p_value(
    numerator_a: int,
    denominator_a: int,
    numerator_b: int,
    denominator_b: int,
) -> float | None:
    """Return a two-sided pooled z-test p-value for independent proportions."""
    if denominator_a <= 0 or denominator_b <= 0:
        return None
    proportion_a = numerator_a / denominator_a
    proportion_b = numerator_b / denominator_b
    pooled = (numerator_a + numerator_b) / (denominator_a + denominator_b)
    standard_error = (pooled * (1 - pooled) * ((1 / denominator_a) + (1 / denominator_b))) ** 0.5
    if standard_error <= 0:
        return None
    z_value = (proportion_a - proportion_b) / standard_error
    return float(2 * (1 - norm.cdf(abs(z_value))))


def _overlap_aware_proportion_p_value(
    mask_a: pd.Series,
    mask_b: pd.Series,
    outcome_mask: pd.Series,
) -> float | None:
    """Return a two-sided overlap-aware p-value for two proportions."""
    aligned_a = mask_a.reindex(outcome_mask.index, fill_value=False).astype(bool)
    aligned_b = mask_b.reindex(outcome_mask.index, fill_value=False).astype(bool)
    aligned_outcome = outcome_mask.reindex(outcome_mask.index, fill_value=False).astype(bool)
    denominator_a = int(aligned_a.sum())
    denominator_b = int(aligned_b.sum())
    if denominator_a <= 0 or denominator_b <= 0:
        return None
    proportion_a = float((aligned_a & aligned_outcome).sum()) / denominator_a
    proportion_b = float((aligned_b & aligned_outcome).sum()) / denominator_b
    outcome_numeric = aligned_outcome.astype(float)
    influence = (
        aligned_a.astype(float) * (outcome_numeric - proportion_a) / denominator_a
        - aligned_b.astype(float) * (outcome_numeric - proportion_b) / denominator_b
    )
    standard_error = float((influence ** 2).sum() ** 0.5)
    if standard_error <= 0:
        return None
    z_value = (proportion_a - proportion_b) / standard_error
    return float(2 * (1 - norm.cdf(abs(z_value))))


def _holm_adjust_p_values(p_values: list[float | None]) -> list[float | None]:
    """Apply Holm-Bonferroni adjustment to a related set of p-values."""
    indexed_values = [(index, value) for index, value in enumerate(p_values) if value is not None]
    if not indexed_values:
        return [None for _ in p_values]
    ordered = sorted(indexed_values, key=lambda item: item[1])
    adjusted = [None for _ in p_values]
    running_max = 0.0
    total = len(ordered)
    for rank, (index, value) in enumerate(ordered):
        adjusted_value = min((total - rank) * value, 1.0)
        running_max = max(running_max, adjusted_value)
        adjusted[index] = running_max
    return adjusted


def _infer_comparison_pairs_for_sig(
    groups: list[dict[str, Any]],
    comparison_scope: str,
    comparison_pairs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return comparison pairs for one significance row."""
    if comparison_scope == "none":
        return []
    if comparison_scope == "control_vs_test":
        return comparison_pairs or build_control_comparison_pairs(groups)
    active_indexes = [index for index, group in enumerate(groups) if group.get("label") != "Total"]
    return [
        {
            "left_index": left_index,
            "right_index": right_index,
            "left_label": normalize_text(groups[left_index].get("label")),
            "right_label": normalize_text(groups[right_index].get("label")),
            "subgroup_label": "Total",
            "overlap": bool((groups[left_index]["mask"] & groups[right_index]["mask"]).sum()),
            "test_type": "paired_overlap"
            if bool((groups[left_index]["mask"] & groups[right_index]["mask"]).sum())
            else "independent",
        }
        for position, left_index in enumerate(active_indexes)
        for right_index in active_indexes[position + 1 :]
    ]


def _build_sig_letters(
    counts_by_group: list[int],
    denominators_by_group: list[int],
    group_labels: list[str],
    alpha: float,
    comparison_scope: str,
    groups: list[dict[str, Any]] | None = None,
    base_masks: list[pd.Series] | None = None,
    outcome_mask: pd.Series | None = None,
    comparison_pairs: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Build significance letters for one row across the visible banner groups."""
    if len(group_labels) <= 1 or comparison_scope == "none":
        return ["" for _ in group_labels]
    output = ["" for _ in group_labels]
    groups = groups or [
        {
            "label": label,
            "mask": pd.Series(dtype=bool),
            "role": "control" if normalize_text(label).lower() == "control" else "test",
        }
        for label in group_labels
    ]
    active_indexes = [index for index, group in enumerate(groups) if group.get("label") != "Total"]
    letters = alpha_letter_sequence(len(active_indexes))
    index_to_letter = {
        actual_index: letters[position]
        for position, actual_index in enumerate(active_indexes)
        if position < len(letters)
    }

    pairs = _infer_comparison_pairs_for_sig(groups, comparison_scope, comparison_pairs)
    p_values: list[float | None] = []
    normalized_pairs: list[dict[str, Any]] = []
    for pair in pairs:
        index_a = int(pair.get("left_index", -1))
        index_b = int(pair.get("right_index", -1))
        if index_a < 0 or index_b < 0 or index_a >= len(group_labels) or index_b >= len(group_labels):
            continue
        if groups[index_a].get("label") == "Total" or groups[index_b].get("label") == "Total":
            continue
        overlaps = bool((groups[index_a]["mask"] & groups[index_b]["mask"]).sum()) if "mask" in groups[index_a] and "mask" in groups[index_b] else False
        p_value = None
        # 2026-05-19 BD: Automatic significance testing switches to an
        # overlap-aware paired proportion test whenever the group masks overlap.
        if overlaps and base_masks is not None and outcome_mask is not None:
            p_value = _overlap_aware_proportion_p_value(
                base_masks[index_a],
                base_masks[index_b],
                outcome_mask,
            )
        else:
            p_value = _pooled_two_sample_z_p_value(
                counts_by_group[index_a],
                denominators_by_group[index_a],
                counts_by_group[index_b],
                denominators_by_group[index_b],
            )
        p_values.append(p_value)
        normalized_pairs.append({**pair, "left_index": index_a, "right_index": index_b, "overlap": overlaps})

    adjusted_values = _holm_adjust_p_values(p_values)
    for pair, adjusted_p in zip(normalized_pairs, adjusted_values):
        if adjusted_p is None or adjusted_p > alpha:
            continue
        index_a = pair["left_index"]
        index_b = pair["right_index"]
        pct_a = (counts_by_group[index_a] / denominators_by_group[index_a]) if denominators_by_group[index_a] else 0.0
        pct_b = (counts_by_group[index_b] / denominators_by_group[index_b]) if denominators_by_group[index_b] else 0.0
        if pct_a > pct_b and index_to_letter.get(index_b):
            output[index_a] += index_to_letter[index_b]
        elif pct_b > pct_a and index_to_letter.get(index_a):
            output[index_b] += index_to_letter[index_a]
    return output


def _build_question_table(
    df: pd.DataFrame,
    question_row: dict[str, Any],
    groups: list[dict[str, Any]],
    net_definitions: dict[str, dict[str, bool]],
    scale_mappings: dict[str, dict[str, Any]],
    alpha: float,
    comparison_scope: str,
    comparison_col: str | None = None,
    comparison_group_labels: dict[str, str] | None = None,
    comparison_pairs: list[dict[str, Any]] | None = None,
    include_percentage: bool = True,
    include_n_count: bool = False,
    include_stat_testing: bool = True,
    notation_location: str = "appended_to_metric",
) -> SheetTable:
    """Build one question table for all visible groups on a banner sheet."""
    variable = normalize_text(question_row.get("variable"))
    display_variable_name = get_display_variable_name(question_row) or variable
    question_label = normalize_text(question_row.get("question_label")) or variable
    question_series = df[variable] if variable in df.columns else pd.Series([None] * len(df), index=df.index)
    output_rows = _get_question_rows(
        variable,
        question_row,
        net_definitions,
        scale_mappings,
        comparison_col=comparison_col,
        comparison_group_labels=comparison_group_labels,
    )

    total_base_denominators = [int(group["mask"].sum()) for group in groups]
    answering_masks = question_series.map(lambda value: normalize_text(value) != "").fillna(False)
    total_answering_denominators = [int((group["mask"] & answering_masks).sum()) for group in groups]
    comparison_pairs = comparison_pairs or _build_comparison_pair_metadata(groups, comparison_col)

    sections: list[dict[str, Any]] = []
    for section_label, denominators, base_masks in [
        ("Total Base", total_base_denominators, [group["mask"] for group in groups]),
        ("Total Answering", total_answering_denominators, [group["mask"] & answering_masks for group in groups]),
    ]:
        rows: list[dict[str, Any]] = []
        for output_row in output_rows:
            counts_by_group: list[int] = []
            percentages_by_group: list[float | None] = []
            if output_row.get("match_mode") == "not_selected":
                matched_mask = question_series.map(
                    lambda value: not any(
                        _value_matches_selected_choices(value, [choice])
                        for choice in output_row["choices"]
                    )
                ).fillna(False)
            else:
                matched_mask = question_series.map(
                    lambda value: any(
                        _value_matches_selected_choices(value, [choice])
                        for choice in output_row["choices"]
                    )
                ).fillna(False)
            for group_mask, denominator in zip(base_masks, denominators):
                numerator = int((group_mask & matched_mask).sum())
                counts_by_group.append(numerator)
                percentages_by_group.append((numerator / denominator) if denominator else None)
            sig_letters = _build_sig_letters(
                counts_by_group,
                denominators,
                [group["label"] for group in groups],
                alpha,
                comparison_scope,
                groups=groups,
                base_masks=base_masks,
                outcome_mask=matched_mask,
                comparison_pairs=comparison_pairs,
            )
            rows.append(
                {
                    "label": output_row["label"],
                    "source_label": output_row.get("source_label", output_row["label"]),
                    "kind": output_row["kind"],
                    "counts": counts_by_group,
                    "percentages": percentages_by_group,
                    "sig_letters": sig_letters,
                }
            )
        sections.append(
            {
                "label": section_label,
                "base_denominators": denominators,
                "rows": rows,
            }
        )

    return SheetTable(
        variable=variable,
        display_variable_name=display_variable_name,
        question_label=question_label,
        sections=sections,
        groups=groups,
        comparison_pairs=comparison_pairs,
        include_percentage=include_percentage,
        include_n_count=include_n_count,
        include_stat_testing=include_stat_testing and comparison_scope != "none",
        notation_location=notation_location,
    )


def _find_comparison_pair_indexes(
    groups: list[dict[str, Any]],
    comparison_col: str | None,
) -> list[tuple[int, int, str, str, str]]:
    """Find comparison-group pairs for topline comparisons.

    Inputs:
        groups: Banner groups already built for one sheet.
        comparison_col: The configured comparison variable, usually `cell`.

    Outputs:
        A list of `(left_index, right_index, subgroup_label, left_label,
        right_label)` tuples. The subgroup label describes the non-comparison
        part of the banner path so notes can read like `test females sig
        higher than control females`.
    """
    return [
        (
            pair["left_index"],
            pair["right_index"],
            pair["subgroup_label"],
            pair["left_label"],
            pair["right_label"],
        )
        for pair in _build_comparison_pair_metadata(groups, comparison_col)
    ]


def _build_comparison_pair_metadata(
    groups: list[dict[str, Any]],
    comparison_col: str | None,
) -> list[dict[str, Any]]:
    """Find Control-vs-group comparison pairs for total or nested banners."""
    normalized_comparison = normalize_text(comparison_col)
    if not normalized_comparison:
        return build_control_comparison_pairs(groups)

    group_lookup: dict[tuple[tuple[str, str], ...], dict[str, dict[str, Any]]] = {}
    for index, group in enumerate(groups):
        if group.get("label") == "Total":
            continue
        values = {
            normalize_text(key): normalize_text(value)
            for key, value in group.get("values", {}).items()
            if normalize_text(key)
        }
        display_values = {
            normalize_text(key): normalize_text(value)
            for key, value in group.get("display_values", {}).items()
            if normalize_text(key)
        }
        if normalized_comparison not in values:
            continue
        comparison_value = normalize_text(values.pop(normalized_comparison)).lower()
        comparison_display = display_values.get(normalized_comparison) or normalize_text(
            group.get("label", "")
        )
        subgroup_pairs = []
        for key, value in values.items():
            subgroup_pairs.append((key, display_values.get(key) or value))
        subgroup_key = tuple(sorted(subgroup_pairs))
        group_lookup.setdefault(subgroup_key, {})[comparison_value] = {
            "index": index,
            "label": comparison_display,
            "label_key": normalize_text(comparison_display).lower(),
            "role": normalize_text(group.get("role")).lower(),
            "mask": group.get("mask"),
        }

    pairs: list[dict[str, Any]] = []
    for subgroup_key, indexed_values in group_lookup.items():
        ordered_values = list(indexed_values.keys())
        if len(ordered_values) < 2:
            continue
        subgroup_label = "Total"
        if subgroup_key:
            subgroup_label = " | ".join(value for _, value in subgroup_key)
        control_key = next(
            (
                value
                for value in ordered_values
                if indexed_values[value].get("role") == "control"
                or indexed_values[value].get("label_key") == "control"
            ),
            None,
        )
        if control_key:
            left_record = indexed_values[control_key]
            for value in ordered_values:
                if value == control_key:
                    continue
                right_record = indexed_values[value]
                overlap = bool((left_record["mask"] & right_record["mask"]).sum()) if left_record.get("mask") is not None and right_record.get("mask") is not None else False
                pairs.append(
                    {
                        "left_index": left_record["index"],
                        "right_index": right_record["index"],
                        "subgroup_label": subgroup_label,
                        "left_label": left_record["label"],
                        "right_label": right_record["label"],
                        "overlap": overlap,
                        "test_type": "paired_overlap" if overlap else "independent",
                        "parent_key": subgroup_key,
                    }
                )
            continue
    return pairs


def _build_significance_direction(
    sig_letters: list[str],
    left_index: int,
    right_index: int,
    active_comparison_indexes: list[int] | None = None,
) -> str:
    """Return which side is significantly higher for one comparison pair.

    Inputs:
        sig_letters: Significance-letter outputs for one response row.
        left_index: Column index for the left comparison group.
        right_index: Column index for the right comparison group.

    Outputs:
        Returns `right`, `left`, or an empty string when there is no
        significant difference between the pair.
    """
    right_sig = normalize_text(sig_letters[right_index]) if right_index < len(sig_letters) else ""
    left_sig = normalize_text(sig_letters[left_index]) if left_index < len(sig_letters) else ""
    active_comparison_indexes = active_comparison_indexes or list(range(len(sig_letters)))
    pair_letters = alpha_letter_sequence(len(active_comparison_indexes))
    index_to_letter = {
        actual_index: pair_letters[position]
        for position, actual_index in enumerate(active_comparison_indexes)
        if position < len(pair_letters)
    }
    left_letter = index_to_letter.get(left_index, "")
    right_letter = index_to_letter.get(right_index, "")
    if right_letter and right_letter in left_sig:
        return "left"
    if left_letter and left_letter in right_sig:
        return "right"
    return ""


def _build_topline_note(
    subgroup_label: str,
    left_label: str,
    right_label: str,
    left_pct: float,
    right_pct: float,
    significant_direction: str,
) -> str:
    """Build one plain-English topline note.

    Inputs:
        subgroup_label: Lowest-level banner subgroup label.
        left_label: Left comparison-group label.
        right_label: Right comparison-group label.
        left_pct: Left-group percentage stored as a decimal.
        right_pct: Right-group percentage stored as a decimal.
        significant_direction: Either `right`, `left`, or blank.

    Outputs:
        A short note that reads like an analyst summary.
    """
    if significant_direction not in {"right", "left"}:
        return ""
    subgroup_suffix = ""
    if subgroup_label and subgroup_label != "Total":
        subgroup_suffix = f" {subgroup_label}"
    lift_points = round((right_pct - left_pct) * 100)
    return (
        f"{right_label}{subgroup_suffix} sig "
        f"{'higher' if significant_direction == 'right' else 'lower'} than "
        f"{left_label}{subgroup_suffix} "
        f"({right_pct:.0%}, {lift_points:+d} pts lift)"
    )


def _build_topline_pair_key(left_label: str, right_label: str) -> str:
    """Return a stable key for Control-vs-group topline notes."""
    return f"{normalize_text(left_label).casefold()}||{normalize_text(right_label).casefold()}"


def _build_banner_note_lookup(
    sheets: list[WorkbookSheet],
    comparison_col: str | None,
    note_base_section_map: dict[str, str] | None = None,
) -> dict[tuple[str, str], dict[str, list[str]]]:
    """Collect banner-level significance notes for each question response.

    Inputs:
        sheets: Banner sheets already prepared for workbook export.
        comparison_col: The chosen comparison variable, usually `cell`.

    Outputs:
        A mapping keyed by `(variable, response_label)` and then comparison
        pair so the topline export can keep each comparison's notes separate.
    """
    note_lookup: dict[tuple[str, str], dict[str, list[str]]] = {}
    note_base_section_map = note_base_section_map or {}
    normalized_comparison = normalize_text(comparison_col)
    if not normalized_comparison:
        return note_lookup
    for sheet in sheets:
        for table in sheet.tables:
            table_groups = list(getattr(table, "groups", []) or sheet.groups)
            table_levels = list(getattr(table, "levels", []) or sheet.levels)
            if not table_levels or not table_groups:
                continue
            # 2026-05-19 BD: Topline notes should come only from true banner
            # breakouts: at least one parent level, with comparison as the
            # lowest level. One-level comparison tables already show lifts in
            # the topline metrics and should not restate them as notes.
            if len(table_levels) < 2:
                continue
            if normalize_text(table_levels[-1]) != normalized_comparison:
                continue
            comparison_pairs = _find_comparison_pair_indexes(table_groups, comparison_col)
            if not comparison_pairs:
                continue
            normalized_variable = normalize_text(table.variable)
            section_label = note_base_section_map.get(normalized_variable, "Total Answering")
            if section_label == "Total Sample":
                section_label = "Total Base"
            note_source_section = next(
                (section for section in table.sections if section.get("label") == section_label),
                None,
            )
            if not note_source_section:
                continue
            for row in note_source_section.get("rows", []):
                # 2026-05-19 BD: Keep banner-derived topline notes split by
                # Control-vs-group pair for the interleaved topline layout.
                row_notes_by_pair: dict[str, list[str]] = {}
                row_directions: list[str] = []
                active_comparison_indexes = [
                    index
                    for index, group in enumerate(table_groups)
                    if group.get("label") != "Total"
                ]
                for left_index, right_index, subgroup_label, left_label, right_label in comparison_pairs:
                    left_pct = row["percentages"][left_index] or 0.0
                    right_pct = row["percentages"][right_index] or 0.0
                    significant_direction = _build_significance_direction(
                        row["sig_letters"],
                        left_index,
                        right_index,
                        active_comparison_indexes=active_comparison_indexes,
                    )
                    if significant_direction:
                        significant_direction = "right" if right_pct > left_pct else "left"
                    note = _build_topline_note(
                        subgroup_label,
                        left_label,
                        right_label,
                        left_pct,
                        right_pct,
                        significant_direction,
                    )
                    if not note:
                        continue
                    pair_key = _build_topline_pair_key(left_label, right_label)
                    row_notes_by_pair.setdefault(pair_key, []).append(note)
                    row_directions.append(significant_direction)
                # If every subgroup on this banner tells the same directional story,
                # suppress subgroup notes and let the topline carry the total-sample read.
                if (
                    row_notes_by_pair
                    and len(row_directions) == len(comparison_pairs)
                    and len(set(row_directions)) == 1
                    and len(row_directions) > 1
                ):
                    continue
                key = (table.variable, row["label"])
                note_lookup.setdefault(key, {})
                for pair_key, notes in row_notes_by_pair.items():
                    note_lookup[key].setdefault(pair_key, [])
                    for note in notes:
                        if note not in note_lookup[key][pair_key]:
                            note_lookup[key][pair_key].append(note)
    return note_lookup


def _build_topline_rows(
    total_comparison_sheet: WorkbookSheet | None,
    banner_sheets: list[WorkbookSheet],
    comparison_col: str | None,
    include_lift: bool,
    include_significance_notes: bool,
    included_variables: set[str] | None = None,
    response_selection_map: dict[str, list[str]] | None = None,
    note_base_section_map: dict[str, str] | None = None,
    variable_display_names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Flatten banner comparisons into one topline sheet.

    Inputs:
        total_comparison_sheet: The one total-level comparison sheet used for
            the topline grid itself.
        banner_sheets: Banner sheets used only to derive subgroup-level notes.
        comparison_col: The selected comparison variable, usually `cell`.
        include_lift: Whether the topline sheet should show lift values.
        include_significance_notes: Whether the topline sheet should include
            analyst-style notes for significant differences.

    Outputs:
        A list of flat topline rows. Each row describes one question response
        on the total sample for control vs test, plus optional banner-derived
        notes.
    """
    rows: list[dict[str, Any]] = []
    if not total_comparison_sheet:
        return rows

    included_variables = included_variables or set()
    response_selection_map = response_selection_map or {}
    note_base_section_map = note_base_section_map or {}
    variable_display_names = variable_display_names or {}
    note_lookup = _build_banner_note_lookup(banner_sheets, comparison_col, note_base_section_map)
    if len(total_comparison_sheet.groups) < 1:
        return rows
    comparison_pairs = list(getattr(total_comparison_sheet, "comparison_pairs", []) or [])
    if not comparison_pairs:
        comparison_pairs = _build_comparison_pair_metadata(total_comparison_sheet.groups, comparison_col)
    active_topline_indexes = [
        index
        for index, group in enumerate(total_comparison_sheet.groups)
        if group.get("label") != "Total"
    ]
    if not active_topline_indexes:
        return rows
    left_index = comparison_pairs[0]["left_index"] if comparison_pairs else active_topline_indexes[0]
    right_index = comparison_pairs[0]["right_index"] if comparison_pairs else active_topline_indexes[min(1, len(active_topline_indexes) - 1)]
    left_group_label = normalize_text(total_comparison_sheet.groups[left_index].get("label")) or "Group 1"
    right_group_label = normalize_text(total_comparison_sheet.groups[right_index].get("label")) or "Group 2"
    for table in total_comparison_sheet.tables:
        normalized_variable = normalize_text(table.variable)
        if included_variables and normalized_variable not in included_variables:
            continue
        selected_note_base = note_base_section_map.get(normalized_variable) or "Total Answering"
        metric_section_label = "Total Base" if selected_note_base == "Total Sample" else "Total Answering"
        metric_section = next(
            (section for section in table.sections if section.get("label") == metric_section_label),
            None,
        )
        if not metric_section:
            continue
        # 2026-05-15 BD: Topline export labels use the displayed variable name,
        # while filtering and response matching continue to use the raw variable key.
        display_variable_name = normalize_text(getattr(table, "display_variable_name", "")) or variable_display_names.get(normalized_variable, normalized_variable)
        base_denominators = list(metric_section.get("base_denominators", []))
        for row in metric_section.get("rows", []):
            has_saved_selection = normalized_variable in response_selection_map
            allowed_responses = response_selection_map.get(normalized_variable, [])
            normalized_allowed = {normalize_text(value) for value in allowed_responses}
            if has_saved_selection and not (
                normalize_text(row["label"]) in normalized_allowed
                or normalize_text(row.get("source_label")) in normalized_allowed
            ):
                continue
            left_n = row["counts"][left_index]
            right_n = row["counts"][right_index]
            left_pct = row["percentages"][left_index] or 0.0
            right_pct = row["percentages"][right_index] or 0.0
            significant_direction = (
                _build_significance_direction(
                    row["sig_letters"],
                    left_index,
                    right_index,
                    active_comparison_indexes=active_topline_indexes,
                )
                if comparison_pairs
                else ""
            )
            if significant_direction:
                significant_direction = "right" if right_pct > left_pct else "left"
            group_results = []
            for group_index in active_topline_indexes:
                group_results.append(
                    {
                        "index": group_index,
                        "label": normalize_text(total_comparison_sheet.groups[group_index].get("label")),
                        "base": base_denominators[group_index] if group_index < len(base_denominators) else None,
                        "n": row["counts"][group_index] if group_index < len(row["counts"]) else None,
                        "pct": row["percentages"][group_index] if group_index < len(row["percentages"]) else None,
                        "sig": row["sig_letters"][group_index] if group_index < len(row["sig_letters"]) else "",
                    }
                )
            pair_results = []
            # 2026-05-19 BD: Pair-specific note buckets let the Excel topline
            # show one notes column per Control-vs-group comparison.
            pair_notes: dict[str, list[str]] = {}
            for pair in comparison_pairs:
                pair_left_index = pair["left_index"]
                pair_right_index = pair["right_index"]
                pair_left_pct = row["percentages"][pair_left_index] or 0.0
                pair_right_pct = row["percentages"][pair_right_index] or 0.0
                pair_direction = _build_significance_direction(
                    row["sig_letters"],
                    pair_left_index,
                    pair_right_index,
                    active_comparison_indexes=active_topline_indexes,
                )
                if pair_direction:
                    pair_direction = "right" if pair_right_pct > pair_left_pct else "left"
                pair_left_label = pair.get("left_label") or total_comparison_sheet.groups[pair_left_index].get("label")
                pair_right_label = pair.get("right_label") or total_comparison_sheet.groups[pair_right_index].get("label")
                pair_key = _build_topline_pair_key(pair_left_label, pair_right_label)
                pair_results.append(
                    {
                        "left_index": pair_left_index,
                        "right_index": pair_right_index,
                        "left_label": pair_left_label,
                        "right_label": pair_right_label,
                        "note_key": pair_key,
                        "left_pct": pair_left_pct,
                        "right_pct": pair_right_pct,
                        "lift": (pair_right_pct - pair_left_pct) if include_lift else None,
                        "sig_direction": pair_direction,
                        "test_type": pair.get("test_type", "paired_overlap" if pair.get("overlap") else "independent"),
                    }
                )
            if include_significance_notes:
                # 2026-05-19 BD: Do not create notes from the topline
                # comparison itself. Notes are reserved for eligible banner
                # subgroups where comparison is the lowest banner level.
                for pair_key, banner_notes in note_lookup.get((table.variable, row["label"]), {}).items():
                    pair_notes.setdefault(pair_key, [])
                    for note in banner_notes:
                        if note not in pair_notes[pair_key]:
                            pair_notes[pair_key].append(note)
            pair_note_text = {
                pair_key: "\n".join(dict.fromkeys(notes))
                for pair_key, notes in pair_notes.items()
                if notes
            }
            note_text = "\n".join(
                dict.fromkeys(
                    note
                    for notes in pair_note_text.values()
                    for note in notes.split("\n")
                    if note
                )
            )

            rows.append(
                {
                    "Topline Label": display_variable_name or table.question_label,
                    "Question": table.question_label,
                    "Variable": table.variable,
                    "Response": row["label"],
                    "Comparison Variable": (
                        COMPARISON_SCHEME_DISPLAY_NAME
                        if normalize_text(comparison_col) == COMPARISON_SCHEME_LEVEL
                        else variable_display_names.get(normalize_text(comparison_col), normalize_text(comparison_col)) or "Comparison"
                    ),
                    "Left Label": left_group_label,
                    "Left Base": base_denominators[left_index],
                    "Left N": left_n,
                    "Left %": left_pct,
                    "Left Sig": row["sig_letters"][left_index],
                    "Right Label": right_group_label,
                    "Right Base": base_denominators[right_index],
                    "Right N": right_n,
                    "Right %": right_pct,
                    "Right Sig": row["sig_letters"][right_index],
                    "Lift": (right_pct - left_pct) if include_lift else None,
                    "Sig Test": significant_direction,
                    "Group Results": group_results,
                    "Comparison Pairs": pair_results,
                    "Pair Notes": pair_note_text,
                    "Notes": note_text,
                    "Note Base": selected_note_base,
                }
            )
    return rows


def generate_workbook_package(
    cleaned_df: pd.DataFrame,
    question_metadata: list[dict[str, Any]],
    custom_variables: list[dict[str, Any]],
    banner_config: dict[str, Any],
    adhoc_crosstabs_config: dict[str, Any],
    net_definitions: dict[str, dict[str, bool]],
    scale_mappings: dict[str, dict[str, Any]],
    banner_stat_config: dict[str, Any],
    adhoc_stat_config: dict[str, Any],
    comparison_col: str | None,
    comparison_group_order: dict[str, int],
    comparison_group_labels: dict[str, str],
    comparison_scheme: dict[str, Any] | None = None,
    global_filters: dict[str, Any] | None = None,
    weighting_config: dict[str, Any] | None = None,
    topline_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the full workbook package used by the export layer.

    Inputs:
        Current cleaned respondent dataset and all saved project setup choices.

    Outputs:
        A workbook package containing one sheet per banner and one table per
        question. Each question includes Total Base and Total Answering
        sections with N, %, and significance letters.
    """
    question_lookup = build_question_lookup(question_metadata, net_definitions, scale_mappings)
    variable_display_names = build_display_variable_lookup(question_metadata)
    for record in custom_variables:
        custom_name = normalize_text(record.get("name"))
        if custom_name:
            variable_display_names[custom_name] = custom_name
    analysis_df = _materialize_custom_variables(cleaned_df, custom_variables, question_lookup)
    global_filters = global_filters or {"rows": []}
    weighting_config = weighting_config or {"weights": []}
    topline_config = topline_config or {}
    # 2026-05-19 BD: A saved comparison_scheme replaces the old binary
    # comparison assumption with rule-defined layered groups.
    comparison_scheme = sanitize_comparison_scheme(comparison_scheme)
    layered_scheme_active = is_layered_comparison_scheme(comparison_scheme)
    effective_comparison_col = _comparison_level_key(comparison_col, layered_scheme_active)
    project_comparison_groups = build_comparison_group_masks(
        analysis_df,
        comparison_scheme if layered_scheme_active else None,
        question_lookup,
        comparison_col,
        comparison_group_order,
        comparison_group_labels,
    )
    project_has_overlaps = bool(detect_group_overlaps(project_comparison_groups)) if layered_scheme_active else False
    adhoc_response_selection_map = {
        normalize_text(variable): [
            normalize_text(choice)
            for choice in choices
            if normalize_text(choice)
        ]
        for variable, choices in topline_config.get("response_selections", {}).items()
        if normalize_text(variable)
    }

    enabled_questions = [
        row
        for row in question_metadata
        if bool(row.get("include", True))
        and normalize_text(row.get("detected_type")) not in {"Ignore", "Open-End Text"}
        and normalize_text(row.get("variable")) in analysis_df.columns
    ]

    banner_rows = _normalize_banner_rows(banner_config, variable_display_names)
    include_total = bool(banner_config.get("include_total", True))
    banner_confidence_intervals = normalize_confidence_intervals(banner_stat_config.get("confidence_intervals", [95]))
    banner_alpha = (100 - banner_confidence_intervals[0]) / 100 if banner_confidence_intervals else 0.05
    banner_include_percentage = _include_percentage(banner_stat_config)
    banner_include_n_count = bool(banner_stat_config.get("include_n_count", False))
    banner_include_stat_testing = _include_stat_testing(banner_stat_config)
    banner_notation_location = _notation_location(banner_stat_config)
    banner_comparison_scope = _effective_comparison_scope(banner_stat_config)
    topline_scope = (
        _topline_comparison_scope(topline_config, banner_comparison_scope, project_comparison_groups)
        if banner_include_stat_testing
        else "none"
    )

    sheet_specs: list[WorkbookSheet] = []
    total_comparison_sheet: WorkbookSheet | None = None
    if not banner_rows:
        if layered_scheme_active:
            groups = _build_layered_banner_groups(
                analysis_df,
                None,
                True,
                project_comparison_groups,
                comparison_col,
                question_lookup,
                custom_variables,
                comparison_group_order,
            )
            sheet_levels = [effective_comparison_col]
            comparison_pairs = _build_comparison_pair_metadata(groups, effective_comparison_col)
            table_comparison_scope = _comparison_scope_for_groups(banner_comparison_scope, groups) if banner_include_stat_testing else "none"
        else:
            groups = _build_banner_groups(
                analysis_df,
                None,
                True,
                question_lookup,
                custom_variables,
                comparison_col,
                comparison_group_order,
                comparison_group_labels,
            )
            sheet_levels = []
            comparison_pairs = _build_comparison_pair_metadata(groups, comparison_col)
            table_comparison_scope = _comparison_scope_for_groups(banner_comparison_scope, groups)
        tables = [
            _build_question_table(
                analysis_df,
                question_row,
                groups,
                net_definitions,
                scale_mappings,
                banner_alpha,
                table_comparison_scope,
                effective_comparison_col if layered_scheme_active else comparison_col,
                comparison_group_labels,
                comparison_pairs,
                include_percentage=banner_include_percentage,
                include_n_count=banner_include_n_count,
                include_stat_testing=banner_include_stat_testing,
                notation_location=banner_notation_location,
            )
            for question_row in enabled_questions
        ]
        only_sheet = WorkbookSheet(
            name="All Tables",
            banner_name="All Tables",
            levels=sheet_levels,
            groups=groups,
            tables=tables,
            comparison_pairs=comparison_pairs,
            footnotes=_build_table_footnotes(
                banner_stat_config,
                [],
                _resolve_weighting_footnotes(weighting_config, ["All Tables"]),
                layered_scheme_active,
                project_has_overlaps,
                comparison_scope_override=table_comparison_scope,
            ),
            include_percentage=banner_include_percentage,
            include_n_count=banner_include_n_count,
            include_stat_testing=banner_include_stat_testing,
            notation_location=banner_notation_location,
        )
        sheet_specs.append(only_sheet)
        total_comparison_sheet = only_sheet
        topline_table_scope = _comparison_scope_for_groups(topline_scope, groups) if banner_include_stat_testing else "none"
        if topline_table_scope != table_comparison_scope:
            total_tables = [
                _build_question_table(
                    analysis_df,
                    question_row,
                    groups,
                    net_definitions,
                    scale_mappings,
                    banner_alpha,
                    topline_table_scope,
                    effective_comparison_col if layered_scheme_active else comparison_col,
                    comparison_group_labels,
                    comparison_pairs,
                    include_percentage=banner_include_percentage,
                    include_n_count=banner_include_n_count,
                    include_stat_testing=banner_include_stat_testing,
                    notation_location=banner_notation_location,
                )
                for question_row in enabled_questions
            ]
            total_comparison_sheet = WorkbookSheet(
                name="Topline Comparison",
                banner_name="Topline Comparison",
                levels=sheet_levels,
                groups=groups,
                tables=total_tables,
                comparison_pairs=comparison_pairs,
                footnotes=_build_table_footnotes(
                    banner_stat_config,
                    [],
                    [],
                    layered_scheme_active,
                    project_has_overlaps,
                    comparison_scope_override=topline_table_scope,
                ),
                include_percentage=banner_include_percentage,
                include_n_count=banner_include_n_count,
                include_stat_testing=banner_include_stat_testing,
                notation_location=banner_notation_location,
            )
    else:
        if layered_scheme_active and project_comparison_groups:
            total_groups = project_comparison_groups
            total_pairs = build_control_comparison_pairs(total_groups)
            total_scope = _comparison_scope_for_groups(topline_scope, total_groups) if banner_include_stat_testing else "none"
            total_tables = [
                _build_question_table(
                    analysis_df,
                    question_row,
                    total_groups,
                    net_definitions,
                    scale_mappings,
                    banner_alpha,
                    total_scope,
                    effective_comparison_col,
                    comparison_group_labels,
                    total_pairs,
                    include_percentage=banner_include_percentage,
                    include_n_count=banner_include_n_count,
                    include_stat_testing=banner_include_stat_testing,
                    notation_location=banner_notation_location,
                )
                for question_row in enabled_questions
            ]
            total_comparison_sheet = WorkbookSheet(
                name="Topline Comparison",
                banner_name="Topline Comparison",
                levels=[effective_comparison_col],
                groups=total_groups,
                tables=total_tables,
                comparison_pairs=total_pairs,
                footnotes=_build_table_footnotes(
                    banner_stat_config,
                    [],
                    [],
                    layered_scheme_active,
                    project_has_overlaps,
                    comparison_scope_override=total_scope,
                ),
                include_percentage=banner_include_percentage,
                include_n_count=banner_include_n_count,
                include_stat_testing=banner_include_stat_testing,
                notation_location=banner_notation_location,
            )
        elif comparison_col and normalize_text(comparison_col) in analysis_df.columns:
            total_groups = _build_total_comparison_groups(
                analysis_df,
                comparison_col,
                comparison_group_order,
                comparison_group_labels,
            )
            total_pairs = _build_comparison_pair_metadata(total_groups, comparison_col)
            total_scope = _comparison_scope_for_groups(topline_scope, total_groups) if banner_include_stat_testing else "none"
            total_tables = [
                _build_question_table(
                    analysis_df,
                    question_row,
                    total_groups,
                    net_definitions,
                    scale_mappings,
                    banner_alpha,
                    total_scope,
                    comparison_col,
                    comparison_group_labels,
                    total_pairs,
                    include_percentage=banner_include_percentage,
                    include_n_count=banner_include_n_count,
                    include_stat_testing=banner_include_stat_testing,
                    notation_location=banner_notation_location,
                )
                for question_row in enabled_questions
            ]
            total_comparison_sheet = WorkbookSheet(
                name="Topline Comparison",
                banner_name="Topline Comparison",
                levels=[comparison_col],
                groups=total_groups,
                tables=total_tables,
                comparison_pairs=total_pairs,
                include_percentage=banner_include_percentage,
                include_n_count=banner_include_n_count,
                include_stat_testing=banner_include_stat_testing,
                notation_location=banner_notation_location,
            )
        for banner_row in banner_rows:
            banner_name = banner_row["name"]
            filtered_banner_df, applied_filters = _apply_targeted_filters(
                analysis_df,
                global_filters,
                ["All Tables", banner_name],
                question_lookup,
            )
            if layered_scheme_active:
                filtered_comparison_groups = build_comparison_group_masks(
                    filtered_banner_df,
                    comparison_scheme,
                    question_lookup,
                    comparison_col,
                    comparison_group_order,
                    comparison_group_labels,
                )
                groups = _build_layered_banner_groups(
                    filtered_banner_df,
                    banner_row,
                    include_total,
                    filtered_comparison_groups,
                    comparison_col,
                    question_lookup,
                    custom_variables,
                    comparison_group_order,
                )
                active_levels = _layered_banner_levels(banner_row, comparison_col)
                comparison_pairs = _build_comparison_pair_metadata(groups, effective_comparison_col)
                table_comparison_scope = _comparison_scope_for_groups(banner_comparison_scope, groups) if banner_include_stat_testing else "none"
                sheet_has_overlaps = bool(detect_group_overlaps(filtered_comparison_groups))
            else:
                groups = _build_banner_groups(
                    filtered_banner_df,
                    banner_row,
                    include_total,
                    question_lookup,
                    custom_variables,
                    comparison_col,
                    comparison_group_order,
                    comparison_group_labels,
                )
                active_levels = banner_row["levels"]
                comparison_pairs = _build_comparison_pair_metadata(groups, comparison_col)
                table_comparison_scope = _comparison_scope_for_groups(banner_comparison_scope, groups)
                sheet_has_overlaps = False
            tables = [
                _build_question_table(
                    filtered_banner_df,
                    question_row,
                    groups,
                    net_definitions,
                    scale_mappings,
                    banner_alpha,
                    table_comparison_scope,
                    effective_comparison_col if layered_scheme_active else comparison_col,
                    comparison_group_labels,
                    comparison_pairs,
                    include_percentage=banner_include_percentage,
                    include_n_count=banner_include_n_count,
                    include_stat_testing=banner_include_stat_testing,
                    notation_location=banner_notation_location,
                )
                for question_row in enabled_questions
            ]
            banner_footnotes = _build_table_footnotes(
                banner_stat_config,
                applied_filters,
                _resolve_weighting_footnotes(weighting_config, ["All Tables", banner_name]),
                layered_scheme_active,
                sheet_has_overlaps,
                comparison_scope_override=table_comparison_scope,
            )
            if banner_config.get("export_style") == "single_sheet":
                if not sheet_specs or sheet_specs[-1].name != "All Banners":
                    sheet_specs.append(
                        WorkbookSheet(
                            name="All Banners",
                            banner_name="All Banners",
                            levels=[],
                            groups=[],
                            tables=[],
                            footnotes=[],
                            include_percentage=banner_include_percentage,
                            include_n_count=banner_include_n_count,
                            include_stat_testing=banner_include_stat_testing,
                            notation_location=banner_notation_location,
                        )
                    )
                for table in tables:
                    table.banner_name = banner_name
                    table.levels = list(active_levels)
                    table.level_labels = {
                        **dict(banner_row.get("level_labels", {})),
                        effective_comparison_col: COMPARISON_SCHEME_DISPLAY_NAME,
                    }
                    table.groups = groups
                    table.comparison_pairs = comparison_pairs
                    table.footnotes = banner_footnotes
                sheet_specs[-1].tables.extend(tables)
            else:
                sheet_specs.append(
                    WorkbookSheet(
                        name=banner_name,
                        banner_name=banner_name,
                        levels=active_levels,
                        level_labels={
                            **dict(banner_row.get("level_labels", {})),
                            effective_comparison_col: COMPARISON_SCHEME_DISPLAY_NAME,
                        },
                        groups=groups,
                        tables=tables,
                        comparison_pairs=comparison_pairs,
                        footnotes=banner_footnotes,
                        include_percentage=banner_include_percentage,
                        include_n_count=banner_include_n_count,
                        include_stat_testing=banner_include_stat_testing,
                        notation_location=banner_notation_location,
                    )
                )

    adhoc_tables = []
    adhoc_config_rows = list((adhoc_crosstabs_config or {}).get("tables", []))
    if adhoc_config_rows:
        adhoc_ci = normalize_confidence_intervals(adhoc_stat_config.get("confidence_intervals", [95]))
        adhoc_alpha = (100 - adhoc_ci[0]) / 100 if adhoc_ci else 0.05
        adhoc_include_percentage = _include_percentage(adhoc_stat_config)
        adhoc_include_n_count = bool(adhoc_stat_config.get("include_n_count", False))
        adhoc_include_stat_testing = _include_stat_testing(adhoc_stat_config)
        adhoc_notation_location = _notation_location(adhoc_stat_config)
        adhoc_scope = _effective_comparison_scope(adhoc_stat_config)
        metadata_lookup = {
            normalize_text(row.get("variable")): row for row in enabled_questions
        }
        for row in adhoc_config_rows:
            row_variable = normalize_text(row.get("row_variable") or row.get("variable"))
            column_variable = normalize_text(row.get("column_variable") or row.get("banner"))
            table_name = normalize_text(row.get("name")) or variable_display_names.get(row_variable, row_variable)
            question_row = metadata_lookup.get(row_variable) or _build_custom_variable_question_row(
                row_variable,
                custom_variables,
            )
            column_uses_comparison_scheme = layered_scheme_active and normalize_text(column_variable) == COMPARISON_SCHEME_LEVEL
            if (
                not row_variable
                or not column_variable
                or not question_row
                or (column_variable not in analysis_df.columns and not column_uses_comparison_scheme)
            ):
                continue
            question_row = _apply_selected_response_filter(
                question_row,
                adhoc_response_selection_map.get(row_variable, []),
            )
            filtered_df, applied_filters = _apply_targeted_filters(
                analysis_df,
                global_filters,
                ["All Tables", table_name],
                question_lookup,
            )
            column_question_row = metadata_lookup.get(column_variable)
            if layered_scheme_active and normalize_text(column_variable) in {normalize_text(comparison_col), COMPARISON_SCHEME_LEVEL}:
                filtered_comparison_groups = build_comparison_group_masks(
                    filtered_df,
                    comparison_scheme,
                    question_lookup,
                    comparison_col,
                    comparison_group_order,
                    comparison_group_labels,
                )
                groups = _build_layered_banner_groups(
                    filtered_df,
                    {"name": table_name, "levels": [column_variable]},
                    include_total,
                    filtered_comparison_groups,
                    comparison_col,
                    question_lookup,
                    custom_variables,
                    comparison_group_order,
                )
                column_levels = [effective_comparison_col]
                comparison_pairs = _build_comparison_pair_metadata(groups, effective_comparison_col)
                adhoc_scope_for_table = _comparison_scope_for_groups(adhoc_scope, groups) if adhoc_include_stat_testing else "none"
                adhoc_has_overlaps = bool(detect_group_overlaps(filtered_comparison_groups))
            elif normalize_text(column_question_row.get("detected_type") if column_question_row else "") == "Multi-Select":
                groups = _build_adhoc_multiselect_groups(
                    filtered_df,
                    column_variable,
                    include_total,
                    question_lookup,
                    comparison_col,
                    comparison_group_labels,
                )
                column_levels = [column_variable, "__selection_status__"]
                comparison_pairs = _build_comparison_pair_metadata(groups, comparison_col)
                adhoc_scope_for_table = _comparison_scope_for_groups(adhoc_scope, groups)
                adhoc_has_overlaps = False
            else:
                banner_row = {
                    "name": table_name,
                    "levels": [column_variable],
                }
                groups = _build_banner_groups(
                    filtered_df,
                    banner_row,
                    include_total,
                    question_lookup,
                    custom_variables,
                    comparison_col,
                    comparison_group_order,
                    comparison_group_labels,
                )
                column_levels = [column_variable]
                comparison_pairs = _build_comparison_pair_metadata(groups, comparison_col)
                adhoc_scope_for_table = _comparison_scope_for_groups(adhoc_scope, groups)
                adhoc_has_overlaps = False
            table = _build_question_table(
                filtered_df,
                question_row,
                groups,
                net_definitions,
                scale_mappings,
                adhoc_alpha,
                adhoc_scope_for_table,
                effective_comparison_col if layered_scheme_active and normalize_text(column_variable) in {normalize_text(comparison_col), COMPARISON_SCHEME_LEVEL} else comparison_col,
                comparison_group_labels,
                comparison_pairs,
                include_percentage=adhoc_include_percentage,
                include_n_count=adhoc_include_n_count,
                include_stat_testing=adhoc_include_stat_testing,
                notation_location=adhoc_notation_location,
            )
            table.banner_name = table_name
            table.levels = column_levels
            table.level_labels = {
                column_variable: variable_display_names.get(column_variable, column_variable),
                "__selection_status__": "Selection Status",
                effective_comparison_col: COMPARISON_SCHEME_DISPLAY_NAME,
            }
            table.groups = groups
            table.comparison_pairs = comparison_pairs
            table.footnotes = _build_table_footnotes(
                adhoc_stat_config,
                applied_filters,
                _resolve_weighting_footnotes(weighting_config, ["All Tables", table_name]),
                layered_scheme_active and normalize_text(column_variable) in {normalize_text(comparison_col), COMPARISON_SCHEME_LEVEL},
                adhoc_has_overlaps,
                comparison_scope_override=adhoc_scope_for_table,
            )
            adhoc_tables.append(table)
        if adhoc_tables:
            sheet_specs.append(
                WorkbookSheet(
                    name="Custom AdHoc Crosstabs",
                    banner_name="Custom AdHoc Crosstabs",
                    levels=[],
                    groups=[],
                    tables=adhoc_tables,
                    footnotes=[],
                    include_percentage=adhoc_include_percentage,
                    include_n_count=adhoc_include_n_count,
                    include_stat_testing=adhoc_include_stat_testing,
                    notation_location=adhoc_notation_location,
                )
            )

    topline_variables = {
        normalize_text(value)
        for value in topline_config.get("variables", [])
        if normalize_text(value)
    }
    response_selection_map = {
        normalize_text(variable): [
            normalize_text(choice)
            for choice in choices
            if normalize_text(choice)
        ]
        for variable, choices in topline_config.get("response_selections", {}).items()
        if normalize_text(variable)
    }
    note_base_section_map = {
        normalize_text(variable): (
            "Total Sample"
            if str(section).strip() == "Total Sample"
            else "Total Answering"
        )
        for variable, section in topline_config.get("note_base_sections", {}).items()
        if normalize_text(variable)
    }
    topline_question_sheets = [
        WorkbookSheet(
            name=sheet.name,
            banner_name=sheet.banner_name,
            levels=sheet.levels,
            level_labels=dict(getattr(sheet, "level_labels", {})),
            groups=sheet.groups,
            comparison_pairs=list(getattr(sheet, "comparison_pairs", []) or []),
            tables=[
                table for table in sheet.tables
                if not topline_variables or normalize_text(table.variable) in topline_variables
            ],
            footnotes=list(getattr(sheet, "footnotes", []) or []),
        )
        for sheet in sheet_specs
    ]
    effective_topline_lift = bool(topline_config.get("include_lift", False)) and bool(
        banner_stat_config.get("include_lift", False)
    )
    topline_rows = _build_topline_rows(
        total_comparison_sheet=total_comparison_sheet,
        banner_sheets=topline_question_sheets,
        comparison_col=effective_comparison_col if layered_scheme_active else comparison_col,
        include_lift=effective_topline_lift,
        include_significance_notes=bool(topline_config.get("include_significance_notes", True)),
        included_variables=topline_variables,
        response_selection_map=response_selection_map,
        note_base_section_map=note_base_section_map,
        variable_display_names=variable_display_names,
    )

    return {
        "sheets": sheet_specs,
        "topline_sheet": ToplineSheet(
            rows=topline_rows,
            footnotes=list(getattr(total_comparison_sheet, "footnotes", []) or []) if total_comparison_sheet else [],
        ),
        "confidence_intervals": banner_confidence_intervals,
        "comparison_scope": banner_comparison_scope,
        "include_lift": bool(banner_stat_config.get("include_lift", False)),
        "include_percentage": banner_include_percentage,
        "include_n_count": banner_include_n_count,
        "question_count": len(enabled_questions),
        "sheet_count": len(sheet_specs),
        "comparison_scheme_active": layered_scheme_active,
        "comparison_scheme_has_overlaps": project_has_overlaps,
    }


def build_workbook_preview(workbook_package: dict[str, Any]) -> pd.DataFrame:
    """Build a compact preview table for the export page."""
    rows: list[dict[str, Any]] = []
    topline_sheet = workbook_package.get("topline_sheet")
    if topline_sheet and getattr(topline_sheet, "rows", None) is not None:
        rows.append(
            {
                "Sheet": "Topline",
                "Banner Levels": "Comparison summary",
                "Groups": "N/A",
                "Questions": len({row["Variable"] for row in topline_sheet.rows}),
            }
        )
    for sheet in workbook_package.get("sheets", []):
        level_labels = getattr(sheet, "level_labels", {}) or {}
        rows.append(
            {
                "Sheet": sheet.banner_name,
                "Banner Levels": " > ".join(level_labels.get(level, level) for level in sheet.levels) if sheet.levels else "All Tables",
                "Groups": str(len(sheet.groups)),
                "Questions": len(sheet.tables),
            }
        )
    return pd.DataFrame(rows)


def generate_placeholder_tables(
    cleaned_df: pd.DataFrame | None,
    question_metadata: list[dict[str, Any]],
) -> dict[str, pd.DataFrame]:
    """Compatibility wrapper for older placeholder export paths.

    Inputs:
        The current cleaned dataframe and question metadata.

    Outputs:
        A simple workbook-like dictionary used only by older legacy code paths.
    """
    summary_rows = [
        {"metric": "rows", "value": 0 if cleaned_df is None else len(cleaned_df)},
        {"metric": "questions", "value": len(question_metadata)},
        {"metric": "status", "value": "compatibility-placeholder"},
    ]
    return {
        "Summary": pd.DataFrame(summary_rows),
        "Question Metadata": pd.DataFrame(question_metadata),
    }


def build_placeholder_table_preview(generated_tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compatibility wrapper that previews the first placeholder sheet."""
    if not generated_tables:
        return pd.DataFrame()
    first_key = next(iter(generated_tables))
    return generated_tables[first_key]
