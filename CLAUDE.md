# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Qué es

Sistema de comandas para un evento scout: meseros toman pedidos desde el celular (`/`), la caja los
cobra (`/caja`), la cocina los prepara (`/cocina`). Código y UI en español — mantener ese idioma en
nombres, mensajes y comentarios. Precios son enteros (pesos sin decimales).

## Comandos

```bash
pip install -r requirements.txt          # dependencias
python app.py                            # dev local, http://localhost:5000 (servidor Flask, debug off)
rm scau.db scau.db-wal scau.db-shm       # resetear la base (se recrea con datos de ejemplo al arrancar)
```

No hay tests ni linter configurados. Producción = Vercel serverless (ver README). El deploy local de
evento (waitress + cloudflared) fue retirado del proyecto.

## Arquitectura

**Monolito Flask en `app.py`** (todas las rutas y la lógica) más una capa de datos en `db.py`. El
frontend es JS vanilla: `static/app.js` (mesero), `static/caja.js`, `static/cocina.js`, que hacen
polling a la API JSON. Las plantillas Jinja están en `templates/`.

**Base de datos dual (clave para entender el proyecto).** `db.py` abstrae SQLite vs PostgreSQL:
- Sin `DATABASE_URL` → SQLite local (`scau.db`, modo WAL para escrituras concurrentes).
- Con `DATABASE_URL` → PostgreSQL (Neon), usado en Vercel.
- Todo `app.py` escribe SQL estilo SQLite con placeholders `?`. `_PgConn` los traduce a `%s`,
  convierte `INSERT OR IGNORE INTO` en `... ON CONFLICT DO NOTHING` y `AUTOINCREMENT` en `SERIAL`.
  Al agregar SQL, seguí ese estilo y usá `db.insert(...)` (no `lastrowid`) para obtener el id nuevo —
  es el único método portable entre ambos motores.

**Despliegue:** Vercel serverless vía `api/index.py`, que envuelve la app Flask. `vercel.json` rutea
todo a ese archivo y `_PathFix` corrige el `PATH_INFO` si Vercel reescribe a `/api/index`. En local se
corre con `python app.py` (servidor de desarrollo de Flask) sobre SQLite.

**`init_db()` corre al importar el módulo** (no solo con `python app.py`). Crea el esquema, siembra
datos de ejemplo (productos, mesas, aderezos y 3 meseros) de forma idempotente, y aplica
migraciones SQLite in-place (rename `chico`→`mesero`, columnas `token`/`metodo_pago`/`aderezos`). Las
migraciones y los `PRAGMA table_info` solo se ejecutan cuando NO es Postgres.

**Máquina de estados del pedido** (`_cambiar_estado_pedido`): `pendiente → cobrado → finalizado`, con
`cancelado`. Las transiciones permitidas están en una matriz explícita; revertir a `pendiente` desde
`cobrado`/`finalizado` requiere ser caja. Un pedido solo aparece en cocina después de que caja lo marca
`cobrado`.

**Creación de pedido idempotente** (`api_crear_pedido`): el cliente manda un `token` para deduplicar
reenvíos; además un `threading.Lock` global más `numero` UNIQUE (hora `HHMMSS`) evitan colisiones. Si
cae `IntegrityError` se devuelve el pedido existente con `duplicado: True`.

## Autenticación (gotcha importante)

Cookie + token. `/caja` pide `CAJA_PASSWORD`, `/monitor` pide `MONITOR_PASSWORD`. Los tokens de sesión
(`_CAJA_TOKEN`, `_MONITOR_TOKEN`) se generan **por proceso** con `secrets`, salvo que se fijen
`CAJA_TOKEN`/`MONITOR_TOKEN` por variable de entorno. En serverless (Vercel) o con múltiples
instancias/reinicios, un token por proceso invalida las cookies existentes: para persistencia de login
hay que definir esas env vars. `/` (mesero) y `/cocina` no tienen auth.

## Configuración (variables de entorno)

Ver `.env.example`. Relevantes: `DATABASE_URL` (activa Postgres), `MP_ALIAS` (alias de Mercado Pago
mostrado al cobrar; también editable en runtime desde `/caja`, se guarda en la tabla `configuracion`),
`CAJA_PASSWORD`, `MONITOR_PASSWORD`. El `.env` nunca se commitea.

**`/monitor`** vigila el uso de Vercel (`VERCEL_TOKEN`/`VERCEL_TEAM_ID`/`VERCEL_PROJECT_ID`) y manda
alertas de WhatsApp vía CallMeBot (`CALLMEBOT_PHONE`/`CALLMEBOT_APIKEY`) cuando algún recurso pasa 70%.
En plan Hobby la API de usage no siempre responde, así que `_get_vercel_usage` cae a una estimación de
ejemplo. El "cron" es casero: el front de `/monitor` se auto-recarga cada ~5 min (no hay crons de Vercel).

## Zona horaria

Siempre usar `ahora()` (que fija `America/Argentina/Buenos_Aires`), nunca `datetime.now()` pelado —
el servidor puede estar en otra zona.
