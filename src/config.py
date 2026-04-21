"""Analysis configuration helpers."""

from __future__ import annotations

from typing import Any

from src.utils import normalize_text


def build_default_weighting_config() -> dict:
    """Return the default weighting configuration."""
    return {
        "weights": [],
    }


def build_default_banner_config() -> dict:
    """Return the default banner configuration."""
    return {
        "banner_variables": [],
        "banners": [],
        "include_total": True,
        "export_style": "one_per_sheet",
    }


def build_default_banner_row() -> dict[str, str]:
    """Return a blank nested-banner row."""
    return {
        "name": "",
        "level_1": "",
        "level_2": "",
        "level_3": "",
    }


def build_default_stat_config() -> dict:
    """Return the default statistical configuration scaffold."""
    return {
        "confidence_intervals": [95],
        "alpha": 0.05,
        "enabled": True,
        "comparison_scope": "control_vs_test",
        "include_n_count": False,
        "include_lift": False,
        "notation_location": "appended_to_metric",
    }


def build_default_adhoc_crosstab_config() -> dict:
    """Return the default custom AdHoc Crosstab configuration."""
    return {
        "tables": [],
    }


def build_default_adhoc_crosstab_row() -> dict[str, str]:
    """Return a blank AdHoc crosstab row."""
    return {
        "name": "",
        "row_variable": "",
        "column_variable": "",
    }


def build_stat_comparison_options(comparison_col: str | None = None) -> list[tuple[str, str]]:
    """Return UI options for statistical comparison behavior."""
    options = [("none", "None"), ("lowest_banner_level", "All lowest banner-level groups")]
    if normalize_text(comparison_col):
        options.insert(1, ("control_vs_test", "Control vs test within each banner"))
    return options


def build_stat_notation_options() -> list[tuple[str, str]]:
    """Return UI options for significance notation placement."""
    return [
        ("appended_to_metric", "Appended to Metric"),
        ("below_metric", "Below Metric"),
    ]
    


def build_analysis_variable_catalog(
    question_metadata: list[dict[str, Any]],
    custom_variables: list[dict[str, Any]],
    comparison_col: str | None = None,
) -> list[dict[str, str]]:
    """Build a catalog of variables available for banners and filters."""
    catalog: list[dict[str, str]] = []
    seen: set[str] = set()

    comparison_variable = normalize_text(comparison_col)
    if comparison_variable:
        catalog.append(
            {
                "id": comparison_variable,
                "label": comparison_variable,
                "kind": "Comparison Variable",
                "question_type": "Single-Select",
            }
        )
        seen.add(comparison_variable)

    for row in question_metadata:
        variable = normalize_text(row.get("variable"))
        question_type = normalize_text(row.get("detected_type"))
        if not variable or variable in seen:
            continue
        if question_type in {"Ignore", "Open-End Text"}:
            continue
        catalog.append(
            {
                "id": variable,
                "label": f"{variable} - {normalize_text(row.get('question_label'))}",
                "kind": "Survey Question",
                "question_type": question_type,
            }
        )
        seen.add(variable)

    for record in custom_variables:
        name = normalize_text(record.get("name"))
        if not name or name in seen:
            continue
        catalog.append(
            {
                "id": name,
                "label": f"{name} - Custom Variable",
                "kind": "Custom Variable",
                "question_type": normalize_text(record.get("builder_type")) or "Custom",
            }
        )
        seen.add(name)

    return catalog


def build_weight_variable_options(question_metadata: list[dict[str, Any]]) -> list[str]:
    """Return variables that are reasonable weight candidates."""
    options: list[str] = []
    for row in question_metadata:
        variable = normalize_text(row.get("variable"))
        question_type = normalize_text(row.get("detected_type"))
        if not variable:
            continue
        if question_type in {"Numeric Data", "Single-Select"}:
            options.append(variable)
    return options


def build_default_weight_row() -> dict[str, Any]:
    """Return a blank weighting row."""
    return {
        "name": "",
        "target": "Total",
        "source": "",
        "variables": [],
        "applies_to": [],
    }


def build_filter_operator_options(question_type: str) -> list[str]:
    """Return supported operators for a filterable variable."""
    if question_type == "Numeric Data":
        return ["Equals", "Does not equal", "Greater than", "Less than"]
    return ["Includes any", "Excludes all", "Is exactly"]


def build_default_filter_condition() -> dict[str, Any]:
    """Return a blank filter condition."""
    return {
        "variable": "",
        "operator": "",
        "values": [],
    }


def build_default_filter_branch() -> dict[str, Any]:
    """Return a blank filter branch."""
    return {
        "name": "",
        "match_logic": "ALL",
        "conditions": [build_default_filter_condition()],
    }


def build_default_filter_row() -> dict[str, Any]:
    """Return a blank named filter definition."""
    return {
        "name": "",
        "branches": [build_default_filter_branch()],
        "applies_to": [],
    }


def validate_analysis_config(
    weighting_config: dict,
    banner_config: dict,
    global_filters: dict,
    local_overrides: dict | None = None,
) -> list[str]:
    """Validate the analysis configuration payload."""
    issues: list[str] = []
    weights = weighting_config.get("weights", [])
    if weights and not isinstance(weights, list):
        issues.append("Weights must be stored as a list.")
    elif isinstance(weights, list):
        seen_weight_names: set[str] = set()
        for index, row in enumerate(weights, start=1):
            name = normalize_text(row.get("name"))
            target = normalize_text(row.get("target"))
            variables = row.get("variables", [])
            applies_to = row.get("applies_to", [])
            if not name:
                issues.append(f"Weight {index} needs a name.")
            elif name in seen_weight_names:
                issues.append(f"Weight {index} duplicates another weight name.")
            else:
                seen_weight_names.add(name)
            if not target:
                issues.append(f"Weight {index} needs a target definition.")
            if not variables:
                issues.append(f"Weight {index} needs at least one weighting variable.")
            if not applies_to:
                issues.append(f"Weight {index} needs at least one apply target.")
    if not isinstance(banner_config.get("banner_variables", []), list):
        issues.append("Banner variables must be stored as a list.")
    if not isinstance(banner_config.get("banners", []), list):
        issues.append("Nested banners must be stored as a list.")
    else:
        seen_banner_paths: set[tuple[str, ...]] = set()
        for index, row in enumerate(banner_config.get("banners", []), start=1):
            banner_name = normalize_text(row.get("name"))
            level_values = [
                normalize_text(row.get("level_1")),
                normalize_text(row.get("level_2")),
                normalize_text(row.get("level_3")),
            ]
            if not banner_name:
                issues.append(f"Banner {index} needs a name.")
            if not level_values[0]:
                issues.append(f"Banner {index} needs a Level 1 variable.")
                continue
            trimmed_values = [value for value in level_values if value]
            if len(trimmed_values) != len(set(trimmed_values)):
                issues.append(f"Banner {index} cannot repeat the same variable across levels.")
            if level_values[2] and not level_values[1]:
                issues.append(f"Banner {index} cannot use Level 3 without Level 2.")
            banner_path = tuple(trimmed_values)
            if banner_path in seen_banner_paths:
                issues.append(f"Banner {index} duplicates another banner path.")
            seen_banner_paths.add(banner_path)
    if not isinstance(global_filters, dict):
        issues.append("Global filters must be stored as a dictionary.")
    else:
        for index, row in enumerate(global_filters.get("rows", []), start=1):
            name = normalize_text(row.get("name"))
            branches = row.get("branches", [])
            applies_to = row.get("applies_to", [])
            if not name:
                issues.append(f"Filter {index} needs a name.")
            if not applies_to:
                issues.append(f"Filter {index} needs at least one apply target.")
            if not branches:
                issues.append(f"Filter {index} needs at least one branch.")
                continue
            for branch_index, branch in enumerate(branches, start=1):
                match_logic = normalize_text(branch.get("match_logic"))
                conditions = branch.get("conditions", [])
                if match_logic not in {"ALL", "ANY"}:
                    issues.append(f"Filter {index} branch {branch_index} needs `ALL` or `ANY` logic.")
                if not conditions:
                    issues.append(f"Filter {index} branch {branch_index} needs at least one condition.")
                    continue
                for condition_index, condition in enumerate(conditions, start=1):
                    variable = normalize_text(condition.get("variable"))
                    operator = normalize_text(condition.get("operator"))
                    values = condition.get("values", [])
                    if any([variable, operator, values]) and not (variable and operator and values):
                        issues.append(
                            f"Filter {index} branch {branch_index} condition {condition_index} is incomplete."
                        )
                    elif not any([variable, operator, values]):
                        issues.append(
                            f"Filter {index} branch {branch_index} condition {condition_index} is incomplete."
                        )
    if not isinstance(local_overrides or {}, dict):
        issues.append("Local overrides must be stored as a dictionary.")
    else:
        for banner_variable, rows in (local_overrides or {}).items():
            for index, row in enumerate(rows or [], start=1):
                variable = normalize_text(row.get("variable"))
                operator = normalize_text(row.get("operator"))
                values = normalize_text(row.get("values"))
                if any([variable, operator, values]) and not all([variable, operator, values]):
                    issues.append(f"{banner_variable} override row {index} is incomplete.")
    return issues
