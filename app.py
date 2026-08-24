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
CAJA_PASSWORD = "soylacaja"
# =======================================

_CAJA_TOKEN = os.environ.get("CAJA_TOKEN") or secrets.token_urlsafe(32)

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
    if db.execute("SELECT COUNT(*) AS n FROM mesero").fetchone()["n"] == 0:
        meseros = [("Mesero 1", 1), ("Mesero 2", 3), ("Mesero 3", 5)]
        for nombre, mesa_id in meseros:
            mid = db.insert("INSERT INTO mesero (nombre) VALUES (?)", (nombre,))
            db.execute(
                "INSERT INTO mesero_mesa (mesero_id, mesa_id) VALUES (?, ?)",
                (mid, mesa_id),
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


def pedido_a_dict(row):
    db = get_db()
    items = db.execute(
        "SELECT nombre, precio, cantidad, aderezos FROM item_pedido WHERE pedido_id=?",
        (row["id"],),
    ).fetchall()
    mesero = db.execute("SELECT nombre FROM mesero WHERE id=?", (row["mesero_id"],)).fetchone()
    mesa = db.execute("SELECT nombre FROM mesa WHERE id=?", (row["mesa_id"],)).fetchone()
    return {
        "id": row["id"],
        "numero": row["numero"],
        "mesero": mesero["nombre"] if mesero else "-",
        "mesa": mesa["nombre"] if mesa else "-",
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
            for i in items
        ],
    }


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
    filas = db.execute("SELECT * FROM mesero WHERE activo=1 ORDER BY id").fetchall()
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
    if mesero_id is not None:
        filas = db.execute(
            "SELECT * FROM pedido WHERE mesero_id=? ORDER BY id DESC", (mesero_id,)
        ).fetchall()
    else:
        filas = db.execute("SELECT * FROM pedido ORDER BY id DESC").fetchall()
    return jsonify([pedido_a_dict(f) for f in filas])


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


@app.post("/api/pedidos/<int:pid>/cobrar")
def api_cobrar_pedido(pid):
    db = get_db()
    db.execute("UPDATE pedido SET estado='cobrado' WHERE id=?", (pid,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/pedidos/<int:pid>/cancelar")
def api_cancelar_pedido(pid):
    db = get_db()
    db.execute("UPDATE pedido SET estado='cancelado' WHERE id=?", (pid,))
    db.commit()
    return jsonify({"ok": True})


# ============ VENTAS ============
@app.get("/api/ventas")
def api_ventas():
    db = get_db()
    filas = db.execute(
        "SELECT COALESCE(metodo_pago, 'sin_registrar') AS metodo_pago, SUM(total) AS total "
        "FROM pedido WHERE estado='cobrado' GROUP BY metodo_pago"
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
