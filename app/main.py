"""API REST de la billetera (FastAPI). Documentación interactiva en /docs."""
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from . import servicios
from .db import Base, motor, obtener_sesion
from .esquemas import CuentaCrear, CuentaSalida, MovimientoSalida, Operacion, TransferenciaCrear, TransferenciaSalida


@asynccontextmanager
async def ciclo_de_vida(_app: FastAPI):
    Base.metadata.create_all(motor)
    yield


app = FastAPI(
    title="Billetera API",
    description="Cuentas, depósitos, retiros y transferencias atómicas con límite diario e idempotencia.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)
SesionDep = Annotated[Session, Depends(obtener_sesion)]


@app.exception_handler(servicios.ErrorNegocio)
async def manejar_error(_req: Request, e: servicios.ErrorNegocio):
    return JSONResponse(status_code=e.estado, content={"detail": e.mensaje})


@app.get("/salud")
def salud():
    return {"ok": True}


@app.post("/cuentas", response_model=CuentaSalida, status_code=201)
def crear_cuenta(datos: CuentaCrear, s: SesionDep):
    return servicios.cuenta_a_dict(servicios.crear_cuenta(s, datos.titular, datos.moneda))


@app.get("/cuentas/{cuenta_id}", response_model=CuentaSalida)
def ver_cuenta(cuenta_id: int, s: SesionDep):
    return servicios.cuenta_a_dict(servicios.obtener_cuenta(s, cuenta_id))


@app.get("/cuentas/{cuenta_id}/movimientos", response_model=list[MovimientoSalida])
def ver_movimientos(
    cuenta_id: int, s: SesionDep, limite: Annotated[int, Query(ge=1, le=100)] = 20, antes_de: int | None = None
):
    return [servicios.movimiento_a_dict(m) for m in servicios.movimientos(s, cuenta_id, limite, antes_de)]


@app.post("/cuentas/{cuenta_id}/depositos", response_model=MovimientoSalida, status_code=201)
def depositar(cuenta_id: int, op: Operacion, s: SesionDep):
    return servicios.movimiento_a_dict(servicios.depositar(s, cuenta_id, op.monto, op.descripcion))


@app.post("/cuentas/{cuenta_id}/retiros", response_model=MovimientoSalida, status_code=201)
def retirar(cuenta_id: int, op: Operacion, s: SesionDep):
    return servicios.movimiento_a_dict(servicios.retirar(s, cuenta_id, op.monto, op.descripcion))


@app.post("/transferencias", response_model=TransferenciaSalida, status_code=201)
def transferir(
    t: TransferenciaCrear, s: SesionDep, idempotency_key: Annotated[str | None, Header(max_length=80)] = None
):
    return servicios.transferir(s, t.origen_id, t.destino_id, t.monto, t.descripcion, idempotency_key)
