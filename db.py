import os
import sqlite3

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras

    IntegrityError = psycopg2.IntegrityError
else:
    IntegrityError = sqlite3.IntegrityError


class _PgConn:
    """Conexion PostgreSQL con la interfaz que usa la app (estilo sqlite3)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        if "INSERT OR IGNORE INTO" in sql:
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO") + " ON CONFLICT DO NOTHING"
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        if params:
            cur.execute(sql, tuple(params))
        else:
            cur.execute(sql)
        return cur

    def insert(self, sql, params=()):
        cur = self.execute(sql + " RETURNING id", params)
        return cur.fetchone()["id"]

    def executemany(self, sql, seq):
        for params in seq:
            self.execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def executescript(self, script):
        script = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        cur = self._conn.cursor()
        for stmt in filter(None, (s.strip() for s in script.split(";"))):
            cur.execute(stmt)
        self._conn.commit()
        cur.close()


class _SqliteConn:
    """Conexion SQLite con insert() unificado para que app.py sea agnostico."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        return self._conn.execute(sql, tuple(params))

    def insert(self, sql, params=()):
        return self._conn.execute(sql, tuple(params)).lastrowid

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def executescript(self, script):
        self._conn.executescript(script)


def connect(db_path=None):
    if USE_POSTGRES:
        return _PgConn(psycopg2.connect(DATABASE_URL))
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return _SqliteConn(conn)
