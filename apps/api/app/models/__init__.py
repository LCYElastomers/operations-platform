"""ORM models.

Import every model module here so Alembic autogenerate sees the full metadata.
"""

from app.db.base import Base

__all__ = ["Base"]
