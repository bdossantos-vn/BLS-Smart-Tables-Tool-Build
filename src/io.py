"""I/O helpers for reading Qualtrics exports."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import pandas as pd


@dataclass
class ExcelReadResult:
    """Container for raw workbook data."""

    dataframe: pd.DataFrame
    sheet_name: str


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
