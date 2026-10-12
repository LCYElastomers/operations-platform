"""PDF renderer: a landscape report laid out for print, not a screenshot.

Charts are reportlab vector drawings, tables repeat their header row on every
page, and every page carries the footer "Operations-Platform · Generated … ·
Page X of Y".
"""

import io
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)
from reportlab.platypus import Table as PdfTable

from app.reports import theme
from app.reports.model import Chart, Kpi, Report, Table, ValueType

PAGE = landscape(letter)
MARGIN = 36
WIDTH = PAGE[0] - 2 * MARGIN
CHART_HEIGHT = 210
LABEL_LIMIT = 24

_ink = colors.HexColor(theme.INK)
_muted = colors.HexColor(theme.MUTED)
_rule = colors.HexColor(theme.RULE)

STYLES = {
    "brand": ParagraphStyle(
        "brand", fontName="Helvetica-Bold", fontSize=8, textColor=colors.HexColor(theme.ACCENT)
    ),
    "module": ParagraphStyle("module", fontName="Helvetica", fontSize=9, textColor=_muted),
    "title": ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=_ink
    ),
    "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5, leading=11, textColor=_ink),
    "h2": ParagraphStyle(
        "h2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=_ink, spaceBefore=8
    ),
    "note": ParagraphStyle(
        "note", fontName="Helvetica", fontSize=7.5, leading=9.5, textColor=_muted
    ),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=7, leading=8.5, textColor=_ink),
    "num": ParagraphStyle(
        "num", fontName="Helvetica", fontSize=7, leading=8.5, textColor=_ink, alignment=TA_RIGHT
    ),
    "head": ParagraphStyle(
        "head", fontName="Helvetica-Bold", fontSize=7, leading=8.5, textColor=colors.white
    ),
    "kpi_label": ParagraphStyle("kpi_label", fontName="Helvetica", fontSize=7.5, textColor=_muted),
    "kpi_value": ParagraphStyle(
        "kpi_value", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=_ink
    ),
}

NUMERIC: set[ValueType] = {"int", "decimal", "money", "money4", "percent"}


def _p(text: str, style: str) -> Paragraph:
    return Paragraph(escape(text), STYLES[style])


def _footer_canvas(generated: str):
    class FooterCanvas(pdf_canvas.Canvas):
        """Draws the footer once the page count is known."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):  # noqa: N802 - reportlab API
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for number, state in enumerate(self._pages, start=1):
                self.__dict__.update(state)
                self.setFont("Helvetica", 7.5)
                self.setFillColor(_muted)
                self.setStrokeColor(_rule)
                self.line(MARGIN, MARGIN - 8, PAGE[0] - MARGIN, MARGIN - 8)
                self.drawString(MARGIN, MARGIN - 20, f"{theme.PRODUCT}  ·  Generated {generated}")
                self.drawRightString(PAGE[0] - MARGIN, MARGIN - 20, f"Page {number} of {total}")
                super().showPage()
            super().save()

    return FooterCanvas


def _header(report: Report) -> list:
    filters = "; ".join(f"{name}: {value}" for name, value in report.filters) or "None"
    generated = theme.generated_label(report.generated_at)
    parts = [
        _p(theme.HEADER, "brand"),
        _p(report.module, "module"),
        Spacer(1, 2),
        _p(report.title, "title"),
    ]
    if report.subtitle:
        parts.append(_p(report.subtitle, "module"))
    parts += [
        Spacer(1, 6),
        Paragraph(f"<b>Period:</b> {escape(report.period_label)}", STYLES["meta"]),
        Paragraph(f"<b>Applied filters:</b> {escape(filters)}", STYLES["meta"]),
        Paragraph(
            f"<b>Generated:</b> {escape(generated)} by {escape(report.generated_by)}",
            STYLES["meta"],
        ),
        Spacer(1, 10),
    ]
    return parts


def _kpis(kpis: list[Kpi]) -> list:
    if not kpis:
        return []
    per_row = 5 if len(kpis) > 8 else 4
    cells = []
    for kpi in kpis:
        cell = [_p(kpi.label, "kpi_label"), _p(theme.display(kpi.value, kpi.type), "kpi_value")]
        if kpi.caption:
            cell.append(_p(kpi.caption, "note"))
        cells.append(cell)
    rows = [cells[i : i + per_row] for i in range(0, len(cells), per_row)]
    rows[-1] += [""] * (per_row - len(rows[-1]))
    table = PdfTable(rows, colWidths=[WIDTH / per_row] * per_row)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for index in range(len(kpis)):
        row, col = divmod(index, per_row)
        style += [
            ("BACKGROUND", (col, row), (col, row), colors.HexColor(theme.KPI_FILL)),
            ("BOX", (col, row), (col, row), 0.5, _rule),
        ]
    table.setStyle(TableStyle(style))
    return [table, Spacer(1, 10)]


def _short(label: str) -> str:
    return label if len(label) <= LABEL_LIMIT else label[: LABEL_LIMIT - 1] + "…"


def _axis_format(kind: ValueType):
    if kind in ("money", "money4"):
        return lambda v: f"${v:,.0f}"
    if kind == "percent":
        return lambda v: f"{v * 100:.0f}%"
    return lambda v: f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"


def _number(value) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal | int | float) else None


def _chart(chart: Chart, width: float) -> Drawing:
    values = [[_number(v) for v in s.values] for s in chart.series]
    present = [v for row in values for v in row if v is not None]
    many = len(chart.categories)
    height = CHART_HEIGHT
    if chart.kind == "hbar":
        height = max(CHART_HEIGHT, 50 + many * 16 * max(1, len(values)))
    drawing = Drawing(width, height)
    drawing.add(String(0, height - 12, chart.title, fontName="Helvetica-Bold", fontSize=9))
    if not chart.categories or not present:
        drawing.add(
            String(0, height - 32, "No data in this selection.", fontSize=8, fillColor=_muted)
        )
        return drawing
    legend_space = 16 if len(values) > 1 else 0
    fmt = _axis_format(chart.value_type)
    top = height - 22 - legend_space
    if chart.kind == "hbar":
        plot = HorizontalBarChart()
        left = 120
        plot.x, plot.y = left, 26
        plot.width, plot.height = width - left - 20, top - 30
        # reportlab draws the first category at the bottom; reports read top-down.
        plot.data = [list(reversed(row)) for row in values]
        plot.categoryAxis.categoryNames = [_short(c) for c in reversed(chart.categories)]
        plot.categoryAxis.labels.boxAnchor = "e"
        plot.categoryAxis.labels.dx = -4
    elif chart.kind == "line":
        plot = HorizontalLineChart()
        plot.x, plot.y = 46, 40
        plot.width, plot.height = width - 60, top - 50
        plot.data = values
        plot.categoryAxis.categoryNames = [_short(c) for c in chart.categories]
        for index in range(len(values)):
            plot.lines[index].strokeWidth = 1.5
    else:
        plot = VerticalBarChart()
        plot.x, plot.y = 46, 40
        plot.width, plot.height = width - 60, top - 50
        plot.data = values
        plot.categoryAxis.categoryNames = [_short(c) for c in chart.categories]
        if many > 6:
            plot.categoryAxis.labels.angle = 30
            plot.categoryAxis.labels.boxAnchor = "ne"
            plot.y = 60
            plot.height = top - 70
    plot.valueAxis.valueMin = min(0, *present)
    plot.valueAxis.labelTextFormat = fmt
    plot.valueAxis.labels.fontSize = 6.5
    plot.categoryAxis.labels.fontSize = 6.5
    plot.valueAxis.visibleGrid = True
    plot.valueAxis.gridStrokeColor = colors.HexColor("#e2e8f0")
    if chart.kind != "line":
        plot.groupSpacing = 6
        if chart.stacked:
            plot.categoryAxis.style = "stacked"
        if len(values) == 1 and many <= 24:
            plot.barLabelFormat = fmt
            plot.barLabels.fontSize = 6
            plot.barLabels.nudge = 7
    for index, series in enumerate(chart.series):
        color = colors.HexColor(series.color or theme.SERIES_COLORS[index % 7])
        if chart.kind == "line":
            plot.lines[index].strokeColor = color
        else:
            plot.bars[index].fillColor = color
            plot.bars[index].strokeColor = None
    drawing.add(plot)
    if chart.y_label:
        drawing.add(String(0, height - 24, chart.y_label, fontSize=6.5, fillColor=_muted))
    if len(values) > 1:
        legend = Legend()
        legend.x, legend.y = 0, height - 22
        legend.alignment = "right"
        legend.columnMaximum = 1
        legend.fontSize = 7
        legend.dx = legend.dy = 6
        legend.dxTextSpace = 4
        legend.boxAnchor = "nw"
        legend.colorNamePairs = [
            (colors.HexColor(s.color or theme.SERIES_COLORS[i % 7]), s.name)
            for i, s in enumerate(chart.series)
        ]
        legend.deltax = max(60, max(len(s.name) for s in chart.series) * 5 + 20)
        legend.variColumn = 1
        drawing.add(legend)
    return drawing


def _charts(charts: list[Chart]) -> list:
    flow: list = []
    half = (WIDTH - 18) / 2
    pending: list[Chart] = []

    def flush():
        if not pending:
            return
        drawings = [_chart(c, half) for c in pending]
        cells = [[d for d in drawings] + ([""] if len(drawings) == 1 else [])]
        row = PdfTable(cells, colWidths=[half + 9, half + 9])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        flow.append(row)
        flow.append(Spacer(1, 6))
        pending.clear()

    for chart in charts:
        if chart.kind == "hbar" and len(chart.categories) > 12:
            flush()
            flow.append(_chart(chart, WIDTH))
            flow.append(Spacer(1, 6))
            continue
        pending.append(chart)
        if len(pending) == 2:
            flush()
    flush()
    descriptions = [c for c in charts if c.description]
    if descriptions:
        flow.append(
            Paragraph(
                "<br/>".join(
                    f"<b>{escape(c.title)}:</b> {escape(c.description)}" for c in descriptions
                ),
                STYLES["note"],
            )
        )
    return flow


def _table(table: Table) -> list:
    rows = table.rows
    columns = table.columns
    if table.pdf_columns is not None:
        columns = [columns[i] for i in table.pdf_columns]
        rows = [[row[i] for i in table.pdf_columns] for row in rows]
    note = ""
    if table.pdf_row_limit is not None and len(rows) > table.pdf_row_limit:
        note = (
            f"Showing the first {table.pdf_row_limit:,} of {len(rows):,} rows; "
            "the Excel export has every row."
        )
        rows = rows[: table.pdf_row_limit]
    weights = [c.width or 12 for c in columns]
    scale = WIDTH / sum(weights)
    head = [_p(c.label, "head") for c in columns]
    body = [
        [
            _p(theme.display(value, column.type), "num" if column.type in NUMERIC else "cell")
            for value, column in zip(row, columns, strict=True)
        ]
        for row in rows
    ]
    grid = PdfTable([head, *body], colWidths=[w * scale for w in weights], repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(theme.HEADER_FILL)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, _rule),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for index in range(2, len(body) + 1, 2):
        style.append(("BACKGROUND", (0, index), (-1, index), colors.HexColor(theme.STRIPE)))
    grid.setStyle(TableStyle(style))
    heading = [_p(table.title, "h2")]
    if table.description:
        heading.append(_p(table.description, "note"))
    heading.append(Spacer(1, 4))
    if not rows:
        return [*heading, _p("No rows in this selection.", "note"), Spacer(1, 8)]
    flow: list = [KeepTogether([*heading, grid])] if len(rows) <= 12 else [*heading, grid]
    if note:
        flow.append(_p(note, "note"))
    flow.append(Spacer(1, 8))
    return flow


def render_pdf(report: Report, *, compress: bool = True) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pageCompression=1 if compress else 0,
        pagesize=PAGE,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 10,
        title=f"{report.title} — {report.period_label}",
        author=theme.PRODUCT,
        subject=report.module,
        creator=theme.PRODUCT,
    )
    story: list = [*_header(report), *_kpis(report.kpis)]
    if report.charts:
        story += _charts(report.charts)
    for table in report.tables:
        if table.in_pdf:
            story += _table(table)
    if report.notes:
        story.append(_p("Notes", "h2"))
        story += [_p(note, "note") for note in report.notes]
    generated = theme.generated_label(report.generated_at)
    doc.build(story, canvasmaker=_footer_canvas(generated))
    return buffer.getvalue()
