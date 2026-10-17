# Comandas del evento

Sistema de comandas para un evento scout. Los meseros toman pedidos desde el celular, la caja los
confirma como cobrados y la cocina ve los pedidos ya cobrados para prepararlos.

## Resumen

Web app en **Flask** (un solo archivo, `app.py`) con una pequeña capa de datos (`db.py`) que funciona
tanto sobre **SQLite** (local) como sobre **PostgreSQL** (en producción, vía la variable
`DATABASE_URL`). El frontend es JS vanilla servido desde `static/` + plantillas en `templates/`.

Tres pantallas, cada una con su URL:

| Pantalla | URL | Quién la usa |
|---|---|---|
| Tomar pedidos | `/` | Meseros, desde el celular |
| Caja | `/caja` | Caja (protegida con contraseña) |
| Cocina | `/cocina` | Cocina |

**Flujo:** el mesero arma el pedido (mesa asignada, comensal y productos) → se genera un número y el
total → cobra mostrando el alias de Mercado Pago → la **caja** marca el pedido como *cobrado* → recién
ahí aparece en **cocina**, que lo prepara y lo entrega por número.

El primer arranque carga datos de ejemplo (productos, mesas, aderezos y meseros), todos editables
desde `/caja`.

## Correr en local

Requiere Python 3.9+.

```bash
pip install -r requirements.txt
python app.py
```

Queda en `http://localhost:5000/` (pedidos), `/caja` y `/cocina`. Usa SQLite en `scau.db`.

Para resetear la base: detener la app y borrar el archivo.

```bash
rm scau.db scau.db-wal scau.db-shm
```

### Variables de entorno (opcional en local)

Copiar `.env.example` a `.env` y ajustar. Las más usadas:

- `MP_ALIAS` — alias de Mercado Pago que se muestra al cobrar (también editable desde `/caja`).
- `CAJA_PASSWORD` — contraseña de `/caja`.
- `MONITOR_PASSWORD` — contraseña de `/monitor` (panel de uso de Vercel).

Sin `.env` la app arranca igual con valores por defecto.

## Deploy en Vercel

El repo ya está listo para Vercel: `api/index.py` envuelve la app Flask y `vercel.json` rutea todo
el tráfico a ese handler.

1. **Base de datos.** Crear una Postgres (p. ej. [Neon](https://neon.tech)) y copiar su connection
   string. En serverless no se puede usar SQLite, así que `DATABASE_URL` es obligatoria.

2. **Importar el repo en Vercel** (New Project → importar este repositorio). El framework se detecta
   solo por `vercel.json`; no hace falta build command.

3. **Cargar las variables de entorno** en *Settings → Environment Variables*:

   | Variable | Para qué | ¿Obligatoria? |
   |---|---|---|
   | `DATABASE_URL` | Postgres (Neon) | **Sí** |
   | `MP_ALIAS` | Alias de Mercado Pago | Sí |
   | `CAJA_PASSWORD` | Contraseña de `/caja` | Sí |
   | `MONITOR_PASSWORD` | Contraseña de `/monitor` | Sí |
   | `CAJA_TOKEN`, `MONITOR_TOKEN` | Mantener la sesión entre instancias serverless (ver nota) | Recomendadas |
   | `VERCEL_TOKEN`, `VERCEL_TEAM_ID`, `VERCEL_PROJECT_ID` | Panel `/monitor` de uso de Vercel | Opcionales |
   | `CALLMEBOT_PHONE`, `CALLMEBOT_APIKEY` | Alertas de WhatsApp al 70% de uso | Opcionales |

4. **Deploy.** Cada push a la rama conectada redepliega. Al terminar, las URLs son
   `https://TU-PROYECTO.vercel.app/`, `/caja` y `/cocina`.

> **Nota sobre el login:** los tokens de sesión de `/caja` y `/monitor` se generan por proceso. Como
> Vercel levanta varias instancias, hay que fijar `CAJA_TOKEN` y `MONITOR_TOKEN` (cualquier string
> secreto largo) para que la cookie de login siga siendo válida en todas. Sin ellas, el login se
> "pierde" al cambiar de instancia.
