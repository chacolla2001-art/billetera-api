"""Reglas de negocio: depósitos, retiros y transferencias atómicas con límite diario e idempotencia."""
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .modelos import ClaveIdempotencia, Cuenta, Movimiento

LIMITE_DIARIO_CENTAVOS = 5_000_00  # 5.000 por día en retiros y transferencias salientes
EGRESOS = ("retiro", "transferencia_salida")


class ErrorNegocio(Exception):
    def __init__(self, mensaje: str, estado: int = 400):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.estado = estado


def a_centavos(monto: Decimal) -> int:
    return int((monto * 100).to_integral_exact())


def formato(centavos: int) -> str:
    signo = "-" if centavos < 0 else ""
    centavos = abs(centavos)
    return f"{signo}{centavos // 100}.{centavos % 100:02d}"


def cuenta_a_dict(c: Cuenta) -> dict:
    return {"id": c.id, "titular": c.titular, "moneda": c.moneda, "saldo": formato(c.saldo_centavos), "creada": c.creada}


def movimiento_a_dict(m: Movimiento) -> dict:
    return {
        "id": m.id,
        "cuenta_id": m.cuenta_id,
        "tipo": m.tipo,
        "monto": formato(m.monto_centavos),
        "saldo_despues": formato(m.saldo_despues_centavos),
        "referencia": m.referencia,
        "descripcion": m.descripcion,
        "creado": m.creado,
    }


def crear_cuenta(s: Session, titular: str, moneda: str) -> Cuenta:
    c = Cuenta(titular=titular.strip(), moneda=moneda, saldo_centavos=0)
    s.add(c)
    s.commit()
    s.refresh(c)
    return c


def obtener_cuenta(s: Session, cuenta_id: int, bloquear: bool = False) -> Cuenta:
    consulta = select(Cuenta).where(Cuenta.id == cuenta_id)
    if bloquear:
        consulta = consulta.with_for_update()  # en PostgreSQL bloquea la fila hasta el commit
    cuenta = s.execute(consulta).scalar_one_or_none()
    if cuenta is None:
        raise ErrorNegocio(f"La cuenta {cuenta_id} no existe.", 404)
    return cuenta


def _registrar(s: Session, cuenta: Cuenta, tipo: str, monto: int, referencia: str | None, descripcion: str | None) -> Movimiento:
    m = Movimiento(
        cuenta_id=cuenta.id,
        tipo=tipo,
        monto_centavos=monto,
        saldo_despues_centavos=cuenta.saldo_centavos,
        referencia=referencia,
        descripcion=descripcion,
    )
    s.add(m)
    return m


def _utc(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def egresos_de_hoy(s: Session, cuenta_id: int) -> int:
    inicio = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    movs = s.execute(select(Movimiento).where(Movimiento.cuenta_id == cuenta_id, Movimiento.tipo.in_(EGRESOS))).scalars()
    return sum(m.monto_centavos for m in movs if _utc(m.creado) >= inicio)


def _validar_egreso(s: Session, cuenta: Cuenta, monto: int) -> None:
    if cuenta.saldo_centavos < monto:
        raise ErrorNegocio(f"Saldo insuficiente: tiene {formato(cuenta.saldo_centavos)} {cuenta.moneda}.", 422)
    if egresos_de_hoy(s, cuenta.id) + monto > LIMITE_DIARIO_CENTAVOS:
        raise ErrorNegocio(f"Supera el límite diario de {formato(LIMITE_DIARIO_CENTAVOS)} en retiros y transferencias.", 422)


def depositar(s: Session, cuenta_id: int, monto: Decimal, descripcion: str | None = None) -> Movimiento:
    cuenta = obtener_cuenta(s, cuenta_id, bloquear=True)
    centavos = a_centavos(monto)
    cuenta.saldo_centavos += centavos
    m = _registrar(s, cuenta, "deposito", centavos, None, descripcion)
    s.commit()
    return m


def retirar(s: Session, cuenta_id: int, monto: Decimal, descripcion: str | None = None) -> Movimiento:
    cuenta = obtener_cuenta(s, cuenta_id, bloquear=True)
    centavos = a_centavos(monto)
    _validar_egreso(s, cuenta, centavos)
    cuenta.saldo_centavos -= centavos
    m = _registrar(s, cuenta, "retiro", centavos, None, descripcion)
    s.commit()
    return m


def transferir(
    s: Session, origen_id: int, destino_id: int, monto: Decimal, descripcion: str | None = None, clave: str | None = None
) -> dict:
    """Mueve dinero entre dos cuentas en una sola transacción: o se hacen los dos movimientos o ninguno."""
    if clave:
        previa = s.get(ClaveIdempotencia, clave)
        if previa:
            return json.loads(previa.respuesta)
    if origen_id == destino_id:
        raise ErrorNegocio("La cuenta de origen y la de destino son la misma.")
    # Bloquear siempre en el mismo orden evita interbloqueos entre transferencias cruzadas.
    primero, segundo = sorted((origen_id, destino_id))
    cuentas = {primero: obtener_cuenta(s, primero, bloquear=True), segundo: obtener_cuenta(s, segundo, bloquear=True)}
    origen, destino = cuentas[origen_id], cuentas[destino_id]
    if origen.moneda != destino.moneda:
        raise ErrorNegocio(f"Las cuentas tienen monedas distintas ({origen.moneda} y {destino.moneda}).")
    centavos = a_centavos(monto)
    _validar_egreso(s, origen, centavos)

    referencia = uuid.uuid4().hex[:12]
    origen.saldo_centavos -= centavos
    destino.saldo_centavos += centavos
    _registrar(s, origen, "transferencia_salida", centavos, referencia, descripcion)
    _registrar(s, destino, "transferencia_entrada", centavos, referencia, descripcion)
    resultado = {
        "referencia": referencia,
        "origen_id": origen.id,
        "destino_id": destino.id,
        "monto": formato(centavos),
        "saldo_origen": formato(origen.saldo_centavos),
        "saldo_destino": formato(destino.saldo_centavos),
    }
    if clave:
        s.add(ClaveIdempotencia(clave=clave, respuesta=json.dumps(resultado)))
    try:
        s.commit()
    except IntegrityError:
        # Otro pedido con la misma clave terminó primero: se devuelve su resultado y no se duplica el dinero.
        s.rollback()
        previa = s.get(ClaveIdempotencia, clave) if clave else None
        if previa:
            return json.loads(previa.respuesta)
        raise
    return resultado


def movimientos(s: Session, cuenta_id: int, limite: int = 20, antes_de: int | None = None) -> list[Movimiento]:
    obtener_cuenta(s, cuenta_id)
    consulta = select(Movimiento).where(Movimiento.cuenta_id == cuenta_id)
    if antes_de:
        consulta = consulta.where(Movimiento.id < antes_de)
    return list(s.execute(consulta.order_by(Movimiento.id.desc()).limit(limite)).scalars())
