"""ORM models.

Import every model module here so Alembic autogenerate sees the full metadata.
"""

from app.audit.models import AuditEvent
from app.db.base import Base
from app.ingestion.models import IngestionBatch
from app.quality.moisture.models import FinishingMeasurement
from app.safety.behavior.models import AnnualBehaviorCount, BehaviorCategory
from app.safety.contacts.models import ContactSupervisor, SupervisorSafetyContact
from app.safety.models import MetricCategory, MetricSection, MonthlyMetricValue
from app.safety.observations.models import Observation, ObservationCategory
from app.safety.performance.models import PerformanceAnnualLegacy, PerformanceHours
from app.safety.records.models import IncidentRecord
from app.safety.trir.models import TrirAnnualFact

__all__ = [
    "AnnualBehaviorCount",
    "AuditEvent",
    "Base",
    "BehaviorCategory",
    "ContactSupervisor",
    "FinishingMeasurement",
    "IncidentRecord",
    "IngestionBatch",
    "MetricCategory",
    "MetricSection",
    "MonthlyMetricValue",
    "Observation",
    "ObservationCategory",
    "PerformanceAnnualLegacy",
    "PerformanceHours",
    "SupervisorSafetyContact",
    "TrirAnnualFact",
]
