"""ORM models.

Import every model module here so Alembic autogenerate sees the full metadata.
"""

from app.db.base import Base
from app.quality.moisture.models import FinishingMeasurement

__all__ = ["Base", "FinishingMeasurement"]
