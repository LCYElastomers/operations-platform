"""Excel renderer: a real .xlsx with typed cells.

Dates are Excel dates, money and percentages are numbers with a number format,
and a value that was not recorded is an empty cell (never zero). Every data
sheet has a context block, a styled frozen header and an autofilter.
"""

import datetime as dt
import io
import re
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.reports import theme
from app.reports.model import Chart, Column, Report, Table, Value, ValueType

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor=theme.HEADER_FILL.removeprefix("#"))
TITLE_FONT = Font(bold=True, size=14)
BRAND_FONT = Font(bold=True, size=9, color=theme.ACCENT.removeprefix("#"))
LABEL_FONT = Font(bold=True)
SECTION_FONT = Font(bold=True, size=12)
THIN = Side(style="thin", color=theme.RULE.removeprefix("#"))

_INVALID_SHEET = re.compile(r"[\[\]:*?/\\]")


def _cell_value(value: Value, kind: ValueType):
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return theme.site_time(value).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, dt.date):
        return value
    if kind in ("int",) and isinstance(value, int | float | Decimal):
        return int(value)
    if kind in ("decimal", "money", "money4", "percent") and isinstance(
        value, int | float | Decimal
    ):
        # openpyxl writes Decimal as a number; float keeps Excel happy across versions.
        return float(value)
    return value


def _write_row(sheet: Worksheet, row: int, values: list[Value], columns: list[Column]) -> None:
    for index, (value, column) in enumerate(zip(values, columns, strict=True), start=1):
        cell = sheet.cell(row=row, column=index, value=_cell_value(value, column.type))
        if cell.value is not None and column.type != "text":
            cell.number_format = theme.EXCEL_FORMATS[column.type]


def _header(sheet: Worksheet, row: int, labels: list[str]) -> None:
    for index, label in enumerate(labels, start=1):
        cell = sheet.cell(row=row, column=index, value=label)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(bottom=THIN)


def _widths(sheet: Worksheet, columns: list[Column], rows: list[list[Value]]) -> None:
    for index, column in enumerate(columns, start=1):
        width = column.width
        if width is None:
            longest = max(
                [len(column.label)]
                + [len(theme.display(r[index - 1], column.type)) for r in rows[:500]]
            )
            width = min(60, max(10, longest + 2))
        sheet.column_dimensions[get_column_letter(index)].width = width


def _context(sheet: Worksheet, report: Report, title: str) -> int:
    """The title block at the top of a data sheet; returns the header row."""
    sheet["A1"] = theme.HEADER
    sheet["A1"].font = BRAND_FONT
    sheet["A2"] = title
    sheet["A2"].font = TITLE_FONT
    filters = "; ".join(f"{name}: {value}" for name, value in report.filters) or "None"
    sheet["A3"] = f"Period: {report.period_label}  ·  Applied filters: {filters}"
    return 5


def _sheet_name(name: str, used: set[str]) -> str:
    base = _INVALID_SHEET.sub(" ", name).strip()[:31] or "Sheet"
    candidate, number = base, 2
    while candidate.lower() in used:
        suffix = f" ({number})"
        candidate = base[: 31 - len(suffix)] + suffix
        number += 1
    used.add(candidate.lower())
    return candidate


def _data_sheet(workbook: Workbook, report: Report, table: Table, used: set[str]) -> None:
    sheet = workbook.create_sheet(_sheet_name(table.sheet or table.title, used))
    header_row = _context(sheet, report, table.title)
    _header(sheet, header_row, [c.label for c in table.columns])
    for offset, row in enumerate(table.rows, start=1):
        _write_row(sheet, header_row + offset, row, table.columns)
    last_row = header_row + max(len(table.rows), 1)
    last_col = get_column_letter(len(table.columns))
    sheet.auto_filter.ref = f"A{header_row}:{last_col}{last_row}"
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    _widths(sheet, table.columns, table.rows)
    if not table.rows:
        sheet.cell(row=header_row + 1, column=1, value="No rows in this selection.")


def _chart_table(chart: Chart) -> Table:
    columns = [Column(chart.x_label or "Category", "text", 28)] + [
        Column(s.name, chart.value_type, 16) for s in chart.series
    ]
    rows: list[list[Value]] = [
        [category, *(s.values[i] if i < len(s.values) else None for s in chart.series)]
        for i, category in enumerate(chart.categories)
    ]
    return Table(chart.title, columns, rows, description=chart.description)


def _block(sheet: Worksheet, row: int, table: Table) -> int:
    """A titled table inside the Summary or Analysis sheet; returns the next free row."""
    sheet.cell(row=row, column=1, value=table.title).font = SECTION_FONT
    row += 1
    if table.description:
        sheet.cell(row=row, column=1, value=table.description).alignment = Alignment(
            wrap_text=False
        )
        row += 1
    _header(sheet, row, [c.label for c in table.columns])
    for values in table.rows:
        row += 1
        _write_row(sheet, row, values, table.columns)
    if not table.rows:
        row += 1
        sheet.cell(row=row, column=1, value="No rows in this selection.")
    return row + 2


def _summary(workbook: Workbook, report: Report, used: set[str]) -> None:
    sheet = workbook.active
    assert sheet is not None  # noqa: S101 - a new workbook always has one sheet
    sheet.title = _sheet_name("Summary", used)
    sheet["A1"] = theme.HEADER
    sheet["A1"].font = BRAND_FONT
    sheet["A2"] = report.title
    sheet["A2"].font = TITLE_FONT
    context: list[tuple[str, object, str | None]] = [
        ("Report Name", report.title, None),
        ("Module", report.module, None),
        ("Period", report.period_label, None),
        (
            "Generated At",
            theme.site_time(report.generated_at).replace(tzinfo=None),
            "yyyy-mm-dd hh:mm",
        ),
        ("Generated By", report.generated_by, None),
    ]
    row = 4
    for label, value, fmt in context:
        sheet.cell(row=row, column=1, value=label).font = LABEL_FONT
        cell = sheet.cell(row=row, column=2, value=value)
        if fmt:
            cell.number_format = fmt
            cell.alignment = Alignment(horizontal="left")
        row += 1
    sheet.cell(row=row, column=1, value="Applied Filters").font = LABEL_FONT
    if not report.filters:
        sheet.cell(row=row, column=2, value="None")
        row += 1
    for name, value in report.filters:
        sheet.cell(row=row, column=2, value=f"{name}: {value}")
        row += 1
    row += 1
    if report.kpis:
        sheet.cell(row=row, column=1, value="Key figures").font = SECTION_FONT
        row += 1
        _header(sheet, row, ["Measure", "Value", "Note"])
        for kpi in report.kpis:
            row += 1
            sheet.cell(row=row, column=1, value=kpi.label)
            cell = sheet.cell(row=row, column=2, value=_cell_value(kpi.value, kpi.type))
            if cell.value is not None and kpi.type != "text":
                cell.number_format = theme.EXCEL_FORMATS[kpi.type]
            if kpi.value is None:
                cell.value = "Not recorded"
            sheet.cell(row=row, column=3, value=kpi.caption or None)
        row += 2
    for table in report.tables:
        if table.sheet is None:
            row = _block(sheet, row, table)
    for note in report.notes:
        sheet.cell(row=row, column=1, value=note)
        row += 1
    sheet.column_dimensions["A"].width = 34
    sheet.column_dimensions["B"].width = 28
    sheet.column_dimensions["C"].width = 60
    for letter in "DEFGHIJ":
        sheet.column_dimensions[letter].width = 16


def render_excel(report: Report) -> bytes:
    workbook = Workbook()
    used: set[str] = set()
    _summary(workbook, report, used)
    for table in report.tables:
        if table.sheet is not None:
            _data_sheet(workbook, report, table, used)
    if report.charts:
        sheet = workbook.create_sheet(_sheet_name("Analysis", used))
        row = _context(sheet, report, f"{report.title} — chart data")
        for chart in report.charts:
            row = _block(sheet, row, _chart_table(chart))
        sheet.column_dimensions["A"].width = 34
        for index in range(2, 10):
            sheet.column_dimensions[get_column_letter(index)].width = 18
    workbook.properties.title = report.title
    workbook.properties.creator = theme.PRODUCT
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
