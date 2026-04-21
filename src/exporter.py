"""Excel export helpers for branded BLS Smart Tables workbooks."""

from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell.cell import MergedCell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from src.utils import normalize_text


VN_BLACK = "FF000000"
VN_WHITE = "FFFFFFFF"
VN_RED = "FFFF005C"
VN_ORANGE = "FFFF6927"
VN_YELLOW = "FFFFC227"
VN_LIGHT_GRAY = "FFF4F5F8"
VN_BORDER_GRAY = "FFD9D9D9"
VN_GREEN = "FF1F8F4E"
VN_LIGHT_GREEN = "FFE6F4EA"
VN_LIGHT_RED = "FFFDE8EC"
EXPORT_LAYOUT_VERSION = "Layout v2026.04.20.4"


def _excel_rgb(color: str) -> str:
    """Return an 8-digit ARGB color string for openpyxl/Excel styles."""
    normalized = (color or "").strip().lstrip("#").upper()
    if len(normalized) == 6:
        return f"FF{normalized}"
    return normalized


def _apply_header_style(cell, fill_color: str, font_color: str = VN_WHITE, bold: bool = True) -> None:
    """Apply a consistent header style to one Excel cell."""
    cell.fill = PatternFill("solid", fgColor=_excel_rgb(fill_color))
    cell.font = Font(color=_excel_rgb(font_color), bold=bold, name="Proxima Nova")
    cell.alignment = Alignment(horizontal="center", vertical="center")


def _apply_body_style(cell, bold: bool = False, fill_color: str | None = None, wrap: bool = False) -> None:
    """Apply a consistent body style to one Excel cell."""
    if fill_color:
        cell.fill = PatternFill("solid", fgColor=_excel_rgb(fill_color))
    cell.font = Font(color=_excel_rgb(VN_BLACK), bold=bold, name="Proxima Nova")
    cell.alignment = Alignment(vertical="top", wrap_text=wrap)
    thin = Side(style="thin", color=_excel_rgb(VN_BORDER_GRAY))
    cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)


def _apply_topline_delta_style(lift_cell, significant_direction: str) -> None:
    """Highlight topline test results to make wins/losses easy to scan."""
    if significant_direction == "right":
        lift_cell.fill = PatternFill("solid", fgColor=_excel_rgb(VN_LIGHT_GREEN))
        lift_cell.font = Font(color=_excel_rgb(VN_GREEN), bold=True, name="Proxima Nova")
    elif significant_direction == "left":
        lift_cell.fill = PatternFill("solid", fgColor=_excel_rgb(VN_LIGHT_RED))
        lift_cell.font = Font(color=_excel_rgb(VN_RED), bold=True, name="Proxima Nova")


def _write_version_stamp(worksheet, row: int, start_column: int, end_column: int) -> None:
    """Write a visible exporter layout version stamp."""
    if end_column <= start_column:
        stamp_cell = worksheet.cell(row=row, column=start_column, value=EXPORT_LAYOUT_VERSION)
    else:
        worksheet.merge_cells(
            start_row=row,
            start_column=start_column,
            end_row=row,
            end_column=end_column,
        )
        stamp_cell = worksheet.cell(row=row, column=start_column, value=EXPORT_LAYOUT_VERSION)
    _apply_body_style(stamp_cell, bold=True, fill_color=VN_LIGHT_GRAY)
    stamp_cell.alignment = Alignment(horizontal="right", vertical="center")


def _set_sheet_columns(worksheet, group_count: int, lift_count: int = 0) -> None:
    """Set practical column widths for a question-table worksheet."""
    worksheet.column_dimensions["A"].width = 42
    worksheet.column_dimensions["B"].width = 20
    total_data_columns = max(group_count, 1) * 2
    total_sheet_columns = total_data_columns + (lift_count * 2) + 1
    for column_index in range(3, 3 + total_sheet_columns):
        worksheet.column_dimensions[get_column_letter(column_index)].width = 14
    separator_column = 3 + group_count + lift_count
    worksheet.column_dimensions[get_column_letter(separator_column)].width = 3


def _build_banner_lift_pairs(sheet, visible_groups: list[dict]) -> tuple[list[dict], str]:
    """Return binary lowest-level lift pairs for one banner sheet."""
    if not sheet.levels:
        return [], "Lift could not be performed since the comparison variable is not binary."

    lowest_level = sheet.levels[-1]
    non_total_groups = [group for group in visible_groups if group.get("label") != "Total"]
    if not non_total_groups:
        return [], "Lift could not be performed since the comparison variable is not binary."

    parent_lookup: dict[tuple[str, ...], list[tuple[int, dict]]] = {}
    for group_index, group in enumerate(visible_groups):
        if group.get("label") == "Total":
            continue
        display_values = group.get("display_values", {}) or {}
        parent_key = tuple(
            normalize_text(display_values.get(level) or group.get("values", {}).get(level))
            for level in sheet.levels[:-1]
        )
        parent_lookup.setdefault(parent_key, []).append((group_index, group))

    lift_pairs: list[dict] = []
    for parent_key, members in parent_lookup.items():
        if len(members) != 2:
            return [], "Lift could not be performed since the comparison variable is not binary."
        (left_index, left_group), (right_index, right_group) = members
        left_display = left_group.get("display_values", {}) or {}
        right_display = right_group.get("display_values", {}) or {}
        lowest_left = normalize_text(left_display.get(lowest_level) or left_group.get("values", {}).get(lowest_level))
        lowest_right = normalize_text(right_display.get(lowest_level) or right_group.get("values", {}).get(lowest_level))
        if not lowest_left or not lowest_right or lowest_left == lowest_right:
            return [], "Lift could not be performed since the comparison variable is not binary."
        parent_label = " | ".join(value for value in parent_key if value)
        if not parent_label:
            parent_label = f"{lowest_right} vs {lowest_left}"
        lift_pairs.append(
            {
                "parent_label": parent_label,
                "left_index": left_index,
                "right_index": right_index,
            }
        )
    return lift_pairs, ""


def _format_lift_display(left_pct: float | None, right_pct: float | None) -> str:
    """Format a lift value as signed point difference."""
    if left_pct is None or right_pct is None:
        return ""
    lift_points = round((right_pct - left_pct) * 100)
    return f"{lift_points:+d} pts"


def _format_level_label(level_name: str) -> str:
    """Return a human-friendly banner-level label for export headers."""
    normalized = normalize_text(level_name)
    if normalized == "__selection_status__":
        return "Selection Status"
    return level_name


def _paint_separator_column(worksheet, column_index: int, start_row: int, end_row: int) -> None:
    """Fill a narrow black separator column between table sections."""
    if end_row < start_row:
        return
    for row_index in range(start_row, end_row + 1):
        cell = worksheet.cell(row=row_index, column=column_index)
        if isinstance(cell, MergedCell):
            continue
        cell.fill = PatternFill("solid", fgColor=_excel_rgb(VN_BLACK))
        cell.border = Border()


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
        "H": 18,
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
    _write_version_stamp(worksheet, row=current_row, start_column=7, end_column=9)
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
        (12, 8): "Note Base",
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
        row_label = row.get("Topline Label") or row.get("Variable") or row.get("Question", "")
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

        _apply_topline_delta_style(
            lift_cell,
            str(row.get("Sig Test", "") or ""),
        )

        notes_cell = worksheet.cell(row=current_row, column=7, value=row.get("Notes", ""))
        _apply_body_style(notes_cell, wrap=True)
        note_base_cell = worksheet.cell(
            row=current_row,
            column=8,
            value=row.get("Note Base") or "Total Answering",
        )
        _apply_body_style(note_base_cell, fill_color=VN_LIGHT_GRAY)
        note_base_cell.alignment = Alignment(horizontal="center", vertical="top", wrap_text=True)
        current_row += 1

    worksheet.freeze_panes = "B11"


def _write_banner_sheet(
    workbook,
    sheet,
    include_n_count: bool = False,
    include_lift: bool = False,
) -> None:
    """Write one banner worksheet in an analyst-friendly table format."""
    table_groups = [table.groups for table in sheet.tables if getattr(table, "groups", None)]
    max_group_count = max([len(sheet.groups), *[len(groups) for groups in table_groups], 1])
    max_lift_count = 0
    if include_lift:
        for groups, levels in [*([(sheet.groups, sheet.levels)] if sheet.groups else []), *[(table.groups, table.levels) for table in sheet.tables if table.groups]]:
            lift_pairs, _ = _build_banner_lift_pairs(type("obj", (), {"levels": levels}), list(groups))
            max_lift_count = max(max_lift_count, len(lift_pairs))

    worksheet = workbook.create_sheet(title=str(sheet.name)[:31] or "Sheet1")
    _set_sheet_columns(worksheet, max_group_count, max_lift_count)

    current_row = 1
    max_end_column = 3 + (max_group_count * 2) + (max_lift_count * 2)
    worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=max_end_column)
    title_cell = worksheet.cell(row=current_row, column=1, value=sheet.banner_name)
    _apply_header_style(title_cell, VN_BLACK)
    current_row += 1
    _write_version_stamp(
        worksheet,
        row=current_row,
        start_column=max(3, max_end_column - 2),
        end_column=max_end_column,
    )
    worksheet.cell(row=current_row, column=1, value="filtered by")
    _apply_body_style(worksheet.cell(row=current_row, column=1))
    current_row += 1
    worksheet.cell(row=current_row, column=1, value="FILTER: ALL")
    _apply_body_style(worksheet.cell(row=current_row, column=1))
    current_row += 2

    def _write_one_table(
        current_row: int,
        table,
        active_banner_name: str,
        active_levels: list[str],
        active_groups: list[dict[str, object]],
        footnotes: list[str],
    ) -> int:
        lift_pairs, lift_footnote = _build_banner_lift_pairs(type("obj", (), {"levels": active_levels}), active_groups) if include_lift else ([], "")
        lift_enabled = bool(include_lift and lift_pairs)
        section_group_count = max(len(active_groups), 1)
        left_data_start_column = 3
        left_lift_start_column = left_data_start_column + section_group_count
        separator_column = left_lift_start_column + (len(lift_pairs) if lift_enabled else 0)
        right_data_start_column = separator_column + 1
        right_lift_start_column = right_data_start_column + section_group_count
        left_data_columns = [left_data_start_column + index for index in range(len(active_groups))]
        right_data_columns = [right_data_start_column + index for index in range(len(active_groups))]
        left_lift_columns = [left_lift_start_column + index for index in range(len(lift_pairs))] if lift_enabled else []
        right_lift_columns = [right_lift_start_column + index for index in range(len(lift_pairs))] if lift_enabled else []
        table_end_column = (
            right_lift_columns[-1] if right_lift_columns else
            (right_data_columns[-1] if right_data_columns else 3)
        )

        banner_descriptor = " > ".join(_format_level_label(level) for level in active_levels) if active_levels else active_banner_name or "All Tables"
        if active_groups:
            worksheet.merge_cells(start_row=current_row, start_column=3, end_row=current_row, end_column=table_end_column)
            descriptor_cell = worksheet.cell(row=current_row, column=3, value=banner_descriptor)
            _apply_header_style(descriptor_cell, VN_ORANGE)
        current_row += 1

        level_rows = max(1, len(active_levels))
        total_group_indexes = [index for index, group in enumerate(active_groups) if group["label"] == "Total"]
        non_total_indexes = [index for index, group in enumerate(active_groups) if group["label"] != "Total"]

        section_header_row = current_row
        if active_groups:
            worksheet.merge_cells(
                start_row=section_header_row,
                start_column=left_data_start_column,
                end_row=section_header_row,
                end_column=(left_lift_columns[-1] if left_lift_columns else left_data_columns[-1]),
            )
            left_title_cell = worksheet.cell(
                row=section_header_row,
                column=left_data_start_column,
                value="Total Sample % / Lift (Base: Total Sample)" if lift_enabled else "Total Sample % (Base: Total Sample)",
            )
            _apply_header_style(left_title_cell, VN_YELLOW, font_color=VN_BLACK)
            worksheet.merge_cells(
                start_row=section_header_row,
                start_column=right_data_start_column,
                end_row=section_header_row,
                end_column=(right_lift_columns[-1] if right_lift_columns else right_data_columns[-1]),
            )
            right_title_cell = worksheet.cell(
                row=section_header_row,
                column=right_data_start_column,
                value="Total Answering % / Lift (Base: Total Answering)" if lift_enabled else "Total Answering % (Base: Total Answering)",
            )
            _apply_header_style(right_title_cell, VN_YELLOW, font_color=VN_BLACK)
        current_row += 1

        def _write_group_header_block(data_columns: list[int]) -> None:
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
            if active_levels and non_total_indexes:
                for level_index, level_name in enumerate(active_levels):
                    header_row = current_row + level_index
                    start_group = None
                    previous_value = None
                    for position, group_index in enumerate(non_total_indexes):
                        group = active_groups[group_index]
                        current_value = normalize_text(group.get("display_values", {}).get(level_name))
                        if not current_value:
                            current_value = normalize_text(group.get("values", {}).get(level_name))
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
                for column_index, group in zip(data_columns, active_groups):
                    group_cell = worksheet.cell(row=header_row, column=column_index, value=group["label"])
                    _apply_body_style(group_cell, bold=(group["label"] == "Total"), fill_color=VN_LIGHT_GRAY if group["label"] == "Total" else None)
                    group_cell.alignment = Alignment(horizontal="center", vertical="center")

        _write_group_header_block(left_data_columns)
        _write_group_header_block(right_data_columns)

        sig_row = current_row + level_rows
        for data_columns in [left_data_columns, right_data_columns]:
            for index, group in enumerate(active_groups):
                column_index = data_columns[index]
                if group["label"] != "Total":
                    sig_letter = chr(64 + index) if index < 27 else ""
                    sig_cell = worksheet.cell(row=sig_row, column=column_index, value=sig_letter)
                    _apply_body_style(sig_cell)
                    sig_cell.alignment = Alignment(horizontal="center", vertical="center")
        if lift_enabled:
            for column_index, pair in zip(left_lift_columns, lift_pairs):
                worksheet.merge_cells(start_row=current_row, start_column=column_index, end_row=sig_row, end_column=column_index)
                lift_header_cell = worksheet.cell(row=current_row, column=column_index, value=f"{pair['parent_label']} Lift")
                _apply_body_style(lift_header_cell, bold=True, fill_color=VN_LIGHT_GRAY, wrap=True)
                lift_header_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for column_index, pair in zip(right_lift_columns, lift_pairs):
                worksheet.merge_cells(start_row=current_row, start_column=column_index, end_row=sig_row, end_column=column_index)
                lift_header_cell = worksheet.cell(row=current_row, column=column_index, value=f"{pair['parent_label']} Lift")
                _apply_body_style(lift_header_cell, bold=True, fill_color=VN_LIGHT_GRAY, wrap=True)
                lift_header_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        current_row = sig_row + 3

        total_base_section = next((section for section in table.sections if section["label"] == "Total Base"), None)
        answering_section = next((section for section in table.sections if section["label"] == "Total Answering"), None)
        if not total_base_section or not answering_section:
            return current_row

        notation_location = getattr(sheet, "notation_location", "appended_to_metric")
        response_block_height = len(total_base_section["rows"]) * (1 + (1 if notation_location == "below_metric" else 0) + (1 if include_n_count else 0))
        question_label_row = current_row + 2
        question_end_row = question_label_row + max(response_block_height - 1, 0)
        if response_block_height > 1:
            worksheet.merge_cells(start_row=question_label_row, start_column=1, end_row=question_end_row, end_column=1)
        question_cell = worksheet.cell(row=question_label_row, column=1, value=table.question_label)
        _apply_header_style(question_cell, VN_RED)
        question_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

        count_label_cell = worksheet.cell(row=current_row, column=2, value="Base Sizes")
        _apply_body_style(count_label_cell, bold=True, fill_color=VN_LIGHT_GRAY)
        for column_index, denominator in zip(left_data_columns, total_base_section["base_denominators"]):
            cell = worksheet.cell(row=current_row, column=column_index, value=denominator)
            _apply_body_style(cell, bold=True, fill_color=VN_LIGHT_GRAY)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for column_index, denominator in zip(right_data_columns, answering_section["base_denominators"]):
            cell = worksheet.cell(row=current_row, column=column_index, value=denominator)
            _apply_body_style(cell, bold=True, fill_color=VN_LIGHT_GRAY)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for column_index, pair in zip(left_lift_columns, lift_pairs):
            lift_base_value = f"{total_base_section['base_denominators'][pair['left_index']]}/{total_base_section['base_denominators'][pair['right_index']]}"
            cell = worksheet.cell(row=current_row, column=column_index, value=lift_base_value)
            _apply_body_style(cell, bold=True, fill_color=VN_LIGHT_GRAY)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for column_index, pair in zip(right_lift_columns, lift_pairs):
            lift_base_value = f"{answering_section['base_denominators'][pair['left_index']]}/{answering_section['base_denominators'][pair['right_index']]}"
            cell = worksheet.cell(row=current_row, column=column_index, value=lift_base_value)
            _apply_body_style(cell, bold=True, fill_color=VN_LIGHT_GRAY)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        current_row += 2

        for total_row, answering_row in zip(total_base_section["rows"], answering_section["rows"]):
            label_fill = VN_LIGHT_GRAY if total_row.get("kind") == "net" else None
            response_cell = worksheet.cell(row=current_row, column=2, value=total_row["label"])
            _apply_body_style(response_cell, bold=bool(total_row.get("kind") == "net"), wrap=True)
            response_cell.alignment = Alignment(vertical="center", wrap_text=True)
            for data_columns, section_row in [(left_data_columns, total_row), (right_data_columns, answering_row)]:
                for column_index, percentage, sig_text in zip(data_columns, section_row["percentages"], section_row["sig_letters"]):
                    display_value = ""
                    if percentage is not None:
                        display_value = f"{percentage:.0%}{normalize_text(sig_text)}" if notation_location != "below_metric" else f"{percentage:.0%}"
                    percent_cell = worksheet.cell(row=current_row, column=column_index, value=display_value)
                    _apply_body_style(percent_cell, fill_color=label_fill)
                    percent_cell.alignment = Alignment(horizontal="center", vertical="center")
            if lift_enabled:
                for column_index, pair in zip(left_lift_columns, lift_pairs):
                    lift_cell = worksheet.cell(row=current_row, column=column_index, value=_format_lift_display(total_row["percentages"][pair["left_index"]], total_row["percentages"][pair["right_index"]]))
                    _apply_body_style(lift_cell, fill_color=label_fill)
                    lift_cell.alignment = Alignment(horizontal="center", vertical="center")
                for column_index, pair in zip(right_lift_columns, lift_pairs):
                    lift_cell = worksheet.cell(row=current_row, column=column_index, value=_format_lift_display(answering_row["percentages"][pair["left_index"]], answering_row["percentages"][pair["right_index"]]))
                    _apply_body_style(lift_cell, fill_color=label_fill)
                    lift_cell.alignment = Alignment(horizontal="center", vertical="center")
            current_row += 1

            if notation_location == "below_metric":
                sig_label_cell = worksheet.cell(row=current_row, column=2, value="")
                _apply_body_style(sig_label_cell, fill_color=label_fill)
                for data_columns, section_row in [(left_data_columns, total_row), (right_data_columns, answering_row)]:
                    for column_index, sig_text in zip(data_columns, section_row["sig_letters"]):
                        sig_cell = worksheet.cell(row=current_row, column=column_index, value=normalize_text(sig_text))
                        _apply_body_style(sig_cell, fill_color=label_fill)
                        sig_cell.alignment = Alignment(horizontal="center", vertical="center")
                for column_index in [*left_lift_columns, *right_lift_columns]:
                    blank_cell = worksheet.cell(row=current_row, column=column_index, value="")
                    _apply_body_style(blank_cell, fill_color=label_fill)
                current_row += 1

            if include_n_count:
                count_label_cell = worksheet.cell(row=current_row, column=2, value="")
                _apply_body_style(count_label_cell, fill_color=label_fill)
                for data_columns, section_row in [(left_data_columns, total_row), (right_data_columns, answering_row)]:
                    for column_index, count in zip(data_columns, section_row["counts"]):
                        count_cell = worksheet.cell(row=current_row, column=column_index, value=count)
                        _apply_body_style(count_cell, fill_color=label_fill)
                        count_cell.alignment = Alignment(horizontal="center", vertical="center")
                for column_index in [*left_lift_columns, *right_lift_columns]:
                    count_cell = worksheet.cell(row=current_row, column=column_index, value="")
                    _apply_body_style(count_cell, fill_color=label_fill)
                current_row += 1

        if include_lift and not lift_enabled and lift_footnote:
            footnotes = [*footnotes, lift_footnote]
        if footnotes:
            for note in footnotes:
                worksheet.merge_cells(start_row=current_row, start_column=2, end_row=current_row, end_column=table_end_column)
                footnote_cell = worksheet.cell(row=current_row, column=2, value=note)
                _apply_body_style(footnote_cell, fill_color=VN_LIGHT_GRAY, wrap=True)
                footnote_cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
                current_row += 1
        _paint_separator_column(worksheet, separator_column, section_header_row, current_row - 1)
        return current_row + 2

    previous_banner_name = None
    if sheet.groups:
        for table in sheet.tables:
            current_row = _write_one_table(
                current_row,
                table,
                sheet.banner_name,
                sheet.levels,
                list(sheet.groups),
                list(sheet.footnotes),
            )
    else:
        for table in sheet.tables:
            active_banner_name = getattr(table, "banner_name", sheet.banner_name)
            active_groups = list(getattr(table, "groups", []))
            table_end_column = max_end_column
            if active_banner_name != previous_banner_name:
                worksheet.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=table_end_column)
                banner_section_cell = worksheet.cell(row=current_row, column=1, value=f"Banner: {active_banner_name}")
                _apply_header_style(banner_section_cell, VN_BLACK)
                current_row += 2
                previous_banner_name = active_banner_name
            current_row = _write_one_table(
                current_row,
                table,
                active_banner_name,
                list(getattr(table, "levels", [])),
                active_groups,
                list(getattr(table, "footnotes", [])),
            )

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
        _write_banner_sheet(
            workbook,
            sheet,
            include_n_count=bool(workbook_package.get("include_n_count", False)),
            include_lift=bool(workbook_package.get("include_lift", False)),
        )

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
