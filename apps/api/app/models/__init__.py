"""ORM models.

Import every model module here so Alembic autogenerate sees the full metadata.
"""

from app.audit.models import AuditEvent
from app.db.base import Base
from app.ingestion.models import IngestionBatch
from app.quality.moisture.models import FinishingMeasurement
from app.safety.contacts.models import ContactSupervisor, SupervisorSafetyContact
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.observations.models import Observation, ObservationCategory
from app.safety.performance.models import PerformanceAnnualLegacy, PerformanceHours

__all__ = [
    "AuditEvent",
    "Base",
    "ContactSupervisor",
    "FinishingMeasurement",
    "IngestionBatch",
    "MetricCategory",
    "MetricSection",
    "MonthlyMetricValue",
    "Observation",
    "ObservationCategory",
    "PerformanceAnnualLegacy",
    "PerformanceHours",
    "SupervisorSafetyContact",
]
