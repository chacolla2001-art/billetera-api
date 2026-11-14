"""Esquemas de entrada y salida (validación con Pydantic)."""
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class CuentaCrear(BaseModel):
    titular: str = Field(min_length=3, max_length=120)
    moneda: Literal["BOB", "USD"] = "BOB"


class CuentaSalida(BaseModel):
    id: int
    titular: str
    moneda: str
    saldo: str
    creada: datetime


class Operacion(BaseModel):
    monto: Decimal = Field(gt=0, max_digits=12, decimal_places=2, description="Monto positivo con hasta 2 decimales")
    descripcion: str | None = Field(default=None, max_length=200)


class TransferenciaCrear(BaseModel):
    origen_id: int
    destino_id: int
    monto: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    descripcion: str | None = Field(default=None, max_length=200)


class MovimientoSalida(BaseModel):
    id: int
    cuenta_id: int
    tipo: str
    monto: str
    saldo_despues: str
    referencia: str | None
    descripcion: str | None
    creado: datetime


class TransferenciaSalida(BaseModel):
    referencia: str
    origen_id: int
    destino_id: int
    monto: str
    saldo_origen: str
    saldo_destino: str
