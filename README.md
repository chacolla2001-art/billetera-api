# 💳 Billetera API

> 🇬🇧 [English version](README.en.md)

![Documentación interactiva de la API (Swagger UI)](docs/captura.png)

API REST de una billetera digital: cuentas en bolivianos o dólares, depósitos, retiros y **transferencias atómicas** entre cuentas, con **límite diario**, **idempotencia** y un libro de movimientos inmutable.

*Digital wallet REST API (FastAPI + SQLAlchemy): atomic transfers, idempotency keys, daily limits, integer-cent money handling and an immutable ledger.*

## Por qué es interesante
El manejo de dinero tiene trampas clásicas que este proyecto resuelve:
- **Sin errores de redondeo:** el dinero se guarda en **centavos enteros**, nunca como `float` (0,10 + 0,20 da exactamente 0,30).
- **Transferencias atómicas:** el débito y el crédito ocurren en la misma transacción; si algo falla, no cambia ningún saldo.
- **Idempotencia:** si el cliente reintenta una transferencia con el mismo encabezado `Idempotency-Key` (por ejemplo, tras un corte de red), no se cobra dos veces.
- **Concurrencia:** las filas se bloquean con `SELECT … FOR UPDATE` (en PostgreSQL) y siempre en el mismo orden, para evitar interbloqueos.
- **Reglas de negocio:** saldo nunca negativo (también como restricción de la base), misma moneda en transferencias y límite diario de 5.000 en egresos.

## Tecnología
Python 3.12, FastAPI, SQLAlchemy 2 (ORM), Pydantic 2 (validación), SQLite o PostgreSQL y pytest. Imagen Docker incluida.

## Cómo correrlo
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload     # http://localhost:8000/docs  (documentación interactiva)
pytest -q                         # 11 pruebas
```
Con Docker: `docker build -t billetera . && docker run -p 8000:8000 billetera`.
Para PostgreSQL: `DATABASE_URL=postgresql+psycopg://usuario:clave@host/db` (requiere instalar el controlador).

## Endpoints
| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/cuentas` | Crea una cuenta (`titular`, `moneda`: BOB o USD) |
| GET | `/cuentas/{id}` | Saldo y datos |
| GET | `/cuentas/{id}/movimientos?limite=&antes_de=` | Movimientos, del más reciente al más antiguo (paginados) |
| POST | `/cuentas/{id}/depositos` | Depósito (`monto` con hasta 2 decimales) |
| POST | `/cuentas/{id}/retiros` | Retiro (valida saldo y límite diario) |
| POST | `/transferencias` | Transferencia; encabezado opcional `Idempotency-Key` |

Ejemplo:
```bash
curl -X POST localhost:8000/transferencias -H "Content-Type: application/json" \
  -H "Idempotency-Key: pago-123" -d '{"origen_id": 1, "destino_id": 2, "monto": "30.50"}'
```

## Estructura
```
app/modelos.py     tablas (cuentas, movimientos, claves de idempotencia)
app/servicios.py   reglas de negocio
app/esquemas.py    validación de entrada y salida
app/main.py        rutas HTTP
tests/             pruebas de punta a punta con base en memoria
```

## Mejoras posibles
Autenticación con OAuth2/JWT, migraciones con Alembic, conversión de moneda con tipo de cambio y reportes de conciliación.

---
Licencia MIT.
