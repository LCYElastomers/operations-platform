"""ORM models.

Import every model module here so Alembic autogenerate sees the full metadata.
"""

from app.audit.models import AuditEvent
from app.auth.models import (
    AuthSession,
    PasswordToken,
    PermissionDefinition,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.db.base import Base
from app.ingestion.models import IngestionBatch
from app.quality.car.models import Car, CarAction, CarApproval, CarReference, CarWhyStep
from app.quality.cost.models import CostMonthlyFact, CostRecord, CostRecordReference
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
    "AuthSession",
    "Base",
    "BehaviorCategory",
    "Car",
    "CarAction",
    "CarApproval",
    "CarReference",
    "CarWhyStep",
    "ContactSupervisor",
    "CostMonthlyFact",
    "CostRecord",
    "CostRecordReference",
    "FinishingMeasurement",
    "IncidentRecord",
    "IngestionBatch",
    "MetricCategory",
    "MetricSection",
    "MonthlyMetricValue",
    "Observation",
    "ObservationCategory",
    "PasswordToken",
    "PerformanceAnnualLegacy",
    "PerformanceHours",
    "PermissionDefinition",
    "Role",
    "RolePermission",
    "SupervisorSafetyContact",
    "TrirAnnualFact",
    "User",
    "UserRole",
]
