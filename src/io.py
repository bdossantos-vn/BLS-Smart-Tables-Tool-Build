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


def read_excel_upload(uploaded_file) -> ExcelReadResult:
    """Read the first worksheet from an uploaded Excel file into a raw dataframe."""
    content = uploaded_file.getvalue()
    workbook = pd.ExcelFile(BytesIO(content))
    if not workbook.sheet_names:
        raise ValueError("The workbook does not contain any sheets.")
    sheet_name = workbook.sheet_names[0]
    dataframe = pd.read_excel(BytesIO(content), sheet_name=sheet_name, header=None, dtype=object)
    return ExcelReadResult(dataframe=dataframe, sheet_name=sheet_name)
