"""SQLAlchemy models.

Phase 0 ships the declarative base only; the tables from SPEC section 3 arrive in
Phase 1. Every model module must be imported here so Alembic autogenerate sees it.
"""

from uyhub.models.base import Base

__all__ = ["Base"]
