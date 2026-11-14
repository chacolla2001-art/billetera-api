"""Conexión a la base de datos (SQLite por defecto; PostgreSQL con DATABASE_URL)."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

URL = os.getenv("DATABASE_URL", "sqlite:///./billetera.db")


class Base(DeclarativeBase):
    pass


def crear_motor(url: str = URL):
    if url.startswith("sqlite"):
        opciones = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            opciones["poolclass"] = StaticPool  # una sola conexión compartida para la base en memoria
        return create_engine(url, **opciones)
    return create_engine(url, pool_pre_ping=True)


motor = crear_motor()
SesionLocal = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)


def obtener_sesion():
    sesion = SesionLocal()
    try:
        yield sesion
    finally:
        sesion.close()
