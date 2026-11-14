"""Pruebas de la API con una base SQLite en memoria (aislada en cada prueba)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.db import Base, crear_motor, obtener_sesion
from app.main import app


@pytest.fixture()
def cliente():
    motor = crear_motor("sqlite://")
    Base.metadata.create_all(motor)
    Sesion = sessionmaker(bind=motor, autoflush=False, expire_on_commit=False)

    def sesion_de_prueba():
        s = Sesion()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[obtener_sesion] = sesion_de_prueba
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def nueva_cuenta(c, titular="Ana Pérez", moneda="BOB", saldo=None):
    cuenta = c.post("/cuentas", json={"titular": titular, "moneda": moneda}).json()
    if saldo:
        c.post(f"/cuentas/{cuenta['id']}/depositos", json={"monto": saldo})
    return cuenta["id"]


def saldo(c, cuenta_id):
    return c.get(f"/cuentas/{cuenta_id}").json()["saldo"]


def test_crear_cuenta_empieza_en_cero(cliente):
    r = cliente.post("/cuentas", json={"titular": "Ana Pérez", "moneda": "USD"})
    assert r.status_code == 201
    assert r.json()["saldo"] == "0.00"
    assert r.json()["moneda"] == "USD"


def test_validaciones_de_entrada(cliente):
    assert cliente.post("/cuentas", json={"titular": "A"}).status_code == 422
    assert cliente.post("/cuentas", json={"titular": "Ana", "moneda": "EUR"}).status_code == 422
    cid = nueva_cuenta(cliente)
    assert cliente.post(f"/cuentas/{cid}/depositos", json={"monto": -5}).status_code == 422
    assert cliente.post(f"/cuentas/{cid}/depositos", json={"monto": "10.123"}).status_code == 422


def test_deposito_y_retiro_sin_errores_de_redondeo(cliente):
    cid = nueva_cuenta(cliente)
    for _ in range(3):
        cliente.post(f"/cuentas/{cid}/depositos", json={"monto": "0.10"})
    assert saldo(cliente, cid) == "0.30"  # con float daría 0.30000000000000004
    r = cliente.post(f"/cuentas/{cid}/retiros", json={"monto": "0.20"})
    assert r.status_code == 201
    assert r.json()["saldo_despues"] == "0.10"


def test_no_se_puede_retirar_mas_que_el_saldo(cliente):
    cid = nueva_cuenta(cliente, saldo="50")
    r = cliente.post(f"/cuentas/{cid}/retiros", json={"monto": "50.01"})
    assert r.status_code == 422
    assert "Saldo insuficiente" in r.json()["detail"]
    assert saldo(cliente, cid) == "50.00"


def test_transferencia_mueve_el_dinero_y_deja_dos_movimientos(cliente):
    a = nueva_cuenta(cliente, "Ana Pérez", saldo="100")
    b = nueva_cuenta(cliente, "Beto Rojas")
    r = cliente.post("/transferencias", json={"origen_id": a, "destino_id": b, "monto": "30.50"})
    assert r.status_code == 201
    datos = r.json()
    assert (datos["saldo_origen"], datos["saldo_destino"]) == ("69.50", "30.50")
    mov_a = cliente.get(f"/cuentas/{a}/movimientos").json()[0]
    mov_b = cliente.get(f"/cuentas/{b}/movimientos").json()[0]
    assert mov_a["tipo"] == "transferencia_salida" and mov_b["tipo"] == "transferencia_entrada"
    assert mov_a["referencia"] == mov_b["referencia"] == datos["referencia"]


def test_transferencia_fallida_no_cambia_ningun_saldo(cliente):
    a = nueva_cuenta(cliente, saldo="10")
    b = nueva_cuenta(cliente, "Beto Rojas")
    r = cliente.post("/transferencias", json={"origen_id": a, "destino_id": b, "monto": "20"})
    assert r.status_code == 422
    assert (saldo(cliente, a), saldo(cliente, b)) == ("10.00", "0.00")


def test_no_se_transfiere_entre_monedas_distintas_ni_a_si_misma(cliente):
    a = nueva_cuenta(cliente, moneda="BOB", saldo="100")
    b = nueva_cuenta(cliente, "Beto Rojas", moneda="USD")
    assert cliente.post("/transferencias", json={"origen_id": a, "destino_id": b, "monto": "1"}).status_code == 400
    assert cliente.post("/transferencias", json={"origen_id": a, "destino_id": a, "monto": "1"}).status_code == 400


def test_idempotencia_un_reintento_no_duplica_la_transferencia(cliente):
    a = nueva_cuenta(cliente, saldo="100")
    b = nueva_cuenta(cliente, "Beto Rojas")
    cuerpo = {"origen_id": a, "destino_id": b, "monto": "25"}
    primera = cliente.post("/transferencias", json=cuerpo, headers={"Idempotency-Key": "pago-123"})
    segunda = cliente.post("/transferencias", json=cuerpo, headers={"Idempotency-Key": "pago-123"})
    assert primera.json() == segunda.json()
    assert saldo(cliente, a) == "75.00"
    assert saldo(cliente, b) == "25.00"


def test_limite_diario_de_egresos(cliente):
    a = nueva_cuenta(cliente, saldo="9000")
    b = nueva_cuenta(cliente, "Beto Rojas")
    assert cliente.post(f"/cuentas/{a}/retiros", json={"monto": "3000"}).status_code == 201
    assert cliente.post("/transferencias", json={"origen_id": a, "destino_id": b, "monto": "2000"}).status_code == 201
    r = cliente.post(f"/cuentas/{a}/retiros", json={"monto": "0.01"})
    assert r.status_code == 422
    assert "límite diario" in r.json()["detail"]


def test_cuenta_inexistente_responde_404(cliente):
    assert cliente.get("/cuentas/999").status_code == 404
    assert cliente.post("/cuentas/999/depositos", json={"monto": "1"}).status_code == 404


def test_movimientos_paginados_del_mas_reciente_al_mas_antiguo(cliente):
    cid = nueva_cuenta(cliente)
    for monto in ("1", "2", "3"):
        cliente.post(f"/cuentas/{cid}/depositos", json={"monto": monto})
    pagina = cliente.get(f"/cuentas/{cid}/movimientos", params={"limite": 2}).json()
    assert [m["monto"] for m in pagina] == ["3.00", "2.00"]
    resto = cliente.get(f"/cuentas/{cid}/movimientos", params={"antes_de": pagina[-1]["id"]}).json()
    assert [m["monto"] for m in resto] == ["1.00"]
