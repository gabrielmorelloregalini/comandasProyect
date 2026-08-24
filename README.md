# Comandas del evento

Sistema de comandas para un evento scout. Los meseros toman pedidos desde su celular, la
caja los confirma como cobrados y la cocina ve los pedidos para preparar.

## Roles y URLs

| Rol | URL | Quien lo usa |
|---|---|---|
| Tomar pedidos | `/` | Meseros (camis/rovers), desde su celular |
| Caja | `/caja` | Adultos en caja (PC) |
| Cocina | `/cocina` | Adultos en cocina (PC) |

## Flujo

1. El mesero entra a `/` y elige su nombre.
2. Arma el pedido: mesa (de las que tiene asignadas), nombre del comensal y productos.
3. Confirma el pedido. El sistema genera el **número de pedido (hora:min:seg)** y calcula el **total**.
   En la pantalla ve el total y el **alias de Mercado Pago** para cobrar.
4. El mesero cobra (efectivo o transferencia) y le avisa el número al comensal.
5. La caja (`/caja`) ve la comanda pendiente y la marca como **"Cobrado"**.
6. Recién entonces la comanda aparece en la cocina (`/cocina`). El cocinero la prepara,
   la entrega con el número y la oculta de pantalla.
7. El mesero sigue sus pedidos en "Mis pedidos" para saber cuál retirar.

## Requisitos

- Python 3.8 o superior
- Dependencias: `pip install -r requirements.txt` (flask y waitress)

## Correr en local (para probar)

```bash
python3 app.py
```

Abrir `http://localhost:5000/` (pedidos), `http://localhost:5000/caja` (caja) y
`http://localhost:5000/cocina` (cocina).

> Nota: este modo usa el servidor de desarrollo de Flask. Sirve para probar.
> Para el evento usar el servidor de producción (ver abajo).

## Servidor de producción (Linux/Windows)

El sistema está pensado para ~50 usuarios simultáneos. Se sirve con **waitress**
(servidor WSGI multihilo, SQLite en modo WAL para escrituras concurrentes):

```bash
waitress-serve --listen=0.0.0.0:5000 --threads=16 app:app
```

- Los celulares de los meseros acceden a `http://IP-DE-LA-PC:5000/`.
- La caja a `http://IP-DE-LA-PC:5000/caja` y la cocina a `.../cocina`.
- `--threads` define cuántas peticiones atiende en paralelo (16 alcanza de sobra).

### Correr como servicio (Linux con systemd)

Crear `/etc/systemd/system/comandas.service`:

```ini
[Unit]
Description=Sistema de comandas del evento
After=network.target

[Service]
WorkingDirectory=/ruta/al/proyecto
ExecStart=/ruta/a/waitress-serve --listen=0.0.0.0:5000 --threads=16 app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now comandas
```

### Correr como servicio (Windows)

Guardar un acceso directo que ejecute
`waitress-serve --listen=0.0.0.0:5000 --threads=16 app:app`
desde la carpeta del proyecto y dejarlo en el inicio de sesión. Recordar abrir el
puerto 5000 en el firewall.

## Configuración

- **Alias de Mercado Pago**: se cambia en `app.py`, en la constante `MP_ALIAS`.
- **Datos de ejemplo**: el primer arranque carga productos, mesas y meseros de ejemplo.
  Se pueden editar desde la pestaña correspondiente en `/caja`.

## Resetear la base

Detener el servidor y borrar el archivo `scau.db` (y los `scau.db-wal`/`scau.db-shm`
si existen). Se vuelve a crear con los datos de ejemplo en el próximo arranque.

```bash
rm scau.db scau.db-wal scau.db-shm
```

## Despliegue en el evento (acceso desde otros dispositivos)

El servidor escucha en todas las interfaces (`0.0.0.0:5000`), así que funciona igual en
la red local sin cambiar nada. Opciones:

- **LAN**: todos los dispositivos conectados a la misma WiFi acceden a
  `http://IP-DE-LA-PC:5000/...`. Hay que abrir el puerto 5000 en el firewall de la PC.
- **Túnel público**: correr `cloudflared tunnel --url http://localhost:5000` para tener una
  URL HTTPS pública si la WiFi aísla dispositivos entre sí.
- **Hosting en la nube**: subir el mismo proyecto a Render/Railway/Fly.io si no se quiere
  depender de una PC prendida durante el evento.

Notas:
- Probar todo con una PC real del evento una semana antes.
- Al terminar, respaldar el archivo `scau.db` (contiene todos los pedidos).
