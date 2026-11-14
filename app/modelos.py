"""Modelos: cuentas, movimientos (libro contable inmutable) y claves de idempotencia."""
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def ahora() -> datetime:
    return datetime.now(timezone.utc)


class Cuenta(Base):
    __tablename__ = "cuentas"
    __table_args__ = (CheckConstraint("saldo_centavos >= 0", name="saldo_no_negativo"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    titular: Mapped[str] = mapped_column(String(120))
    moneda: Mapped[str] = mapped_column(String(3))
    # El dinero se guarda en centavos (entero) para no perder precisión con decimales.
    saldo_centavos: Mapped[int] = mapped_column(Integer, default=0)
    creada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    movimientos: Mapped[list["Movimiento"]] = relationship(back_populates="cuenta", order_by="Movimiento.id")


class Movimiento(Base):
    __tablename__ = "movimientos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # deposito | retiro | transferencia_salida | transferencia_entrada
    monto_centavos: Mapped[int] = mapped_column(Integer)
    saldo_despues_centavos: Mapped[int] = mapped_column(Integer)
    referencia: Mapped[str | None] = mapped_column(String(60), nullable=True)
    descripcion: Mapped[str | None] = mapped_column(String(200), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)

    cuenta: Mapped[Cuenta] = relationship(back_populates="movimientos")


class ClaveIdempotencia(Base):
    """Guarda la respuesta de una operación para devolver la misma si el cliente reintenta."""

    __tablename__ = "claves_idempotencia"

    clave: Mapped[str] = mapped_column(String(80), primary_key=True)
    respuesta: Mapped[str] = mapped_column(Text)
    creada: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=ahora)
