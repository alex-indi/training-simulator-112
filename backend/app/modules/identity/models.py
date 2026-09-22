"""SQLAlchemy-модели пользователей локального стенда."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(StrEnum):
    """Определяет доступные роли пользователя тренажёра."""

    ADMIN = "ADMIN"
    INSTRUCTOR = "INSTRUCTOR"
    TRAINEE = "TRAINEE"


class User(Base):
    """Представляет пользователя локального демонстрационного стенда."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", validate_strings=True),
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
