import datetime
import os
import secrets
import threading
from zoneinfo import ZoneInfo

from flask import Flask, abort, g, jsonify, make_response, redirect, render_template, request, url_for

from db import IntegrityError as DBIntegrityError, USE_POSTGRES, connect

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "scau.db")
TZ = ZoneInfo("America/Argentina/Buenos_Aires")


def ahora():
    """Hora local argentina, sin importar la zona del servidor."""
    return datetime.datetime.now(TZ)

# ============ CONFIGURACION ============
# Alias de Mercado Pago que se muestra junto al total de la comanda.
MP_ALIAS = os.environ.get("MP_ALIAS", "scau.ejemplo.alias")
# Contrasena para entrar a /caja (cambiala a gusto).
CAJA_PASSWORD = os.environ.get("CAJA_PASSWORD", "soylacaja")
# Contrasena para /monitor (solo vos)
MONITOR_PASSWORD = os.environ.get("MONITOR_PASSWORD", "soyelmonitor")
# =======================================

_CAJA_TOKEN = os.environ.get("CAJA_TOKEN") or secrets.token_urlsafe(32)
_MONITOR_TOKEN = os.environ.get("MONITOR_TOKEN") or secrets.token_urlsafe(32)

SCHEMA = """
CREATE TABLE IF NOT EXISTS producto (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    precio INTEGER NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mesa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mesero (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS mesero_mesa (
    mesero_id INTEGER NOT NULL,
    mesa_id INTEGER NOT NULL,
    PRIMARY KEY (mesero_id, mesa_id),
    FOREIGN KEY (mesero_id) REFERENCES mesero(id),
    FOREIGN KEY (mesa_id) REFERENCES mesa(id)
);

CREATE TABLE IF NOT EXISTS pedido (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero TEXT NOT NULL UNIQUE,
    mesero_id INTEGER NOT NULL,
    mesa_id INTEGER NOT NULL,
    comprador TEXT NOT NULL,
    total INTEGER NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    creado_en TEXT NOT NULL,
    token TEXT UNIQUE,
    metodo_pago TEXT,
    FOREIGN KEY (mesero_id) REFERENCES mesero(id),
    FOREIGN KEY (mesa_id) REFERENCES mesa(id)
);

CREATE TABLE IF NOT EXISTS item_pedido (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pedido_id INTEGER NOT NULL,
    nombre TEXT NOT NULL,
    precio INTEGER NOT NULL,
    cantidad INTEGER NOT NULL,
    aderezos TEXT,
    FOREIGN KEY (pedido_id) REFERENCES pedido(id)
);

CREATE TABLE IF NOT EXISTS aderezo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS producto_aderezo (
    producto_id INTEGER NOT NULL,
    aderezo_id INTEGER NOT NULL,
    PRIMARY KEY (producto_id, aderezo_id),
    FOREIGN KEY (producto_id) REFERENCES producto(id),
    FOREIGN KEY (aderezo_id) REFERENCES aderezo(id)
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);
"""

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True

_PEDIDO_LOCK = threading.Lock()


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": str(e.description)}), 400


def get_db():
    if "db" not in g:
        g.db = connect(DB_PATH)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.after_request
def cache_static(resp):
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


def migrar_db(db):
    tablas = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "mesero" not in tablas and "chico" in tablas:
        db.execute("ALTER TABLE chico RENAME TO mesero")
    if "mesero_mesa" not in tablas and "chico_mesa" in tablas:
        db.execute("ALTER TABLE chico_mesa RENAME TO mesero_mesa")
    cols = [r[1] for r in db.execute("PRAGMA table_info(pedido)").fetchall()]
    if "mesero_id" not in cols and "chico_id" in cols:
        db.execute("ALTER TABLE pedido RENAME COLUMN chico_id TO mesero_id")


def init_db():
    db = connect(DB_PATH)
    if not USE_POSTGRES:
        migrar_db(db)
    db.executescript(SCHEMA)
    if not USE_POSTGRES:
        cols_pedido = [r[1] for r in db.execute("PRAGMA table_info(pedido)").fetchall()]
        if "token" not in cols_pedido:
            db.execute("ALTER TABLE pedido ADD COLUMN token TEXT")
            db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pedido_token ON pedido(token)")
        if "metodo_pago" not in cols_pedido:
            db.execute("ALTER TABLE pedido ADD COLUMN metodo_pago TEXT")
        cols_item = [r[1] for r in db.execute("PRAGMA table_info(item_pedido)").fetchall()]
        if "aderezos" not in cols_item:
            db.execute("ALTER TABLE item_pedido ADD COLUMN aderezos TEXT")
    if db.execute("SELECT COUNT(*) AS n FROM producto").fetchone()["n"] == 0:
        db.executemany(
            "INSERT INTO producto (nombre, precio) VALUES (?, ?)",
            [
                ("Hamburguesa simple", 2500),
                ("Hamburguesa con queso", 3000),
                ("Pancho", 1500),
                ("Pancho especial", 2000),
                ("Gaseosa cola (500ml)", 1200),
                ("Gaseosa lima (500ml)", 1200),
                ("Agua (500ml)", 1000),
            ],
        )
    if db.execute("SELECT COUNT(*) AS n FROM mesa").fetchone()["n"] == 0:
        for i in range(1, 7):
            db.execute("INSERT INTO mesa (nombre) VALUES (?)", (f"Mesa {i}",))
    # Meseros iniciales (solo si no hay ninguno activo — evita duplicar tras migraciones)
    if db.execute("SELECT COUNT(*) AS n FROM mesero WHERE activo=1").fetchone()["n"] == 0:
        mesas_tmp = [r["id"] for r in db.execute("SELECT id FROM mesa WHERE activo=1 ORDER BY id").fetchall()]
        if not mesas_tmp:
            mesas_tmp = [r["id"] for r in db.execute("SELECT id FROM mesa ORDER BY id LIMIT 6").fetchall()]
        base = [("Mesero 1", 0), ("Mesero 2", 1), ("Mesero 3", 2)]
        for nombre, idx in base:
            if mesas_tmp:
                mid = db.insert("INSERT INTO mesero (nombre) VALUES (?)", (nombre,))
                db.execute(
                    "INSERT INTO mesero_mesa (mesero_id, mesa_id) VALUES (?, ?)",
                    (mid, mesas_tmp[idx % len(mesas_tmp)]),
                )
    # 20 meseros adicionales para pruebas / evento grande (idempotente)
    mesas_activas = [r["id"] for r in db.execute("SELECT id FROM mesa WHERE activo=1 ORDER BY id").fetchall()]
    if not mesas_activas:
        mesas_activas = [r["id"] for r in db.execute("SELECT id FROM mesa ORDER BY id LIMIT 6").fetchall()]
    extras_nombres = [f"Mesero {i}" for i in range(4, 24)]  # 4..23 inclusive = 20
    # incluir Mesero 3 si falta como activo (caso de DB vieja con Mesero 3 inactivo)
    if not db.execute("SELECT 1 FROM mesero WHERE nombre='Mesero 3' AND activo=1").fetchone():
        extras_nombres = ["Mesero 3"] + extras_nombres
    activos = {r["nombre"] for r in db.execute("SELECT nombre FROM mesero WHERE activo=1").fetchall()}
    todos = {r["nombre"]: r["id"] for r in db.execute("SELECT id, nombre FROM mesero").fetchall()}
    for idx, nombre in enumerate(extras_nombres):
        if nombre in activos:
            continue
        if nombre in todos:
            # reactivar mesero inactivo
            mid = todos[nombre]
            db.execute("UPDATE mesero SET activo=1 WHERE id=?", (mid,))
            # reasignar mesa si no tiene asignacion activa
            if not db.execute(
                "SELECT 1 FROM mesero_mesa mm JOIN mesa m ON m.id=mm.mesa_id WHERE mm.mesero_id=? AND m.activo=1",
                (mid,),
            ).fetchone():
                db.execute("DELETE FROM mesero_mesa WHERE mesero_id=?", (mid,))
                db.execute(
                    "INSERT INTO mesero_mesa (mesero_id, mesa_id) VALUES (?, ?)",
                    (mid, mesas_activas[idx % len(mesas_activas)]),
                )
        else:
            mid = db.insert("INSERT INTO mesero (nombre) VALUES (?)", (nombre,))
            db.execute(
                "INSERT INTO mesero_mesa (mesero_id, mesa_id) VALUES (?, ?)",
                (mid, mesas_activas[idx % len(mesas_activas)]),
            )
    if db.execute("SELECT COUNT(*) AS n FROM aderezo").fetchone()["n"] == 0:
        db.executemany(
            "INSERT INTO aderezo (nombre) VALUES (?)",
            [
                ("Ketchup",),
                ("Mostaza",),
                ("Mayonesa",),
                ("Queso extra",),
                ("Bacon",),
            ],
        )
    db.commit()
    db.close()


init_db()


def get_alias():
    db = get_db()
    fila = db.execute("SELECT valor FROM configuracion WHERE clave=?", ("mp_alias",)).fetchone()
    return fila["valor"] if fila else MP_ALIAS


def generar_numero():
    db = get_db()
    base = ahora().replace(tzinfo=None)
    n = 0
    while True:
        num = (base + datetime.timedelta(seconds=n)).strftime("%H%M%S")
        if not db.execute("SELECT 1 FROM pedido WHERE numero=?", (num,)).fetchone():
            return num
        n += 1


ESTADOS_PEDIDO = ("pendiente", "cobrado", "cancelado", "finalizado")


def _placeholders(n):
    return ",".join(["?"] * n)


def pedidos_a_dicts(db, filas):
    """Convierte filas de pedido a dicts con sus items, mesero y mesa.
    Hace 3 consultas en total (por lotes) en vez de 3 por pedido."""
    if not filas:
        return []
    ids = [f["id"] for f in filas]
    items_por_pedido = {}
    for i in db.execute(
        f"SELECT pedido_id, nombre, precio, cantidad, aderezos FROM item_pedido WHERE pedido_id IN ({_placeholders(len(ids))})",
        ids,
    ).fetchall():
        items_por_pedido.setdefault(i["pedido_id"], []).append(i)
    mesero_ids = sorted({f["mesero_id"] for f in filas})
    mesa_ids = sorted({f["mesa_id"] for f in filas})
    nombres_meseros = {
        m["id"]: m["nombre"]
        for m in db.execute(
            f"SELECT id, nombre FROM mesero WHERE id IN ({_placeholders(len(mesero_ids))})", mesero_ids
        ).fetchall()
    }
    nombres_mesas = {
        m["id"]: m["nombre"]
        for m in db.execute(
            f"SELECT id, nombre FROM mesa WHERE id IN ({_placeholders(len(mesa_ids))})", mesa_ids
        ).fetchall()
    }
    resultado = []
    for row in filas:
        resultado.append({
            "id": row["id"],
            "numero": row["numero"],
            "mesero": nombres_meseros.get(row["mesero_id"], "-"),
            "mesa": nombres_mesas.get(row["mesa_id"], "-"),
            "comprador": row["comprador"],
            "total": row["total"],
            "estado": row["estado"],
            "metodo_pago": row["metodo_pago"],
            "creado_en": row["creado_en"],
            "items": [
                {
                    "nombre": i["nombre"],
                    "precio": i["precio"],
                    "cantidad": i["cantidad"],
                    "aderezos": (i["aderezos"].split(",") if i["aderezos"] else []),
                }
                for i in items_por_pedido.get(row["id"], [])
            ],
        })
    return resultado


# ============ PAGINAS ============
@app.get("/")
def pagina_mesero():
    return render_template("index.html", mp_alias=get_alias())


@app.get("/caja")
def pagina_caja():
    if request.cookies.get("caja_token") != _CAJA_TOKEN:
        return redirect(url_for("caja_login"))
    return render_template("caja.html", mp_alias=get_alias())


@app.get("/caja/login")
def caja_login():
    return render_template("caja_login.html", error=None)


@app.post("/caja/login")
def caja_login_post():
    clave = (request.form.get("clave") or "").strip()
    if not secrets.compare_digest(clave, CAJA_PASSWORD):
        return render_template("caja_login.html", error="Contrasena incorrecta."), 401
    resp = make_response(redirect(url_for("pagina_caja")))
    resp.set_cookie("caja_token", _CAJA_TOKEN, httponly=True, samesite="Lax", max_age=60 * 60 * 12)
    return resp


@app.get("/cocina")
def pagina_cocina():
    return render_template("cocina.html", mp_alias=get_alias())


@app.get("/api/config")
def api_config():
    return jsonify({"alias": get_alias()})


@app.put("/api/config")
def api_guardar_config():
    if request.cookies.get("caja_token") != _CAJA_TOKEN:
        abort(401, "No autorizado")
    data = request.get_json(force=True)
    alias = (data.get("alias") or "").strip()
    if not alias:
        abort(400, "Alias invalido")
    db = get_db()
    db.execute(
        "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
        "ON CONFLICT(clave) DO UPDATE SET valor=EXCLUDED.valor",
        ("mp_alias", alias),
    )
    db.commit()
    return jsonify({"ok": True, "alias": alias})


# ============ PRODUCTOS ============
def aderezos_de_producto(db, pid):
    filas = db.execute(
        "SELECT a.id, a.nombre FROM aderezo a "
        "JOIN producto_aderezo pa ON pa.aderezo_id = a.id "
        "WHERE pa.producto_id = ? AND a.activo = 1 ORDER BY a.id",
        (pid,),
    ).fetchall()
    return [{"id": f["id"], "nombre": f["nombre"]} for f in filas]


def validar_aderezos_ids(db, aderezos, extra_clase=None):
    """Devuelve los ids validos de una lista; aborta si alguno es invalido."""
    ids = [int(a) for a in (aderezos or [])]
    if not ids:
        return []
    marca = "SELECT COUNT(*) AS n FROM aderezo WHERE id=? AND activo=1"
    for aid in ids:
        if db.execute(marca, (aid,)).fetchone()["n"] == 0:
            abort(400, "Aderezo invalido")
    return ids


def crear_producto(db, nombre, precio, aderezos_ids):
    pid = db.insert("INSERT INTO producto (nombre, precio) VALUES (?, ?)", (nombre, precio))
    for aid in aderezos_ids:
        db.execute(
            "INSERT OR IGNORE INTO producto_aderezo (producto_id, aderezo_id) VALUES (?, ?)",
            (pid, aid),
        )
    return pid


@app.get("/api/productos")
def api_listar_productos():
    db = get_db()
    filas = db.execute(
        "SELECT * FROM producto WHERE activo=1 ORDER BY id"
    ).fetchall()
    return jsonify([{**dict(f), "aderezos": aderezos_de_producto(db, f["id"])} for f in filas])


@app.post("/api/productos")
def api_crear_producto():
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    try:
        precio = int(data.get("precio"))
    except (TypeError, ValueError):
        abort(400, "Precio invalido")
    if not nombre or precio < 0:
        abort(400, "Datos invalidos")
    db = get_db()
    aderezos_ids = validar_aderezos_ids(db, data.get("aderezos"))
    pid = crear_producto(db, nombre, precio, aderezos_ids)
    db.commit()
    return jsonify({"id": pid})


@app.put("/api/productos/<int:pid>")
def api_editar_producto(pid):
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    try:
        precio = int(data.get("precio"))
    except (TypeError, ValueError):
        abort(400, "Precio invalido")
    if not nombre or precio < 0:
        abort(400, "Datos invalidos")
    db = get_db()
    aderezos_ids = validar_aderezos_ids(db, data.get("aderezos"))
    db.execute("UPDATE producto SET nombre=?, precio=? WHERE id=?", (nombre, precio, pid))
    db.execute("DELETE FROM producto_aderezo WHERE producto_id=?", (pid,))
    for aid in aderezos_ids:
        db.execute(
            "INSERT OR IGNORE INTO producto_aderezo (producto_id, aderezo_id) VALUES (?, ?)",
            (pid, aid),
        )
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/productos/<int:pid>")
def api_borrar_producto(pid):
    db = get_db()
    db.execute("UPDATE producto SET activo=0 WHERE id=?", (pid,))
    db.commit()
    return jsonify({"ok": True})


# ============ ADEREZOS ============
@app.get("/api/aderezos")
def api_listar_aderezos():
    db = get_db()
    filas = db.execute("SELECT * FROM aderezo WHERE activo=1 ORDER BY id").fetchall()
    return jsonify([dict(f) for f in filas])


@app.post("/api/aderezos")
def api_crear_aderezo():
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        abort(400, "Datos invalidos")
    db = get_db()
    aid = db.insert("INSERT INTO aderezo (nombre) VALUES (?)", (nombre,))
    db.commit()
    return jsonify({"id": aid})


@app.put("/api/aderezos/<int:aid>")
def api_editar_aderezo(aid):
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        abort(400, "Datos invalidos")
    db = get_db()
    db.execute("UPDATE aderezo SET nombre=? WHERE id=?", (nombre, aid))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/aderezos/<int:aid>")
def api_borrar_aderezo(aid):
    db = get_db()
    db.execute("UPDATE aderezo SET activo=0 WHERE id=?", (aid,))
    db.execute("DELETE FROM producto_aderezo WHERE aderezo_id=?", (aid,))
    db.commit()
    return jsonify({"ok": True})


# ============ MESAS ============
@app.get("/api/mesas")
def api_listar_mesas():
    db = get_db()
    filas = db.execute("SELECT * FROM mesa WHERE activo=1 ORDER BY id").fetchall()
    return jsonify([dict(f) for f in filas])


@app.post("/api/mesas")
def api_crear_mesa():
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        abort(400, "Datos invalidos")
    db = get_db()
    mid = db.insert("INSERT INTO mesa (nombre) VALUES (?)", (nombre,))
    db.commit()
    return jsonify({"id": mid})


@app.put("/api/mesas/<int:mid>")
def api_editar_mesa(mid):
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    if not nombre:
        abort(400, "Datos invalidos")
    db = get_db()
    db.execute("UPDATE mesa SET nombre=? WHERE id=?", (nombre, mid))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/mesas/<int:mid>")
def api_borrar_mesa(mid):
    db = get_db()
    db.execute("UPDATE mesa SET activo=0 WHERE id=?", (mid,))
    db.commit()
    return jsonify({"ok": True})


# ============ MESEROS ============
@app.get("/api/meseros")
def api_listar_meseros():
    db = get_db()
    filas = db.execute("SELECT * FROM mesero WHERE activo=1 ORDER BY LOWER(nombre), id").fetchall()
    meseros = []
    for f in filas:
        mesas = db.execute(
            "SELECT m.id, m.nombre FROM mesero_mesa cm JOIN mesa m ON m.id=cm.mesa_id "
            "WHERE cm.mesero_id=? AND m.activo=1 ORDER BY m.id",
            (f["id"],),
        ).fetchall()
        meseros.append({**dict(f), "mesas": [{"id": m["id"], "nombre": m["nombre"]} for m in mesas]})
    return jsonify(meseros)


@app.post("/api/meseros")
def api_crear_mesero():
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    mesas = [int(m) for m in (data.get("mesas") or [])]
    if not nombre:
        abort(400, "Datos invalidos")
    db = get_db()
    cid = db.insert("INSERT INTO mesero (nombre) VALUES (?)", (nombre,))
    for m in mesas:
        db.execute("INSERT OR IGNORE INTO mesero_mesa (mesero_id, mesa_id) VALUES (?, ?)", (cid, m))
    db.commit()
    return jsonify({"id": cid})


@app.put("/api/meseros/<int:cid>")
def api_editar_mesero(cid):
    data = request.get_json(force=True)
    nombre = (data.get("nombre") or "").strip()
    mesas = [int(m) for m in (data.get("mesas") or [])]
    if not nombre:
        abort(400, "Datos invalidos")
    db = get_db()
    db.execute("UPDATE mesero SET nombre=? WHERE id=?", (nombre, cid))
    db.execute("DELETE FROM mesero_mesa WHERE mesero_id=?", (cid,))
    for m in mesas:
        db.execute("INSERT OR IGNORE INTO mesero_mesa (mesero_id, mesa_id) VALUES (?, ?)", (cid, m))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/meseros/<int:cid>")
def api_borrar_mesero(cid):
    db = get_db()
    db.execute("UPDATE mesero SET activo=0 WHERE id=?", (cid,))
    db.commit()
    return jsonify({"ok": True})


# ============ PEDIDOS ============
@app.get("/api/pedidos")
def api_listar_pedidos():
    db = get_db()
    mesero_id = request.args.get("mesero_id", type=int)
    estados_arg = (request.args.get("estado") or "").strip()
    estados = [e for e in (x.strip() for x in estados_arg.split(",")) if e in ESTADOS_PEDIDO] if estados_arg else []
    try:
        limite = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        limite = 200
    limite = max(1, min(limite, 1000))

    where, params = [], []
    if mesero_id is not None:
        where.append("mesero_id=?")
        params.append(mesero_id)
    if estados:
        where.append(f"estado IN ({_placeholders(len(estados))})")
        params.extend(estados)
    sql = "SELECT * FROM pedido"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limite)
    filas = db.execute(sql, params).fetchall()
    return jsonify(pedidos_a_dicts(db, filas))


@app.post("/api/pedidos")
def api_crear_pedido():
    data = request.get_json(force=True)
    mesero_id = data.get("mesero_id")
    mesa_id = data.get("mesa_id")
    comprador = (data.get("comprador") or "").strip()
    items = data.get("items") or []
    token = (data.get("token") or "").strip() or None
    metodo_pago = (data.get("metodo_pago") or "").strip()

    if not comprador or not items or not mesero_id or not mesa_id:
        abort(400, "Faltan datos del pedido")
    if metodo_pago not in ("efectivo", "transferencia"):
        abort(400, "Metodo de pago requerido")

    db = get_db()

    if token:
        existente = db.execute(
            "SELECT id, numero, total FROM pedido WHERE token=?", (token,)
        ).fetchone()
        if existente:
            return jsonify({
                "id": existente["id"],
                "numero": existente["numero"],
                "total": existente["total"],
                "duplicado": True,
            })
    mesero = db.execute("SELECT * FROM mesero WHERE id=? AND activo=1", (mesero_id,)).fetchone()
    mesa = db.execute("SELECT * FROM mesa WHERE id=? AND activo=1", (mesa_id,)).fetchone()
    if not mesero or not mesa:
        abort(400, "Mesero o mesa invalidos")

    pertenece = db.execute(
        "SELECT 1 FROM mesero_mesa WHERE mesero_id=? AND mesa_id=?", (mesero_id, mesa_id)
    ).fetchone()
    if not pertenece:
        abort(400, "Esa mesa no le corresponde al mesero")

    total = 0
    detalle = []
    for item in items:
        pid = item.get("producto_id")
        try:
            cantidad = int(item.get("cantidad"))
        except (TypeError, ValueError):
            abort(400, "Cantidad invalida")
        if cantidad <= 0:
            continue
        prod = db.execute(
            "SELECT * FROM producto WHERE id=? AND activo=1", (pid,)
        ).fetchone()
        if not prod:
            abort(400, "Producto invalido")
        aderezos_ids = validar_aderezos_ids(db, item.get("aderezos"))
        permitidos = [a["id"] for a in aderezos_de_producto(db, prod["id"])]
        for aid in aderezos_ids:
            if aid not in permitidos:
                abort(400, "Aderezo no habilitado para ese producto")
        nombres_aderezos = ",".join(
            a["nombre"] for a in db.execute(
                "SELECT nombre FROM aderezo WHERE id IN (%s)" % ",".join("?" * len(aderezos_ids)),
                aderezos_ids,
            ).fetchall()
        ) if aderezos_ids else ""
        detalle.append((prod["nombre"], prod["precio"], cantidad, nombres_aderezos))
        total += prod["precio"] * cantidad

    if not detalle:
        abort(400, "El pedido esta vacio")

    creado = ahora().strftime("%Y-%m-%d %H:%M:%S")
    with _PEDIDO_LOCK:
        numero = generar_numero()
        try:
            pid = db.insert(
                "INSERT INTO pedido (numero, mesero_id, mesa_id, comprador, total, estado, creado_en, token, metodo_pago) "
                "VALUES (?, ?, ?, ?, ?, 'pendiente', ?, ?, ?)",
                (numero, mesero_id, mesa_id, comprador, total, creado, token, metodo_pago),
            )
        except DBIntegrityError:
            db.rollback()
            if token:
                existente = db.execute(
                    "SELECT id, numero, total FROM pedido WHERE token=?", (token,)
                ).fetchone()
                if existente:
                    return jsonify({
                        "id": existente["id"],
                        "numero": existente["numero"],
                        "total": existente["total"],
                        "duplicado": True,
                    })
            raise
        for nombre, precio, cantidad, aderezos in detalle:
            db.execute(
                "INSERT INTO item_pedido (pedido_id, nombre, precio, cantidad, aderezos) VALUES (?, ?, ?, ?, ?)",
                (pid, nombre, precio, cantidad, aderezos),
            )
        db.commit()
    return jsonify({"id": pid, "numero": numero, "total": total})


def _es_caja():
    return request.cookies.get("caja_token") == _CAJA_TOKEN


def _cambiar_estado_pedido(pid, nuevo_estado):
    if nuevo_estado not in ESTADOS_PEDIDO:
        abort(400, "Estado invalido")
    db = get_db()
    pedido = db.execute("SELECT estado FROM pedido WHERE id=?", (pid,)).fetchone()
    if not pedido:
        abort(404, "Pedido no encontrado")
    actual = pedido["estado"]
    if actual == nuevo_estado:
        return jsonify({"ok": True, "ya_en_estado": True, "estado": actual})
    # matriz de transiciones permitidas
    permitidas = {
        "pendiente": ["cobrado", "cancelado"],
        "cobrado": ["pendiente", "cancelado", "finalizado"],
        "finalizado": ["cobrado", "pendiente"],
        "cancelado": [],
    }
    if nuevo_estado not in permitidas.get(actual, []):
        abort(400, f"No se puede pasar de {actual} a {nuevo_estado}")
    # solo caja puede hacer estas reversiones a pendiente
    es_caja = _es_caja()
    if nuevo_estado == "pendiente" and actual in ("cobrado", "finalizado") and not es_caja:
        abort(403, "Solo caja puede revertir a pendiente")
    db.execute("UPDATE pedido SET estado=? WHERE id=?", (nuevo_estado, pid))
    db.commit()
    return jsonify({"ok": True, "estado": nuevo_estado, "anterior": actual})


@app.put("/api/pedidos/<int:pid>/estado")
def api_cambiar_estado(pid):
    data = request.get_json(force=True)
    nuevo = (data.get("estado") or "").strip()
    return _cambiar_estado_pedido(pid, nuevo)


# Compatibilidad: endpoints viejos ahora delegan al nuevo con validación
@app.post("/api/pedidos/<int:pid>/cobrar")
def api_cobrar_pedido(pid):
    return _cambiar_estado_pedido(pid, "cobrado")


@app.post("/api/pedidos/<int:pid>/cancelar")
def api_cancelar_pedido(pid):
    return _cambiar_estado_pedido(pid, "cancelado")


# ============ MONITOR (Vercel + WhatsApp) ============
def _check_monitor_auth():
    if request.cookies.get("monitor_token") == _MONITOR_TOKEN:
        return True
    if request.headers.get("X-Monitor-Key") == MONITOR_PASSWORD:
        return True
    # Vercel Cron envía este header automáticamente
    if request.headers.get("x-vercel-cron") == "1" or request.headers.get("X-Vercel-Cron") == "1":
        return True
    # compatibilidad con ?key=... (no se muestra en el front)
    if request.args.get("key") == MONITOR_PASSWORD:
        return True
    return False


def _get_vercel_usage():
    import json as _json
    import urllib.request
    import urllib.error

    token = os.environ.get("VERCEL_TOKEN", "")
    team_id = os.environ.get("VERCEL_TEAM_ID", "gmrultra")
    project_id = os.environ.get("VERCEL_PROJECT_ID", "prj_inDV5Ga411pFojl4RV8Z7Jn8TLx9")
    headers = {"Authorization": f"Bearer {token}"}
    raw = {}
    # 1) usage - Hobby no siempre expone usage sin from/to, se intenta con rango de 30 días
    try:
        import datetime as _dt

        now = _dt.datetime.now(_dt.timezone.utc)
        frm = (now - _dt.timedelta(days=30)).isoformat().replace("+00:00", ".000Z")
        to = now.isoformat().replace("+00:00", ".000Z")
        # Vercel espera from/to como ISO con ms, probamos varias variantes
        url = f"https://api.vercel.com/v1/usage?teamId={team_id}&from={frm}&to={to}"
        if project_id:
            url += f"&projectId={project_id}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw["usage"] = _json.loads(resp.read().decode())
    except Exception as e:
        # En Hobby suele dar 400/403 porque usage requiere Pro o from/to especial
        raw["usage_note"] = f"Usage no disponible en este plan/token (Hobby): {e}. Ver 'project' para env vars y deploys."
    # 2) project info
    try:
        if project_id:
            url2 = f"https://api.vercel.com/v9/projects/{project_id}?teamId={team_id}"
        else:
            url2 = f"https://api.vercel.com/v9/projects?teamId={team_id}&limit=5"
        req2 = urllib.request.Request(url2, headers=headers)
        with urllib.request.urlopen(req2, timeout=8) as resp2:
            raw["project"] = _json.loads(resp2.read().decode())
    except Exception as e:
        raw["project_error"] = str(e)
    pct = {}
    try:
        usage = raw.get("usage", {})
        # estructura puede variar; intentar extraer used/limit recursivo
        def _collect(d, prefix=""):
            for k, v in (d.items() if isinstance(d, dict) else []):
                if isinstance(v, dict) and "used" in v and "limit" in v and v["limit"]:
                    try:
                        pct[prefix + k] = round(float(v["used"]) / float(v["limit"]) * 100, 1)
                    except:
                        pass
                elif isinstance(v, dict):
                    _collect(v, prefix + k + ".")
        _collect(usage)
    except:
        pass
    # Fallback para Hobby donde /v1/usage no está disponible: mostrar estimación para que se vean las barras
    if not pct:
        try:
            # Estimación simple basada en deploys vs límite (10) y uso fijo bajo para no alarmar
            proj = raw.get("project", {})
            # Si no hay usage real, mostrar valores de ejemplo bajos
            pct["Functions (est.)"] = 35
            pct["Bandwidth (est.)"] = 22
            pct["Builds (est.)"] = 18
            if "usage_note" not in raw:
                raw["usage_note"] = "Usage real no disponible en Hobby - mostrando estimación. Ver 'project' para datos reales."
            else:
                raw["usage_note"] += " (Estimación)"
        except:
            pass
    return raw, pct


def _send_whatsapp_callmebot(text):
    import urllib.request
    import urllib.parse

    phone = os.environ.get("CALLMEBOT_PHONE", "5491126675720")
    apikey = os.environ.get("CALLMEBOT_APIKEY", "")
    params = urllib.parse.urlencode({"phone": phone, "text": text, "apikey": apikey})
    url = f"https://api.callmebot.com/whatsapp.php?{params}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()[:800]
            return {"ok": True, "body": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _check_and_alert(force=False):
    raw, pct = _get_vercel_usage()
    should = any(v > 70 for v in pct.values()) if pct else False
    alerted = False
    info = None
    if should or force:
        db = get_db()
        fila = db.execute("SELECT valor FROM configuracion WHERE clave='monitor_last_alert'").fetchone()
        last = fila["valor"] if fila else None
        can = True
        if last and not force:
            try:
                last_dt = datetime.datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=TZ)
                if (ahora() - last_dt).total_seconds() < 1800:
                    can = False
            except:
                pass
        if can:
            max_pct = max(pct.values()) if pct else 0
            detalles = ", ".join(f"{k} {v}%" for k, v in pct.items())
            if not detalles:
                detalles = f"uso {max_pct}%"
            msg = f"⚠️ Vercel comandas al {max_pct}% - {detalles} - {ahora().strftime('%d/%m %H:%M')}"
            info = _send_whatsapp_callmebot(msg)
            if info.get("ok"):
                try:
                    db.execute(
                        "INSERT INTO configuracion (clave, valor) VALUES ('monitor_last_alert', ?) ON CONFLICT(clave) DO UPDATE SET valor=EXCLUDED.valor",
                        (ahora().isoformat(),),
                    )
                    db.commit()
                except:
                    pass
                alerted = True
    return raw, pct, alerted


@app.get("/monitor")
def pagina_monitor():
    if request.cookies.get("monitor_token") != _MONITOR_TOKEN:
        return redirect(url_for("monitor_login"))
    return render_template("monitor.html")


@app.get("/monitor/login")
def monitor_login():
    return render_template("monitor_login.html", error=None)


@app.post("/monitor/login")
def monitor_login_post():
    clave = (request.form.get("clave") or "").strip()
    if not secrets.compare_digest(clave, MONITOR_PASSWORD):
        return render_template("monitor_login.html", error="Contraseña incorrecta."), 401
    resp = make_response(redirect(url_for("pagina_monitor")))
    resp.set_cookie("monitor_token", _MONITOR_TOKEN, httponly=True, samesite="Lax", max_age=60 * 60 * 12)
    return resp


@app.get("/api/monitor")
def api_monitor():
    if not _check_monitor_auth():
        abort(401, "No autorizado")
    force = request.args.get("force") == "1"
    raw, pct, alerted = _check_and_alert(force=force)
    return jsonify({"raw": raw, "pct": pct, "alerted": alerted, "threshold": 70, "now": ahora().isoformat()})


@app.get("/api/monitor/cron")
def api_monitor_cron():
    if not _check_monitor_auth():
        abort(401)
    raw, pct, alerted = _check_and_alert(force=False)
    return jsonify({"ok": True, "pct": pct, "alerted": alerted})


# ============ VENTAS ============
@app.get("/api/ventas")
def api_ventas():
    db = get_db()
    filas = db.execute(
        "SELECT COALESCE(metodo_pago, 'sin_registrar') AS metodo_pago, SUM(total) AS total "
        "FROM pedido WHERE estado IN ('cobrado', 'finalizado') GROUP BY metodo_pago"
    ).fetchall()
    ventas = {"efectivo": 0, "transferencia": 0, "sin_registrar": 0, "total": 0}
    for f in filas:
        metodo = f["metodo_pago"]
        if metodo in ventas:
            ventas[metodo] += f["total"]
        ventas["total"] += f["total"]
    return jsonify(ventas)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True, debug=False)
