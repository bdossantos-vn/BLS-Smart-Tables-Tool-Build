"""Respondent-level weighting helpers for table generation and audit exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re

import pandas as pd

from src.utils import normalize_text


FINAL_WEIGHT_COLUMN = "BLS_Final_Weight"
ALL_CONFIGURED_WEIGHT_COLUMN = "BLS_All_Configured_Weights"


@dataclass
class WeightResult:
    """Calculated respondent-level weight factors for configured weight rows."""

    weight_columns: dict[str, pd.Series]
    row_names: dict[str, str]
    issues: list[str]


def _target_matches(applies_to: list[str], target_names: list[str]) -> bool:
    """Return whether one weighting row applies to the requested export target."""
    normalized_targets = {normalize_text(value).casefold() for value in target_names if normalize_text(value)}
    normalized_applies = {normalize_text(value).casefold() for value in applies_to if normalize_text(value)}
    if not normalized_applies or "all tables" in normalized_applies:
        return True
    return bool(normalized_targets & normalized_applies)


def _safe_weight_column_name(name: str, index: int) -> str:
    """Build a stable CSV-safe column name for one configured weight row."""
    normalized = normalize_text(name) or f"Weight_{index}"
    slug = re.sub(r"[^0-9A-Za-z]+", "_", normalized).strip("_")
    return f"BLS_Weight_{slug or index}"


def _weight_combo_key(df: pd.DataFrame, variables: list[str]) -> pd.Series:
    """Return one post-stratification cell key per respondent."""
    if not variables:
        return pd.Series("", index=df.index, dtype=object)
    parts = []
    for variable in variables:
        if variable in df.columns:
            part = df[variable].map(normalize_text)
        else:
            part = pd.Series("", index=df.index, dtype=object)
        parts.append(part.replace("", "(Blank)"))
    combo = parts[0].astype(str)
    for part in parts[1:]:
        combo = combo + "||" + part.astype(str)
    return combo


def _group_value_series(df: pd.DataFrame, group_variable: str | None) -> pd.Series:
    """Return the source group for each respondent, or Total when no group exists."""
    if group_variable and group_variable in df.columns:
        return df[group_variable].map(normalize_text).replace("", "(Blank)")
    return pd.Series("Total", index=df.index, dtype=object)


def _target_mask_for_row(
    df: pd.DataFrame,
    group_values: pd.Series,
    target: str,
) -> pd.Series:
    """Resolve the target group/distribution for one weight row."""
    normalized_target = normalize_text(target)
    if not normalized_target or normalized_target.casefold() == "total" or normalized_target.casefold().startswith("match "):
        return pd.Series(True, index=df.index)
    return group_values.map(lambda value: normalize_text(value).casefold() == normalized_target.casefold()).fillna(False)


def _limit_mask_for_row(
    df: pd.DataFrame,
    limit_variable: str | None,
    limit_values: list[str] | None,
) -> tuple[pd.Series, list[str]]:
    """Return the respondent subset where a weight row should create factors."""
    issues: list[str] = []
    normalized_variable = normalize_text(limit_variable)
    normalized_values = [
        normalize_text(value)
        for value in (limit_values or [])
        if normalize_text(value)
    ]
    if not normalized_variable and not normalized_values:
        return pd.Series(True, index=df.index), issues
    if not normalized_variable:
        issues.append("Weight limit values were ignored because no limit variable was selected.")
        return pd.Series(False, index=df.index), issues
    if normalized_variable not in df.columns:
        issues.append(f"Weight limit variable `{normalized_variable}` was not found; no respondents were weighted.")
        return pd.Series(False, index=df.index), issues
    if not normalized_values:
        issues.append(f"Weight limit `{normalized_variable}` has no selected values; no respondents were weighted.")
        return pd.Series(False, index=df.index), issues

    allowed_values = {value.casefold() for value in normalized_values}
    mask = df[normalized_variable].map(lambda value: normalize_text(value).casefold() in allowed_values).fillna(False)
    if not bool(mask.any()):
        issues.append(
            f"Weight limit `{normalized_variable}` did not match selected values; no respondents were weighted."
        )
    return mask.astype(bool), issues


def _distribution_for_mask(combo_values: pd.Series, mask: pd.Series) -> dict[str, float]:
    """Return proportional distribution of post-stratification cells within a mask."""
    aligned_mask = mask.reindex(combo_values.index, fill_value=False).astype(bool)
    selected = combo_values.loc[aligned_mask]
    total = len(selected)
    if total <= 0:
        return {}
    counts = selected.value_counts(dropna=False)
    return {normalize_text(key): float(count) / total for key, count in counts.items()}


def _compute_poststratification_factor(
    df: pd.DataFrame,
    variables: list[str],
    group_variable: str | None,
    target: str,
    limit_variable: str | None = None,
    limit_values: list[str] | None = None,
) -> tuple[pd.Series, list[str]]:
    """Calculate one weight row as target cell share divided by source group share."""
    issues: list[str] = []
    existing_variables = [variable for variable in variables if variable in df.columns]
    missing_variables = [variable for variable in variables if variable not in df.columns]
    for variable in missing_variables:
        issues.append(f"Weight variable `{variable}` was not found and was skipped.")
    if not existing_variables:
        return pd.Series(1.0, index=df.index), issues

    source_group_variable = group_variable if group_variable in df.columns else None
    if group_variable and source_group_variable is None:
        issues.append(f"Weight source `{group_variable}` was not found; using a single Total source group.")

    combo_values = _weight_combo_key(df, existing_variables)
    group_values = _group_value_series(df, source_group_variable)
    limit_mask, limit_issues = _limit_mask_for_row(df, limit_variable, limit_values)
    issues.extend(limit_issues)
    if not bool(limit_mask.any()):
        return pd.Series(1.0, index=df.index), issues

    target_mask = _target_mask_for_row(df, group_values, target) & limit_mask
    if not bool(target_mask.any()):
        issues.append(f"Weight target `{target}` did not match any respondents; using the limited subset as the target.")
        target_mask = limit_mask.copy()
    target_distribution = _distribution_for_mask(combo_values, target_mask)
    if not target_distribution:
        return pd.Series(1.0, index=df.index), issues

    factors = pd.Series(1.0, index=df.index, dtype=float)
    for group_value in group_values.loc[limit_mask].dropna().unique().tolist():
        group_mask = (group_values == group_value) & limit_mask
        group_distribution = _distribution_for_mask(combo_values, group_mask)
        if not group_distribution:
            continue
        for combo_value, group_share in group_distribution.items():
            if group_share <= 0:
                continue
            target_share = target_distribution.get(combo_value, 0.0)
            factors.loc[group_mask & (combo_values == combo_value)] = target_share / group_share
    return factors.fillna(1.0).astype(float), issues


def active_weight_rows(weighting_config: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return configured weight rows that have the minimum fields needed for math."""
    rows = []
    for row in (weighting_config or {}).get("weights", []):
        if not isinstance(row, dict):
            continue
        variables = [normalize_text(value) for value in row.get("variables", []) if normalize_text(value)]
        if not normalize_text(row.get("name")) or not variables:
            continue
        rows.append(row)
    return rows


def has_active_weighting(weighting_config: dict[str, Any] | None) -> bool:
    """Return whether weighting has at least one usable row."""
    return bool(active_weight_rows(weighting_config))


def calculate_weight_factors(
    df: pd.DataFrame,
    weighting_config: dict[str, Any] | None,
    comparison_col: str | None = None,
) -> WeightResult:
    """Calculate every configured weight row as a respondent-level factor."""
    weight_columns: dict[str, pd.Series] = {}
    row_names: dict[str, str] = {}
    issues: list[str] = []
    used_columns: set[str] = set()
    for index, row in enumerate(active_weight_rows(weighting_config), start=1):
        name = normalize_text(row.get("name")) or f"Weight {index}"
        column_name = _safe_weight_column_name(name, index)
        base_column_name = column_name
        suffix = 2
        while column_name in used_columns:
            column_name = f"{base_column_name}_{suffix}"
            suffix += 1
        used_columns.add(column_name)
        source_variable = normalize_text(row.get("source")) or normalize_text(comparison_col)
        variables = [normalize_text(value) for value in row.get("variables", []) if normalize_text(value)]
        factors, row_issues = _compute_poststratification_factor(
            df,
            variables,
            source_variable,
            normalize_text(row.get("target")) or "Total",
            normalize_text(row.get("limit_variable")),
            [normalize_text(value) for value in row.get("limit_values", []) if normalize_text(value)],
        )
        weight_columns[column_name] = factors
        row_names[column_name] = name
        issues.extend(f"{name}: {issue}" for issue in row_issues)
    return WeightResult(weight_columns=weight_columns, row_names=row_names, issues=issues)


def effective_weight_series(
    df: pd.DataFrame,
    weighting_config: dict[str, Any] | None,
    comparison_col: str | None,
    target_names: list[str],
    weight_result: WeightResult | None = None,
) -> pd.Series:
    """Return the effective respondent weight for the current table target."""
    result = weight_result or calculate_weight_factors(df, weighting_config, comparison_col)
    weights = pd.Series(1.0, index=df.index, dtype=float)
    active_rows = active_weight_rows(weighting_config)
    for row, column_name in zip(active_rows, result.weight_columns):
        if not _target_matches(list(row.get("applies_to", [])), target_names):
            continue
        weights = weights * result.weight_columns[column_name].reindex(df.index, fill_value=1.0).astype(float)
    return weights.fillna(1.0)


def build_weight_audit_dataframe(
    df: pd.DataFrame,
    weighting_config: dict[str, Any] | None,
    comparison_col: str | None,
) -> pd.DataFrame:
    """Return respondent-level data with calculated weight columns for audit records."""
    audit_df = df.copy()
    result = calculate_weight_factors(df, weighting_config, comparison_col)
    final_weight = pd.Series(1.0, index=df.index, dtype=float)
    all_configured_weight = pd.Series(1.0, index=df.index, dtype=float)
    active_rows = active_weight_rows(weighting_config)
    for row, column_name in zip(active_rows, result.weight_columns):
        factor = result.weight_columns[column_name].reindex(df.index, fill_value=1.0).astype(float)
        audit_df[column_name] = factor.round(6)
        all_configured_weight = all_configured_weight * factor
        if _target_matches(list(row.get("applies_to", [])), ["All Tables"]):
            final_weight = final_weight * factor
    audit_df[FINAL_WEIGHT_COLUMN] = final_weight.round(6)
    audit_df[ALL_CONFIGURED_WEIGHT_COLUMN] = all_configured_weight.round(6)
    return audit_df
