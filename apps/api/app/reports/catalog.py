"""Every exportable report, by key. A new dashboard adds its definition here."""

from app.quality.car import reports as car_reports
from app.quality.cost import reports as cost_reports
from app.reports.definitions import ReportDefinition
from app.safety import reports as safety_reports
from app.safety.psm import reports as psm_reports

DEFINITIONS: tuple[ReportDefinition, ...] = (
    car_reports.DASHBOARD,
    car_reports.REGISTER,
    cost_reports.COPQ,
    cost_reports.MATRIX,
    cost_reports.REGISTER,
    safety_reports.INCIDENTS,
    safety_reports.PERFORMANCE,
    safety_reports.TRIR,
    safety_reports.OBSERVATIONS,
    psm_reports.RECOMMENDATIONS,
    psm_reports.ACTIONS,
)

REPORTS: dict[str, ReportDefinition] = {d.key: d for d in DEFINITIONS}
