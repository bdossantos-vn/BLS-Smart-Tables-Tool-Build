"""I/O helpers for reading Qualtrics exports."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from tempfile import NamedTemporaryFile
from typing import Any
import re

import pandas as pd

from src.utils import normalize_text


@dataclass
class ExcelReadResult:
    """Container for raw workbook data."""

    dataframe: pd.DataFrame
    sheet_name: str


@dataclass
class SavReadResult:
    """Container for respondent data and labels read from an SPSS SAV file."""

    dataframe: pd.DataFrame
    question_labels: dict[str, str]
    source_answer_choices: dict[str, list[str]]
    sheet_name: str = "SAV data"
    collapsed_multi_response_groups: int = 0


@dataclass
class _SavMultiResponseGroup:
    """One logical multi-select question spread across several SAV columns."""

    variable: str
    question_label: str
    source_variables: list[str]
    answer_choices: list[str]
    choice_by_source_variable: dict[str, str]
    selected_values_by_variable: dict[str, set[str]]


def get_excel_sheet_names(uploaded_file) -> list[str]:
    """Return workbook sheet names from an uploaded Excel file."""
    content = uploaded_file.getvalue()
    workbook = pd.ExcelFile(BytesIO(content))
    if not workbook.sheet_names:
        raise ValueError("The workbook does not contain any sheets.")
    return workbook.sheet_names


def read_excel_upload(uploaded_file, sheet_name: str | None = None) -> ExcelReadResult:
    """Read a selected worksheet from an uploaded Excel file into a raw dataframe."""
    content = uploaded_file.getvalue()
    workbook = pd.ExcelFile(BytesIO(content))
    if not workbook.sheet_names:
        raise ValueError("The workbook does not contain any sheets.")
    selected_sheet = sheet_name or workbook.sheet_names[0]
    if selected_sheet not in workbook.sheet_names:
        raise ValueError(f"Sheet `{selected_sheet}` was not found in the workbook.")
    dataframe = pd.read_excel(BytesIO(content), sheet_name=selected_sheet, header=None, dtype=object)
    return ExcelReadResult(dataframe=dataframe, sheet_name=selected_sheet)


def _extract_sav_question_labels(dataframe: pd.DataFrame, metadata: Any) -> dict[str, str]:
    """Return SAV variable labels keyed by dataframe column name."""
    column_names = list(getattr(metadata, "column_names", [])) or list(dataframe.columns)
    column_labels = list(getattr(metadata, "column_labels", [])) or []
    labels_by_column = {
        normalize_text(column): normalize_text(label) or normalize_text(column)
        for column, label in zip(column_names, column_labels)
        if normalize_text(column)
    }
    return {
        normalize_text(column): labels_by_column.get(normalize_text(column), normalize_text(column))
        for column in dataframe.columns
    }


def _extract_sav_answer_choices(dataframe: pd.DataFrame, metadata: Any) -> dict[str, list[str]]:
    """Return all SAV value labels keyed by dataframe column name."""
    source_choices: dict[str, list[str]] = {}
    dataframe_columns = {normalize_text(column) for column in dataframe.columns}
    variable_value_labels = getattr(metadata, "variable_value_labels", {}) or {}
    for variable, value_labels in variable_value_labels.items():
        variable_name = normalize_text(variable)
        if variable_name not in dataframe_columns or not isinstance(value_labels, dict):
            continue
        choices: list[str] = []
        for label in value_labels.values():
            normalized_label = normalize_text(label)
            if normalized_label and normalized_label not in choices:
                choices.append(normalized_label)
        if choices:
            source_choices[variable_name] = choices
    return source_choices


MULTI_RESPONSE_LABEL_HINTS = [
    "select all that apply",
    "choose all that apply",
    "check all that apply",
    "mark all that apply",
    "select all",
    "choose all",
    "check all",
    "multiple response",
    "multiple responses",
    "multiple answer",
    "multiple answers",
    "multi-select",
]

GENERIC_DICHOTOMY_LABELS = {
    "0",
    "0.0",
    "1",
    "1.0",
    "checked",
    "mentioned",
    "no",
    "not checked",
    "not mentioned",
    "not selected",
    "selected",
    "unchecked",
    "unselected",
    "yes",
    "false",
    "true",
}

NEGATIVE_DICHOTOMY_LABELS = {
    "0",
    "0.0",
    "false",
    "no",
    "not checked",
    "not mentioned",
    "not selected",
    "unchecked",
    "unselected",
}

POSITIVE_DICHOTOMY_LABELS = {
    "1",
    "1.0",
    "checked",
    "mentioned",
    "selected",
    "true",
    "yes",
}


def _normalized_variable_value_labels(metadata: Any) -> dict[str, dict[Any, str]]:
    """Return value labels keyed by normalized variable name."""
    variable_value_labels = getattr(metadata, "variable_value_labels", {}) or {}
    return {
        normalize_text(variable): labels
        for variable, labels in variable_value_labels.items()
        if normalize_text(variable) and isinstance(labels, dict)
    }


def _normalize_mr_set(mr_set: Any) -> dict[str, Any]:
    """Coerce pyreadstat MR-set metadata into a plain dictionary."""
    if isinstance(mr_set, dict):
        return mr_set
    return {
        "type": getattr(mr_set, "type", ""),
        "is_dichotomy": getattr(mr_set, "is_dichotomy", False),
        "counted_value": getattr(mr_set, "counted_value", None),
        "label": getattr(mr_set, "label", ""),
        "variable_list": getattr(mr_set, "variable_list", []),
    }


def _clean_group_variable_name(raw_name: str, fallback: str, existing_columns: set[str]) -> str:
    """Return a stable combined-column name that does not collide with kept columns."""
    candidate = normalize_text(raw_name).lstrip("$#")
    if not candidate:
        candidate = fallback
    candidate = re.sub(r"\s+", "_", candidate)
    candidate = re.sub(r"[^0-9A-Za-z_]+", "_", candidate).strip("_")
    if not candidate:
        candidate = fallback

    base_candidate = candidate
    suffix = 2
    while candidate in existing_columns:
        candidate = f"{base_candidate}_{suffix}"
        suffix += 1
    return candidate


def _numbered_variable_base(variable: str) -> str | None:
    """Return the shared base for Qualtrics-style checkbox variables."""
    match = re.match(r"^(.+)_\d+$", normalize_text(variable))
    if not match:
        return None
    return match.group(1)


def _has_multi_response_hint(label: str) -> bool:
    """Return whether label text suggests a multi-select question."""
    label_lower = normalize_text(label).lower()
    return any(hint in label_lower for hint in MULTI_RESPONSE_LABEL_HINTS)


def _clean_question_stem(label: str) -> str:
    """Normalize a grouped question stem without dropping meaningful punctuation."""
    cleaned = re.sub(r"\s+", " ", normalize_text(label))
    return cleaned.strip(" -:;")


def _clean_option_label(label: str) -> str:
    """Normalize an answer option found inside a SAV variable label."""
    cleaned = re.sub(r"\s+", " ", normalize_text(label))
    cleaned = cleaned.strip(" -:;,.")
    cleaned = re.sub(r"^(?:selected\s+choice|choice)\b\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -:;,.")


def _split_multiselect_label(label: str) -> tuple[str, str] | None:
    """Split a label such as `Question? Select all. Option` into stem and option."""
    normalized_label = normalize_text(label)
    if not normalized_label or not _has_multi_response_hint(normalized_label):
        return None

    hint_pattern = "|".join(re.escape(hint) for hint in MULTI_RESPONSE_LABEL_HINTS)
    pattern = re.compile(
        rf"(?P<stem>.+?(?:{hint_pattern})[.?:!]?)\s+(?P<option>.+)$",
        re.IGNORECASE,
    )
    match = pattern.match(normalized_label)
    if not match:
        return None

    stem = _clean_question_stem(match.group("stem"))
    option = _clean_option_label(match.group("option"))
    if not stem or not option:
        return None
    return stem, option


def _common_prefix(values: list[str]) -> str:
    """Return the character prefix shared by all values."""
    if not values:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while prefix and not value.startswith(prefix):
            prefix = prefix[:-1]
    return prefix


def _split_group_labels_by_common_prefix(labels: list[str]) -> tuple[str, list[str]] | None:
    """Find a shared question stem and option suffixes across repeated labels."""
    normalized_labels = [normalize_text(label) for label in labels]
    if len(normalized_labels) < 2 or not all(normalized_labels):
        return None

    prefix = _common_prefix(normalized_labels)
    if len(prefix) < 24:
        return None

    split_at = -1
    for delimiter in [". ", "? ", "! ", ": ", " - "]:
        index = prefix.rfind(delimiter)
        if index > split_at:
            split_at = index + len(delimiter)
    if split_at <= 0:
        return None

    stem = _clean_question_stem(prefix[:split_at])
    if not stem or not _has_multi_response_hint(stem):
        return None

    options = [_clean_option_label(label[split_at:]) for label in normalized_labels]
    if any(not option for option in options):
        return None
    return stem, options


def _split_numbered_multiselect_labels(labels: list[str]) -> tuple[str, list[str]] | None:
    """Return one question stem and option labels for a numbered checkbox group."""
    explicit_splits = [_split_multiselect_label(label) for label in labels]
    if all(split is not None for split in explicit_splits):
        stems = [split[0] for split in explicit_splits if split is not None]
        options = [split[1] for split in explicit_splits if split is not None]
        if len(set(stems)) == 1:
            return stems[0], options

    return _split_group_labels_by_common_prefix(labels)


def _selected_values_for_variable(
    variable: str,
    choice_label: str,
    value_labels_by_variable: dict[str, dict[Any, str]],
    counted_value: Any = None,
) -> set[str]:
    """Build the selected-value aliases for one dichotomy source column."""
    selected_values: set[str] = set()
    value_labels = value_labels_by_variable.get(variable, {})
    if counted_value is not None:
        selected_values.add(normalize_text(counted_value))
        try:
            selected_values.add(normalize_text(float(counted_value)))
        except (TypeError, ValueError):
            pass
        if counted_value in value_labels:
            selected_values.add(normalize_text(value_labels[counted_value]))
        else:
            for value, label in value_labels.items():
                if normalize_text(value) == normalize_text(counted_value):
                    selected_values.add(normalize_text(label))

    if not selected_values:
        selected_values.add(choice_label)
        selected_values.update(POSITIVE_DICHOTOMY_LABELS)

    return {value for value in selected_values if value}


def _preferred_selected_value_label(
    variable: str,
    value_labels_by_variable: dict[str, dict[Any, str]],
    counted_value: Any = None,
) -> str:
    """Return a non-generic value label for the selected state when available."""
    value_labels = value_labels_by_variable.get(variable, {})
    candidates: list[str] = []
    if counted_value is not None:
        if counted_value in value_labels:
            candidates.append(normalize_text(value_labels[counted_value]))
        for value, label in value_labels.items():
            if normalize_text(value) == normalize_text(counted_value):
                candidates.append(normalize_text(label))
    candidates.extend(normalize_text(label) for label in value_labels.values())

    for candidate in candidates:
        if candidate and candidate.lower() not in GENERIC_DICHOTOMY_LABELS:
            return candidate
    return ""


def _option_from_variable_label(variable_label: str, question_label: str) -> str:
    """Extract a checkbox option from a variable label when possible."""
    label = normalize_text(variable_label)
    question = normalize_text(question_label)
    if not label:
        return ""

    split_label = _split_multiselect_label(label)
    if split_label is not None:
        return split_label[1]

    if question and label.startswith(question):
        return _clean_option_label(label[len(question):])

    return label if label != question else ""


def _is_selected_multiselect_value(
    value: Any,
    choice_label: str,
    selected_values: set[str],
) -> bool:
    """Return whether one SAV dichotomy column marks its option as selected."""
    normalized_value = normalize_text(value)
    if not normalized_value:
        return False
    value_lower = normalized_value.lower()
    if value_lower in NEGATIVE_DICHOTOMY_LABELS:
        return False
    if normalized_value in selected_values:
        return True
    if normalize_text(choice_label) and normalized_value == normalize_text(choice_label):
        return True
    if value_lower in POSITIVE_DICHOTOMY_LABELS:
        return True
    return not selected_values and value_lower not in NEGATIVE_DICHOTOMY_LABELS


def _build_sav_mr_set_groups(
    dataframe: pd.DataFrame,
    metadata: Any,
    question_labels: dict[str, str],
) -> list[_SavMultiResponseGroup]:
    """Build groups from native SPSS multiple-response metadata."""
    mr_sets = getattr(metadata, "mr_sets", {}) or {}
    if not isinstance(mr_sets, dict):
        return []

    dataframe_columns = {normalize_text(column) for column in dataframe.columns}
    value_labels_by_variable = _normalized_variable_value_labels(metadata)
    groups: list[_SavMultiResponseGroup] = []

    for set_name, raw_set in mr_sets.items():
        mr_set = _normalize_mr_set(raw_set)
        source_variables = [
            normalize_text(variable)
            for variable in mr_set.get("variable_list", [])
            if normalize_text(variable) in dataframe_columns
        ]
        if len(source_variables) < 2:
            continue
        if not bool(mr_set.get("is_dichotomy")) and normalize_text(mr_set.get("type")).upper() != "D":
            continue

        fallback_base = _numbered_variable_base(source_variables[0]) or normalize_text(set_name).lstrip("$#")
        existing_columns = dataframe_columns.difference(source_variables)
        variable = _clean_group_variable_name(normalize_text(set_name), fallback_base, existing_columns)
        question_label = normalize_text(mr_set.get("label")) or question_labels.get(source_variables[0], variable)
        split_question = _split_multiselect_label(question_label)
        if split_question is not None:
            question_label = split_question[0]

        counted_value = mr_set.get("counted_value")
        answer_choices: list[str] = []
        aligned_source_variables: list[str] = []
        choice_by_source_variable: dict[str, str] = {}
        selected_values_by_variable: dict[str, set[str]] = {}
        for source_variable in source_variables:
            variable_label = question_labels.get(source_variable, source_variable)
            choice_label = (
                _option_from_variable_label(variable_label, question_label)
                or _preferred_selected_value_label(source_variable, value_labels_by_variable, counted_value)
                or source_variable
            )
            choice_label = _clean_option_label(choice_label)
            if not choice_label:
                continue
            aligned_source_variables.append(source_variable)
            choice_by_source_variable[source_variable] = choice_label
            if choice_label not in answer_choices:
                answer_choices.append(choice_label)
            selected_values_by_variable[source_variable] = _selected_values_for_variable(
                source_variable,
                choice_label,
                value_labels_by_variable,
                counted_value,
            )

        if len(answer_choices) < 2:
            continue
        groups.append(
            _SavMultiResponseGroup(
                variable=variable,
                question_label=_clean_question_stem(question_label) or variable,
                source_variables=aligned_source_variables,
                answer_choices=answer_choices,
                choice_by_source_variable=choice_by_source_variable,
                selected_values_by_variable=selected_values_by_variable,
            )
        )

    return groups


def _build_label_based_sav_multiselect_groups(
    dataframe: pd.DataFrame,
    metadata: Any,
    question_labels: dict[str, str],
    excluded_variables: set[str],
) -> list[_SavMultiResponseGroup]:
    """Infer checkbox groups when the SAV lacks native multiple-response metadata."""
    grouped_variables: dict[str, list[str]] = {}
    for column in dataframe.columns:
        variable = normalize_text(column)
        if variable in excluded_variables:
            continue
        base = _numbered_variable_base(variable)
        if not base:
            continue
        grouped_variables.setdefault(base, []).append(variable)

    dataframe_columns = {normalize_text(column) for column in dataframe.columns}
    value_labels_by_variable = _normalized_variable_value_labels(metadata)
    groups: list[_SavMultiResponseGroup] = []

    for base, source_variables in grouped_variables.items():
        if len(source_variables) < 2:
            continue
        labels = [question_labels.get(variable, variable) for variable in source_variables]
        split_labels = _split_numbered_multiselect_labels(labels)
        if split_labels is None:
            continue

        question_label, answer_choices = split_labels
        existing_columns = dataframe_columns.difference(source_variables)
        variable = _clean_group_variable_name(base, base, existing_columns)
        choice_by_source_variable = {
            source_variable: choice_label
            for source_variable, choice_label in zip(source_variables, answer_choices)
        }
        unique_answer_choices: list[str] = []
        for choice_label in answer_choices:
            if choice_label not in unique_answer_choices:
                unique_answer_choices.append(choice_label)
        selected_values_by_variable = {
            source_variable: _selected_values_for_variable(
                source_variable,
                choice_by_source_variable[source_variable],
                value_labels_by_variable,
            )
            for source_variable in source_variables
        }
        groups.append(
            _SavMultiResponseGroup(
                variable=variable,
                question_label=question_label,
                source_variables=source_variables,
                answer_choices=unique_answer_choices,
                choice_by_source_variable=choice_by_source_variable,
                selected_values_by_variable=selected_values_by_variable,
            )
        )

    return groups


def _collapse_sav_multi_response_groups(
    dataframe: pd.DataFrame,
    groups: list[_SavMultiResponseGroup],
) -> pd.DataFrame:
    """Replace checkbox-set source columns with combined multi-select columns."""
    if not groups:
        return dataframe

    group_by_first_variable = {group.source_variables[0]: group for group in groups}
    grouped_variables = {
        variable
        for group in groups
        for variable in group.source_variables
    }
    collapsed_columns: dict[str, Any] = {}

    for column in dataframe.columns:
        variable = normalize_text(column)
        if variable in group_by_first_variable:
            group = group_by_first_variable[variable]
            combined_values = []
            for row_values in dataframe[group.source_variables].itertuples(index=False, name=None):
                selected_choices = []
                for source_variable, value in zip(group.source_variables, row_values):
                    choice_label = group.choice_by_source_variable.get(source_variable, source_variable)
                    if not _is_selected_multiselect_value(
                        value,
                        choice_label,
                        group.selected_values_by_variable.get(source_variable, set()),
                    ):
                        continue
                    if choice_label not in selected_choices:
                        selected_choices.append(choice_label)
                combined_values.append("; ".join(selected_choices))
            collapsed_columns[group.variable] = combined_values
        if variable in grouped_variables:
            continue
        collapsed_columns[variable] = dataframe[variable].tolist()

    return pd.DataFrame(collapsed_columns, index=dataframe.index)


def _normalize_sav_multi_response_sets(
    dataframe: pd.DataFrame,
    metadata: Any,
    question_labels: dict[str, str],
    source_answer_choices: dict[str, list[str]],
) -> tuple[pd.DataFrame, dict[str, str], dict[str, list[str]], int]:
    """Collapse SAV checkbox sets into regular multi-select columns."""
    mr_set_groups = _build_sav_mr_set_groups(dataframe, metadata, question_labels)
    mr_set_variables = {
        variable
        for group in mr_set_groups
        for variable in group.source_variables
    }
    label_groups = _build_label_based_sav_multiselect_groups(
        dataframe,
        metadata,
        question_labels,
        excluded_variables=mr_set_variables,
    )
    groups = mr_set_groups + label_groups
    if not groups:
        return dataframe, question_labels, source_answer_choices, 0

    collapsed_df = _collapse_sav_multi_response_groups(dataframe, groups)
    grouped_variables = {
        variable
        for group in groups
        for variable in group.source_variables
    }
    group_lookup = {group.variable: group for group in groups}

    normalized_question_labels = {
        column: group_lookup[column].question_label if column in group_lookup else question_labels.get(column, column)
        for column in collapsed_df.columns
    }
    normalized_source_choices = {
        column: group_lookup[column].answer_choices if column in group_lookup else list(source_answer_choices.get(column, []))
        for column in collapsed_df.columns
        if column in group_lookup or source_answer_choices.get(column)
    }

    return collapsed_df, normalized_question_labels, normalized_source_choices, len(groups)


def read_sav_upload(uploaded_file) -> SavReadResult:
    """Read an uploaded SPSS SAV file and preserve variable/value labels."""
    try:
        import pyreadstat
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise ImportError(
            "SAV support requires `pyreadstat`. Install dependencies with `pip install -r requirements.txt`."
        ) from exc

    content = uploaded_file.getvalue()
    with NamedTemporaryFile(suffix=".sav") as temp_file:
        temp_file.write(content)
        temp_file.flush()
        dataframe, metadata = pyreadstat.read_sav(
            temp_file.name,
            apply_value_formats=True,
            formats_as_category=False,
        )

    dataframe.columns = [normalize_text(column) for column in dataframe.columns]
    question_labels = _extract_sav_question_labels(dataframe, metadata)
    source_answer_choices = _extract_sav_answer_choices(dataframe, metadata)
    (
        dataframe,
        question_labels,
        source_answer_choices,
        collapsed_multi_response_groups,
    ) = _normalize_sav_multi_response_sets(
        dataframe,
        metadata,
        question_labels,
        source_answer_choices,
    )
    return SavReadResult(
        dataframe=dataframe,
        question_labels=question_labels,
        source_answer_choices=source_answer_choices,
        collapsed_multi_response_groups=collapsed_multi_response_groups,
    )
