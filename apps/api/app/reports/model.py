"""What a report contains, independent of PDF or Excel.

A module's report builder fills a ``Report`` from the same repository and
service calls its screens use; the renderers in ``pdf`` and ``excel`` turn it
into a file. Values keep their types (dates, Decimals, ints); ``None`` means not
recorded and is never shown or written as zero.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

ValueType = Literal["text", "int", "decimal", "money", "money4", "percent", "date", "datetime"]
Value = str | int | float | Decimal | dt.date | dt.datetime | None


@dataclass(frozen=True)
class Kpi:
    label: str
    value: Value
    type: ValueType = "int"
    caption: str = ""


@dataclass(frozen=True)
class Series:
    name: str
    values: list[float | int | Decimal | None]
    color: str | None = None


@dataclass(frozen=True)
class Chart:
    title: str
    categories: list[str]
    series: list[Series]
    kind: Literal["bar", "hbar", "line"] = "bar"
    value_type: ValueType = "int"
    description: str = ""
    stacked: bool = False
    x_label: str = ""
    y_label: str = ""


@dataclass(frozen=True)
class Column:
    label: str
    type: ValueType = "text"
    width: int | None = None
    """Excel column width in characters; PDF widths are proportional to it."""


@dataclass(frozen=True)
class Table:
    title: str
    columns: list[Column]
    rows: list[list[Value]]
    description: str = ""
    sheet: str | None = None
    """Excel sheet name; tables without one are added to the Summary sheet."""
    in_pdf: bool = True
    pdf_columns: list[int] | None = None
    """Indexes of the columns the PDF shows when the full set is too wide."""
    pdf_row_limit: int | None = None
    """Long tables are cut in the PDF (with a note); Excel always has every row."""


@dataclass(frozen=True)
class Report:
    key: str
    title: str
    module: str
    period_label: str
    filename: str
    filters: list[tuple[str, str]]
    generated_at: dt.datetime
    generated_by: str
    kpis: list[Kpi] = field(default_factory=list)
    charts: list[Chart] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    subtitle: str = ""

    @property
    def row_count(self) -> int:
        return sum(len(t.rows) for t in self.tables if t.sheet)
