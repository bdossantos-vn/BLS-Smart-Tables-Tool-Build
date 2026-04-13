"""Core table-generation helpers for the BLS Smart Tables Tool."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any

import pandas as pd
from scipy.stats import norm

from src.custom_vars import build_question_lookup
from src.nets import build_enabled_net_choice_map
from src.stats import normalize_confidence_intervals
from src.utils import alpha_letter_sequence, normalize_text


@dataclass
class SheetTable:
    """One rendered question table destined for a workbook sheet."""

    variable: str
    question_label: str
    sections: list[dict[str, Any]]


@dataclass
class WorkbookSheet:
    """One workbook sheet with banner metadata and rendered tables."""

    name: str
    banner_name: str
    levels: list[str]
    groups: list[dict[str, Any]]
    tables: list[SheetTable]


@dataclass
class ToplineSheet:
    """One flat topline sheet used for quick analyst summaries.

    This sheet is intentionally flatter than the banner sheets. It is meant to
    surface the most useful control-vs-test comparison rows and short notes in
    one place.
    """

    rows: list[dict[str, Any]]


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
        messages.append(f"{banner_count} banner sheet(s) are configured.")
    else:
        messages.append("No banners configured. Export will use a single `All Tables` sheet.")
    return messages


def _normalize_banner_rows(banner_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return banner rows that have at least one configured level."""
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
                    "name": normalize_text(row.get("name")) or levels[0],
                    "levels": [value for value in levels if value],
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
    if operator == "Is exactly":
        normalized_choices = {normalize_text(choice) for choice in choices if normalize_text(choice)}
        return series.map(lambda value: normalize_text(value) in normalized_choices).fillna(False)
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
        label = " | ".join(normalize_text(values[level]) for level in levels)
        groups.append(
            {
                "label": label,
                "mask": mask.fillna(False),
                "values": values,
            }
        )
    return groups


def _compute_choice_count(series: pd.Series, choice: str) -> pd.Series:
    """Return a boolean mask for respondents who selected one choice."""
    normalized_choice = normalize_text(choice)
    return series.map(lambda value: _value_matches_selected_choices(value, [normalized_choice])).fillna(False)


def _get_question_rows(
    variable: str,
    question_row: dict[str, Any],
    net_definitions: dict[str, dict[str, bool]],
    scale_mappings: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the ordered output rows for one question table."""
    rows: list[dict[str, Any]] = []
    question_type = normalize_text(question_row.get("detected_type"))
    answer_choices = list(question_row.get("answer_choices_list", []))
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
    for choice in answer_choices:
        rows.append(
            {
                "label": choice,
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


def _build_sig_letters(
    counts_by_group: list[int],
    denominators_by_group: list[int],
    group_labels: list[str],
    alpha: float,
    comparison_scope: str,
) -> list[str]:
    """Build significance letters for one row across the visible banner groups."""
    if len(group_labels) <= 1:
        return ["" for _ in group_labels]
    letters = alpha_letter_sequence(len(group_labels))
    output = ["" for _ in group_labels]

    compare_pairs: list[tuple[int, int]] = []
    if comparison_scope == "control_vs_test":
        control_indexes = [index for index, label in enumerate(group_labels) if normalize_text(label).lower() == "control"]
        test_indexes = [index for index, label in enumerate(group_labels) if normalize_text(label).lower() == "test"]
        for control_index in control_indexes:
            for test_index in test_indexes:
                compare_pairs.append((control_index, test_index))
    else:
        compare_pairs = list(combinations(range(len(group_labels)), 2))

    for index_a, index_b in compare_pairs:
        if _pooled_two_sample_z_test(
            counts_by_group[index_a],
            denominators_by_group[index_a],
            counts_by_group[index_b],
            denominators_by_group[index_b],
            alpha,
        ):
            output[index_a] += letters[index_b]
        if _pooled_two_sample_z_test(
            counts_by_group[index_b],
            denominators_by_group[index_b],
            counts_by_group[index_a],
            denominators_by_group[index_a],
            alpha,
        ):
            output[index_b] += letters[index_a]
    return output


def _build_question_table(
    df: pd.DataFrame,
    question_row: dict[str, Any],
    groups: list[dict[str, Any]],
    net_definitions: dict[str, dict[str, bool]],
    scale_mappings: dict[str, dict[str, Any]],
    alpha: float,
    comparison_scope: str,
) -> SheetTable:
    """Build one question table for all visible groups on a banner sheet."""
    variable = normalize_text(question_row.get("variable"))
    question_label = normalize_text(question_row.get("question_label")) or variable
    question_series = df[variable] if variable in df.columns else pd.Series([None] * len(df), index=df.index)
    output_rows = _get_question_rows(variable, question_row, net_definitions, scale_mappings)

    total_base_denominators = [int(group["mask"].sum()) for group in groups]
    answering_masks = question_series.map(lambda value: normalize_text(value) != "").fillna(False)
    total_answering_denominators = [int((group["mask"] & answering_masks).sum()) for group in groups]

    sections: list[dict[str, Any]] = []
    for section_label, denominators, base_masks in [
        ("Total Base", total_base_denominators, [group["mask"] for group in groups]),
        ("Total Answering", total_answering_denominators, [group["mask"] & answering_masks for group in groups]),
    ]:
        rows: list[dict[str, Any]] = []
        for output_row in output_rows:
            counts_by_group: list[int] = []
            percentages_by_group: list[float | None] = []
            for group_mask, denominator in zip(base_masks, denominators):
                matched_mask = question_series.map(
                    lambda value: any(
                        _value_matches_selected_choices(value, [choice])
                        for choice in output_row["choices"]
                    )
                ).fillna(False)
                numerator = int((group_mask & matched_mask).sum())
                counts_by_group.append(numerator)
                percentages_by_group.append((numerator / denominator) if denominator else None)
            sig_letters = _build_sig_letters(
                counts_by_group[1:] if groups and groups[0]["label"] == "Total" else counts_by_group,
                denominators[1:] if groups and groups[0]["label"] == "Total" else denominators,
                [group["label"] for group in groups[1:]] if groups and groups[0]["label"] == "Total" else [group["label"] for group in groups],
                alpha,
                comparison_scope,
            )
            if groups and groups[0]["label"] == "Total":
                sig_letters = ["", *sig_letters]
            rows.append(
                {
                    "label": output_row["label"],
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

    return SheetTable(variable=variable, question_label=question_label, sections=sections)


def _find_control_test_pair_indexes(
    groups: list[dict[str, Any]],
    comparison_col: str | None,
) -> list[tuple[int, int, str]]:
    """Find control/test group pairs for topline comparisons.

    Inputs:
        groups: Banner groups already built for one sheet.
        comparison_col: The configured comparison variable, usually `cell`.

    Outputs:
        A list of `(control_index, test_index, subgroup_label)` tuples. The
        subgroup label describes the non-comparison part of the banner path so
        notes can read like `test females sig higher than control females`.
    """
    normalized_comparison = normalize_text(comparison_col)
    if not normalized_comparison:
        return []

    group_lookup: dict[tuple[tuple[str, str], ...], dict[str, int]] = {}
    for index, group in enumerate(groups):
        if group.get("label") == "Total":
            continue
        values = {
            normalize_text(key): normalize_text(value)
            for key, value in group.get("values", {}).items()
            if normalize_text(key)
        }
        if normalized_comparison not in values:
            continue
        comparison_value = normalize_text(values.pop(normalized_comparison)).lower()
        subgroup_key = tuple(sorted(values.items()))
        group_lookup.setdefault(subgroup_key, {})[comparison_value] = index

    pairs: list[tuple[int, int, str]] = []
    for subgroup_key, indexed_values in group_lookup.items():
        if "control" not in indexed_values or "test" not in indexed_values:
            continue
        subgroup_label = "Total"
        if subgroup_key:
            subgroup_label = " | ".join(value for _, value in subgroup_key)
        pairs.append((indexed_values["control"], indexed_values["test"], subgroup_label))
    return pairs


def _build_topline_note(
    subgroup_label: str,
    control_pct: float,
    test_pct: float,
    significant_direction: str,
) -> str:
    """Build one plain-English topline note.

    Inputs:
        subgroup_label: Lowest-level banner subgroup label.
        control_pct: Control percentage stored as a decimal.
        test_pct: Test percentage stored as a decimal.
        significant_direction: Either `test`, `control`, or blank.

    Outputs:
        A short note that reads like an analyst summary.
    """
    if significant_direction not in {"test", "control"}:
        return ""
    subgroup_suffix = ""
    if subgroup_label and subgroup_label != "Total":
        subgroup_suffix = f" {subgroup_label}"
    higher_value = test_pct if significant_direction == "test" else control_pct
    lower_value = control_pct if significant_direction == "test" else test_pct
    lift_points = round((test_pct - control_pct) * 100)
    direction_text = "higher"
    if significant_direction == "test":
        return (
            f"test{subgroup_suffix} sig {direction_text} than control{subgroup_suffix} "
            f"({higher_value:.0%}, {lift_points:+d} pts lift)"
        )
    return (
        f"control{subgroup_suffix} sig {direction_text} than test{subgroup_suffix} "
        f"({higher_value:.0%}, {abs(lift_points):+d} pts lift)"
    )


def _build_topline_rows(
    sheets: list[WorkbookSheet],
    comparison_col: str | None,
    include_lift: bool,
    include_significance_notes: bool,
) -> list[dict[str, Any]]:
    """Flatten banner comparisons into one topline sheet.

    Inputs:
        sheets: The already-built banner sheets.
        comparison_col: The selected comparison variable, usually `cell`.
        include_lift: Whether the topline sheet should show lift values.
        include_significance_notes: Whether the topline sheet should include
            analyst-style notes for significant differences.

    Outputs:
        A list of flat topline rows. Each row describes one question response
        within one banner subgroup for control vs test.
    """
    rows: list[dict[str, Any]] = []
    for sheet in sheets:
        control_test_pairs = _find_control_test_pair_indexes(sheet.groups, comparison_col)
        if not control_test_pairs:
            continue
        for table in sheet.tables:
            answering_section = next(
                (section for section in table.sections if section.get("label") == "Total Answering"),
                None,
            )
            if not answering_section:
                continue
            base_denominators = list(answering_section.get("base_denominators", []))
            for row in answering_section.get("rows", []):
                for control_index, test_index, subgroup_label in control_test_pairs:
                    control_n = row["counts"][control_index]
                    test_n = row["counts"][test_index]
                    control_pct = row["percentages"][control_index] or 0.0
                    test_pct = row["percentages"][test_index] or 0.0

                    significant_direction = ""
                    test_sig = normalize_text(row["sig_letters"][test_index])
                    control_sig = normalize_text(row["sig_letters"][control_index])
                    if control_sig:
                        significant_direction = "control"
                    elif test_sig:
                        significant_direction = "test"

                    sig_display = ""
                    if significant_direction == "test":
                        sig_display = "Test > Control"
                    elif significant_direction == "control":
                        sig_display = "Control > Test"

                    rows.append(
                        {
                            "Question": table.question_label,
                            "Variable": table.variable,
                            "Response": row["label"],
                            "Banner": sheet.banner_name,
                            "Segment": subgroup_label,
                            "Control Base": base_denominators[control_index],
                            "Control N": control_n,
                            "Control %": control_pct,
                            "Test Base": base_denominators[test_index],
                            "Test N": test_n,
                            "Test %": test_pct,
                            "Lift": (test_pct - control_pct) if include_lift else None,
                            "Sig Test": sig_display,
                            "Notes": (
                                _build_topline_note(subgroup_label, control_pct, test_pct, significant_direction)
                                if include_significance_notes
                                else ""
                            ),
                        }
                    )
    return rows


def generate_workbook_package(
    cleaned_df: pd.DataFrame,
    question_metadata: list[dict[str, Any]],
    custom_variables: list[dict[str, Any]],
    banner_config: dict[str, Any],
    net_definitions: dict[str, dict[str, bool]],
    scale_mappings: dict[str, dict[str, Any]],
    stat_config: dict[str, Any],
    comparison_col: str | None,
    comparison_group_order: dict[str, int],
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
    analysis_df = _materialize_custom_variables(cleaned_df, custom_variables, question_lookup)

    enabled_questions = [
        row
        for row in question_metadata
        if normalize_text(row.get("detected_type")) not in {"Ignore", "Open-End Text"}
        and normalize_text(row.get("variable")) in analysis_df.columns
    ]

    banner_rows = _normalize_banner_rows(banner_config)
    include_total = bool(banner_config.get("include_total", True))
    confidence_intervals = normalize_confidence_intervals(stat_config.get("confidence_intervals", [95]))
    alpha = (100 - confidence_intervals[0]) / 100 if confidence_intervals else 0.05
    comparison_scope = normalize_text(stat_config.get("comparison_scope")) or "lowest_banner_level"

    sheet_specs: list[WorkbookSheet] = []
    if not banner_rows:
        groups = _build_banner_groups(
            analysis_df,
            None,
            True,
            question_lookup,
            custom_variables,
            comparison_col,
            comparison_group_order,
        )
        tables = [
            _build_question_table(
                analysis_df,
                question_row,
                groups,
                net_definitions,
                scale_mappings,
                alpha,
                comparison_scope,
            )
            for question_row in enabled_questions
        ]
        sheet_specs.append(
            WorkbookSheet(
                name="All Tables",
                banner_name="All Tables",
                levels=[],
                groups=groups,
                tables=tables,
            )
        )
    else:
        for banner_row in banner_rows:
            groups = _build_banner_groups(
                analysis_df,
                banner_row,
                include_total,
                question_lookup,
                custom_variables,
                comparison_col,
                comparison_group_order,
            )
            tables = [
                _build_question_table(
                    analysis_df,
                    question_row,
                    groups,
                    net_definitions,
                    scale_mappings,
                    alpha,
                    comparison_scope,
                )
                for question_row in enabled_questions
            ]
            sheet_specs.append(
                WorkbookSheet(
                    name=banner_row["name"],
                    banner_name=banner_row["name"],
                    levels=banner_row["levels"],
                    groups=groups,
                    tables=tables,
                )
            )

    topline_config = topline_config or {}
    topline_variables = {
        normalize_text(value)
        for value in topline_config.get("variables", [])
        if normalize_text(value)
    }
    topline_question_sheets = [
        WorkbookSheet(
            name=sheet.name,
            banner_name=sheet.banner_name,
            levels=sheet.levels,
            groups=sheet.groups,
            tables=[
                table for table in sheet.tables
                if not topline_variables or normalize_text(table.variable) in topline_variables
            ],
        )
        for sheet in sheet_specs
    ]
    effective_topline_lift = bool(topline_config.get("include_lift", False)) and bool(
        stat_config.get("include_lift", False)
    )
    topline_rows = _build_topline_rows(
        topline_question_sheets,
        comparison_col=comparison_col,
        include_lift=effective_topline_lift,
        include_significance_notes=bool(topline_config.get("include_significance_notes", True))
        and effective_topline_lift,
    )

    return {
        "sheets": sheet_specs,
        "topline_sheet": ToplineSheet(rows=topline_rows),
        "confidence_intervals": confidence_intervals,
        "comparison_scope": comparison_scope,
        "question_count": len(enabled_questions),
        "sheet_count": len(sheet_specs),
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
        rows.append(
            {
                "Sheet": sheet.banner_name,
                "Banner Levels": " > ".join(sheet.levels) if sheet.levels else "All Tables",
                "Groups": len(sheet.groups),
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
