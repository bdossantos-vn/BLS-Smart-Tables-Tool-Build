"""Excel export helpers for branded BLS Smart Tables workbooks."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


VN_BLACK = "000000"
VN_WHITE = "FFFFFF"
VN_RED = "FF005C"
VN_ORANGE = "FF6927"
VN_YELLOW = "FFC227"
VN_LIGHT_GREEN = "E8F6EA"
VN_LIGHT_GRAY = "F4F5F8"


def _apply_header_style(cell, fill_color: str, font_color: str = VN_WHITE, bold: bool = True) -> None:
    """Apply a consistent header style to one Excel cell."""
    cell.fill = PatternFill("solid", fgColor=fill_color)
    cell.font = Font(color=font_color, bold=bold, name="Proxima Nova")
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _apply_body_style(cell, bold: bool = False, fill_color: str | None = None, wrap: bool = False) -> None:
    """Apply a consistent body style to one Excel cell."""
    if fill_color:
        cell.fill = PatternFill("solid", fgColor=fill_color)
    cell.font = Font(color=VN_BLACK, bold=bold, name="Proxima Nova")
    cell.alignment = Alignment(vertical="top", wrap_text=wrap)
    thin = Side(style="thin", color="D9D9D9")
    cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)


def _set_sheet_columns(worksheet, group_count: int) -> None:
    """Set practical column widths for a question-table worksheet."""
    worksheet.column_dimensions["A"].width = 34
    start_column = 2
    for group_index in range(group_count):
        worksheet.column_dimensions[get_column_letter(start_column + (group_index * 3))].width = 11
        worksheet.column_dimensions[get_column_letter(start_column + (group_index * 3) + 1)].width = 9
        worksheet.column_dimensions[get_column_letter(start_column + (group_index * 3) + 2)].width = 12


def _set_topline_columns(worksheet) -> None:
    """Set practical column widths for the topline worksheet."""
    widths = {
        "A": 34,
        "B": 26,
        "C": 20,
        "D": 20,
        "E": 12,
        "F": 12,
        "G": 12,
        "H": 12,
        "I": 10,
        "J": 18,
        "K": 48,
    }
    for column_letter, width in widths.items():
        worksheet.column_dimensions[column_letter].width = width


def _write_topline_sheet(workbook, topline_sheet) -> None:
    """Write the flat topline worksheet.

    Inputs:
        workbook: OpenPyXL workbook object.
        topline_sheet: Flat topline payload built by the table service.

    Outputs:
        Adds one `Topline` worksheet to the workbook.
    """
    worksheet = workbook.create_sheet(title="Topline")
    _set_topline_columns(worksheet)

    current_row = 1
    worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=11)
    title_cell = worksheet.cell(row=current_row, column=1, value="Viral Nation | Topline")
    _apply_header_style(title_cell, VN_BLACK)
    current_row += 2

    headers = [
        "Question",
        "Response",
        "Banner",
        "Segment",
        "Control N",
        "Control %",
        "Test N",
        "Test %",
        "Lift",
        "Sig Test",
        "Notes",
    ]
    for column_index, header in enumerate(headers, start=1):
        header_cell = worksheet.cell(row=current_row, column=column_index, value=header)
        _apply_header_style(header_cell, VN_YELLOW, font_color=VN_BLACK)
    current_row += 1

    rows = list(getattr(topline_sheet, "rows", []))
    if not rows:
        worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=11)
        empty_cell = worksheet.cell(
            row=current_row,
            column=1,
            value="No topline rows were generated for the current project setup.",
        )
        _apply_body_style(empty_cell, fill_color=VN_LIGHT_GRAY)
        worksheet.freeze_panes = "A4"
        return

    for row in rows:
        values = [
            row.get("Question", ""),
            row.get("Response", ""),
            row.get("Banner", ""),
            row.get("Segment", ""),
            row.get("Control N"),
            row.get("Control %"),
            row.get("Test N"),
            row.get("Test %"),
            row.get("Lift"),
            row.get("Sig Test", ""),
            row.get("Notes", ""),
        ]
        for column_index, value in enumerate(values, start=1):
            cell = worksheet.cell(row=current_row, column=column_index, value=value)
            _apply_body_style(cell, wrap=column_index in {1, 2, 11})
            if column_index in {6, 8, 9} and value is not None:
                cell.number_format = "0%"
        current_row += 1

    worksheet.freeze_panes = "A4"


def export_workbook_to_excel_bytes(
    workbook_package: dict,
    uploaded_filename: str | None = None,
) -> bytes:
    """Convert the generated workbook package into branded Excel bytes.

    Inputs:
        workbook_package: Structured workbook content built by the table
        generator.
        uploaded_filename: Optional source filename, used only by the calling
        layer for naming the final download.

    Outputs:
        In-memory Excel bytes ready for a Streamlit download button.
    """
    workbook = Workbook()
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    topline_sheet = workbook_package.get("topline_sheet")
    if topline_sheet is not None:
        _write_topline_sheet(workbook, topline_sheet)

    for sheet in workbook_package.get("sheets", []):
        worksheet = workbook.create_sheet(title=str(sheet.name)[:31] or "Sheet1")
        _set_sheet_columns(worksheet, len(sheet.groups))

        current_row = 1
        worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=max(4, 1 + (len(sheet.groups) * 3)))
        title_cell = worksheet.cell(row=current_row, column=1, value=f"Viral Nation | {sheet.banner_name}")
        _apply_header_style(title_cell, VN_BLACK)
        current_row += 1

        subtitle = "Banner Levels: " + (" > ".join(sheet.levels) if sheet.levels else "All Tables")
        worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=max(4, 1 + (len(sheet.groups) * 3)))
        subtitle_cell = worksheet.cell(row=current_row, column=1, value=subtitle)
        _apply_body_style(subtitle_cell, bold=True, fill_color=VN_LIGHT_GRAY)
        current_row += 2

        for table in sheet.tables:
            worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=max(4, 1 + (len(sheet.groups) * 3)))
            question_cell = worksheet.cell(row=current_row, column=1, value=f"{table.variable}: {table.question_label}")
            _apply_header_style(question_cell, VN_RED)
            current_row += 1

            for section in table.sections:
                worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=max(4, 1 + (len(sheet.groups) * 3)))
                section_cell = worksheet.cell(row=current_row, column=1, value=section["label"])
                _apply_header_style(section_cell, VN_ORANGE, font_color=VN_WHITE)
                current_row += 1

                worksheet.cell(row=current_row, column=1, value="Response")
                _apply_header_style(worksheet.cell(row=current_row, column=1), VN_YELLOW, font_color=VN_BLACK)
                for group_index, group in enumerate(sheet.groups):
                    start_column = 2 + (group_index * 3)
                    worksheet.merge_cells(
                        start_row=current_row,
                        start_column=start_column,
                        end_row=current_row,
                        end_column=start_column + 2,
                    )
                    group_cell = worksheet.cell(row=current_row, column=start_column, value=group["label"])
                    _apply_header_style(group_cell, VN_YELLOW, font_color=VN_BLACK)
                current_row += 1

                worksheet.cell(row=current_row, column=1, value="Metric")
                _apply_body_style(worksheet.cell(row=current_row, column=1), bold=True, fill_color=VN_LIGHT_GRAY)
                for group_index in range(len(sheet.groups)):
                    start_column = 2 + (group_index * 3)
                    for offset, label in enumerate(["N", "%", "Sig"]):
                        metric_cell = worksheet.cell(row=current_row, column=start_column + offset, value=label)
                        _apply_body_style(metric_cell, bold=True, fill_color=VN_LIGHT_GRAY)
                        metric_cell.alignment = Alignment(horizontal="center", vertical="center")
                current_row += 1

                worksheet.cell(row=current_row, column=1, value="Base N")
                _apply_body_style(worksheet.cell(row=current_row, column=1), bold=True, fill_color=VN_LIGHT_GRAY)
                for group_index, denominator in enumerate(section["base_denominators"]):
                    start_column = 2 + (group_index * 3)
                    base_n_cell = worksheet.cell(row=current_row, column=start_column, value=denominator)
                    _apply_body_style(base_n_cell, bold=True, fill_color=VN_LIGHT_GRAY)
                    _apply_body_style(worksheet.cell(row=current_row, column=start_column + 1), fill_color=VN_LIGHT_GRAY)
                    _apply_body_style(worksheet.cell(row=current_row, column=start_column + 2), fill_color=VN_LIGHT_GRAY)
                current_row += 1

                for row in section["rows"]:
                    label_fill = VN_LIGHT_GRAY if row.get("kind") == "net" else None
                    row_label = f"{row['label']} (Net)" if row.get("kind") == "net" else row["label"]
                    label_cell = worksheet.cell(row=current_row, column=1, value=row_label)
                    _apply_body_style(label_cell, bold=bool(row.get("kind") == "net"), fill_color=label_fill, wrap=True)
                    for group_index, (count, percentage, sig_text) in enumerate(
                        zip(row["counts"], row["percentages"], row["sig_letters"])
                    ):
                        start_column = 2 + (group_index * 3)
                        count_cell = worksheet.cell(row=current_row, column=start_column, value=count)
                        _apply_body_style(count_cell, fill_color=label_fill)

                        percent_cell = worksheet.cell(
                            row=current_row,
                            column=start_column + 1,
                            value=(percentage if percentage is not None else None),
                        )
                        _apply_body_style(percent_cell, fill_color=label_fill)
                        if percentage is not None:
                            percent_cell.number_format = "0%"

                        sig_cell = worksheet.cell(row=current_row, column=start_column + 2, value=sig_text)
                        _apply_body_style(sig_cell, fill_color=label_fill)
                        sig_cell.alignment = Alignment(horizontal="center", vertical="center")
                    current_row += 1

                current_row += 1

        worksheet.freeze_panes = "B4"

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def export_tables_to_excel_bytes(tables: dict) -> bytes:
    """Compatibility export helper for older placeholder dataframe payloads.

    Inputs:
        A mapping of sheet names to pandas dataframes.

    Outputs:
        In-memory Excel bytes for legacy placeholder flows.
    """
    from pandas import ExcelWriter

    output = BytesIO()
    with ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, dataframe in tables.items():
            safe_name = str(sheet_name)[:31] or "Sheet1"
            dataframe.to_excel(writer, sheet_name=safe_name, index=False)
    return output.getvalue()
