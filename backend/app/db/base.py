"""Базовый класс декларативных SQLAlchemy-моделей."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Общая база для таблиц модульного монолита."""
