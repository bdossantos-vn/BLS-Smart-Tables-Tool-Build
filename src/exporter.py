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
    worksheet.column_dimensions["A"].width = 42
    worksheet.column_dimensions["B"].width = 20
    for column_index in range(3, 3 + max(group_count, 1)):
        worksheet.column_dimensions[get_column_letter(column_index)].width = 14


def _set_topline_columns(worksheet) -> None:
    """Set practical column widths for the topline worksheet."""
    widths = {
        "A": 4,
        "B": 40,
        "C": 12,
        "D": 12,
        "E": 12,
        "F": 6,
        "G": 56,
        "H": 8,
        "I": 8,
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
    worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=9)
    title_cell = worksheet.cell(row=current_row, column=1, value="Viral Nation | Topline")
    _apply_header_style(title_cell, VN_BLACK)
    current_row = 2
    worksheet.cell(row=current_row, column=2, value="Observations:")
    _apply_body_style(worksheet.cell(row=current_row, column=2), bold=True)
    current_row = 9

    results_cell = worksheet.cell(row=current_row, column=3, value="RESULTS")
    _apply_header_style(results_cell, VN_RED)
    current_row = 11

    rows = list(getattr(topline_sheet, "rows", []))
    comparison_variable_label = "Comparison"
    left_group_label = "Group 1"
    right_group_label = "Group 2"
    if rows:
        comparison_variable_label = rows[0].get("Comparison Variable", comparison_variable_label)
        left_group_label = rows[0].get("Left Label", left_group_label)
        right_group_label = rows[0].get("Right Label", right_group_label)

    header_values = {
        (11, 2): comparison_variable_label,
        (11, 3): left_group_label,
        (11, 4): right_group_label,
        (11, 5): "Lift",
        (12, 2): "Base Size",
        (12, 7): "NOTES",
    }
    for (row_index, column_index), value in header_values.items():
        cell = worksheet.cell(row=row_index, column=column_index, value=value)
        if row_index == 11:
            _apply_body_style(cell, bold=True, fill_color=VN_LIGHT_GRAY)
        else:
            _apply_body_style(cell, bold=True, fill_color=VN_LIGHT_GRAY if column_index != 7 else None)

    if not rows:
        worksheet.merge_cells(start_row=14, start_column=2, end_row=14, end_column=7)
        empty_cell = worksheet.cell(
            row=14,
            column=2,
            value="No topline rows were generated for the current project setup.",
        )
        _apply_body_style(empty_cell, fill_color=VN_LIGHT_GRAY)
        worksheet.freeze_panes = "A4"
        return

    base_row = rows[0]
    worksheet.cell(row=12, column=3, value=base_row.get("Left Base"))
    _apply_body_style(worksheet.cell(row=12, column=3))
    worksheet.cell(row=12, column=4, value=base_row.get("Right Base"))
    _apply_body_style(worksheet.cell(row=12, column=4))
    worksheet.cell(row=12, column=5, value=None)
    _apply_body_style(worksheet.cell(row=12, column=5), fill_color=VN_LIGHT_GRAY)

    current_row = 13
    for row in rows:
        row_label = row.get("Question", "")
        response = row.get("Response", "")
        if response:
            row_label = f"{row_label} | {response}"
        label_cell = worksheet.cell(row=current_row, column=2, value=row_label)
        _apply_body_style(label_cell, wrap=True)

        left_pct = row.get("Left %")
        left_sig = str(row.get("Left Sig", "") or "")
        left_display = ""
        if left_pct is not None:
            left_display = f"{left_pct:.0%}{left_sig}"
        left_pct_cell = worksheet.cell(row=current_row, column=3, value=left_display)
        _apply_body_style(left_pct_cell)
        left_pct_cell.alignment = Alignment(horizontal="center", vertical="top")

        right_pct = row.get("Right %")
        right_sig = str(row.get("Right Sig", "") or "")
        right_display = ""
        if right_pct is not None:
            right_display = f"{right_pct:.0%}{right_sig}"
        right_pct_cell = worksheet.cell(row=current_row, column=4, value=right_display)
        _apply_body_style(right_pct_cell)
        right_pct_cell.alignment = Alignment(horizontal="center", vertical="top")

        lift_value = row.get("Lift")
        lift_cell = worksheet.cell(row=current_row, column=5, value=lift_value)
        _apply_body_style(lift_cell, fill_color=VN_LIGHT_GRAY)
        if lift_value is not None:
            lift_cell.number_format = "0%"

        notes_cell = worksheet.cell(row=current_row, column=7, value=row.get("Notes", ""))
        _apply_body_style(notes_cell, wrap=True)
        current_row += 1

    worksheet.freeze_panes = "B11"


def _write_banner_sheet(workbook, sheet) -> None:
    """Write one banner worksheet in an analyst-friendly table format.

    Inputs:
        workbook: OpenPyXL workbook object.
        sheet: One banner-sheet payload created by the table service.

    Outputs:
        Adds one formatted worksheet to the workbook.
    """
    worksheet = workbook.create_sheet(title=str(sheet.name)[:31] or "Sheet1")
    _set_sheet_columns(worksheet, len(sheet.groups))

    current_row = 1
    visible_groups = list(sheet.groups)
    max_end_column = 2 + len(visible_groups)

    worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=max_end_column)
    title_cell = worksheet.cell(row=current_row, column=1, value=sheet.banner_name)
    _apply_header_style(title_cell, VN_BLACK)
    current_row += 1

    worksheet.cell(row=current_row, column=1, value="filtered by")
    _apply_body_style(worksheet.cell(row=current_row, column=1))
    current_row += 1
    worksheet.cell(row=current_row, column=1, value="FILTER: ALL")
    _apply_body_style(worksheet.cell(row=current_row, column=1))
    current_row += 2

    banner_descriptor = " > ".join(sheet.levels) if sheet.levels else "All Tables"
    if visible_groups:
        worksheet.merge_cells(start_row=current_row, start_column=3, end_row=current_row, end_column=max_end_column)
        descriptor_cell = worksheet.cell(row=current_row, column=3, value=banner_descriptor)
        _apply_header_style(descriptor_cell, VN_ORANGE)
    current_row += 1

    data_start_column = 3
    data_columns: list[int] = []
    for index, _group in enumerate(visible_groups):
        data_columns.append(data_start_column + index)

    level_rows = max(1, len(sheet.levels))
    total_group_indexes = [index for index, group in enumerate(visible_groups) if group["label"] == "Total"]
    non_total_indexes = [index for index, group in enumerate(visible_groups) if group["label"] != "Total"]

    if total_group_indexes:
        total_column = data_columns[total_group_indexes[0]]
        worksheet.merge_cells(
            start_row=current_row,
            start_column=total_column,
            end_row=current_row + level_rows - 1,
            end_column=total_column,
        )
        total_cell = worksheet.cell(row=current_row, column=total_column, value="Total")
        _apply_body_style(total_cell, bold=True, fill_color=VN_LIGHT_GRAY)
        total_cell.alignment = Alignment(horizontal="center", vertical="center")

    if sheet.levels and non_total_indexes:
        for level_index, level_name in enumerate(sheet.levels):
            header_row = current_row + level_index
            start_group = None
            previous_value = None
            for position, group_index in enumerate(non_total_indexes):
                group = visible_groups[group_index]
                current_value = normalize_text(group.get("values", {}).get(level_name))
                if not current_value:
                    split_parts = [
                        part.strip()
                        for part in normalize_text(group.get("label")).split("|")
                        if part.strip()
                    ]
                    if level_index < len(split_parts):
                        current_value = split_parts[level_index]
                if start_group is None:
                    start_group = group_index
                    previous_value = current_value
                    continue
                if current_value != previous_value:
                    start_column = data_columns[start_group]
                    end_column = data_columns[non_total_indexes[position - 1]]
                    worksheet.merge_cells(
                        start_row=header_row,
                        start_column=start_column,
                        end_row=header_row,
                        end_column=end_column,
                    )
                    merged_cell = worksheet.cell(row=header_row, column=start_column, value=previous_value)
                    _apply_body_style(merged_cell, bold=True)
                    merged_cell.alignment = Alignment(horizontal="center", vertical="center")
                    start_group = group_index
                    previous_value = current_value
            if start_group is not None:
                start_column = data_columns[start_group]
                end_column = data_columns[non_total_indexes[-1]]
                worksheet.merge_cells(
                    start_row=header_row,
                    start_column=start_column,
                    end_row=header_row,
                    end_column=end_column,
                )
                merged_cell = worksheet.cell(row=header_row, column=start_column, value=previous_value)
                _apply_body_style(merged_cell, bold=True)
                merged_cell.alignment = Alignment(horizontal="center", vertical="center")
    else:
        header_row = current_row
        for column_index, group in zip(data_columns, visible_groups):
            group_cell = worksheet.cell(row=header_row, column=column_index, value=group["label"])
            _apply_body_style(group_cell, bold=(group["label"] == "Total"), fill_color=VN_LIGHT_GRAY if group["label"] == "Total" else None)
            group_cell.alignment = Alignment(horizontal="center", vertical="center")

    sig_row = current_row + level_rows
    for index, group in enumerate(visible_groups):
        column_index = data_columns[index]
        if group["label"] != "Total":
            sig_letter = chr(64 + index) if index < 27 else ""
            sig_cell = worksheet.cell(row=sig_row, column=column_index, value=sig_letter)
            _apply_body_style(sig_cell)
            sig_cell.alignment = Alignment(horizontal="center", vertical="center")
    current_row = sig_row + 3

    for table in sheet.tables:
        total_base_section = next((section for section in table.sections if section["label"] == "Total Base"), None)
        answering_section = next((section for section in table.sections if section["label"] == "Total Answering"), None)
        if not total_base_section or not answering_section:
            continue

        question_cell = worksheet.cell(row=current_row, column=1, value=table.question_label)
        _apply_header_style(question_cell, VN_RED)
        count_label_cell = worksheet.cell(row=current_row, column=2, value="Total Count (All)")
        _apply_body_style(count_label_cell, bold=True, fill_color=VN_LIGHT_GRAY)
        for column_index, denominator in zip(data_columns, total_base_section["base_denominators"]):
            cell = worksheet.cell(row=current_row, column=column_index, value=denominator)
            _apply_body_style(cell, bold=True, fill_color=VN_LIGHT_GRAY)
        current_row += 2

        for count_row, pct_row in zip(total_base_section["rows"], answering_section["rows"]):
            label_fill = VN_LIGHT_GRAY if count_row.get("kind") == "net" else None
            label_text = count_row["label"]
            response_cell = worksheet.cell(row=current_row, column=2, value=label_text)
            _apply_body_style(response_cell, bold=bool(count_row.get("kind") == "net"), wrap=True)
            for column_index, count in zip(data_columns, count_row["counts"]):
                count_cell = worksheet.cell(row=current_row, column=column_index, value=count)
                _apply_body_style(count_cell, fill_color=label_fill)
            current_row += 1

            pct_label_cell = worksheet.cell(row=current_row, column=2, value="")
            _apply_body_style(pct_label_cell, fill_color=label_fill)
            for column_index, percentage in zip(data_columns, pct_row["percentages"]):
                percent_cell = worksheet.cell(row=current_row, column=column_index, value=percentage)
                _apply_body_style(percent_cell, fill_color=label_fill)
                if percentage is not None:
                    percent_cell.number_format = "0%"
            current_row += 1

            sig_label_cell = worksheet.cell(row=current_row, column=2, value="")
            _apply_body_style(sig_label_cell, fill_color=label_fill)
            for column_index, sig_text in zip(data_columns, pct_row["sig_letters"]):
                sig_cell = worksheet.cell(row=current_row, column=column_index, value=sig_text)
                _apply_body_style(sig_cell, fill_color=label_fill)
                sig_cell.alignment = Alignment(horizontal="center", vertical="center")
            current_row += 1

        current_row += 2

    worksheet.freeze_panes = "D7"


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
        _write_banner_sheet(workbook, sheet)

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
