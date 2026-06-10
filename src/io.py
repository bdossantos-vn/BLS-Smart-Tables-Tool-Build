"""I/O helpers for reading Qualtrics exports."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from tempfile import NamedTemporaryFile
from typing import Any

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
    return SavReadResult(
        dataframe=dataframe,
        question_labels=question_labels,
        source_answer_choices=source_answer_choices,
    )
