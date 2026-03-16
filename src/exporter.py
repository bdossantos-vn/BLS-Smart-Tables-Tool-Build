"""Excel export helpers."""

from __future__ import annotations

from io import BytesIO

import pandas as pd


def export_tables_to_excel_bytes(tables: dict[str, pd.DataFrame]) -> bytes:
    """Export a workbook payload into in-memory Excel bytes."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, dataframe in tables.items():
            safe_name = str(sheet_name)[:31] or "Sheet1"
            dataframe.to_excel(writer, sheet_name=safe_name, index=False)
    return output.getvalue()
