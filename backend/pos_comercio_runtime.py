from __future__ import annotations

import base64
import contextvars
import json
import hashlib
import math
import os
import queue
import re
import secrets
import sqlite3
import sys
import threading
from datetime import datetime, timedelta
from http import HTTPStatus
from http.client import HTTPException
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
LOCAL_DATA_DIRECTORY = Path(os.getenv("LOCALAPPDATA", Path.home())) / "FerrePOS"
DEFAULT_ENV_FILE = (
    LOCAL_DATA_DIRECTORY / ".env"
    if getattr(sys, "frozen", False)
    else ROOT / ".env"
)
load_dotenv(os.getenv("OZZVON_ENV_FILE", DEFAULT_ENV_FILE))
SUPABASE_DATABASE_URL = os.getenv("SUPABASE_DATABASE_URL", "").strip()
HOST = os.getenv("HOST", "127.0.0.1")
CLOUD_API_BASE = os.getenv("OZZVON_API_BASE", "https://www.ozzvon.com").strip().rstrip("/")
CLOUD_PROXY_MAX_BODY = 10 * 1024 * 1024
# DATABASE = Path(os.getenv("DATABASE_PATH", ROOT / "punto_de_venta.db"))
SESSIONS: dict[str, int] = {}
EVENT_STREAMS: list[queue.Queue] = []
ALL_PERMISSIONS = [
    "dashboard.view", "sales.create", "inventory.view", "inventory.manage",
    "clients.view", "clients.manage", "reports.view", "cash.view",
    "cash.manage", "users.manage", "settings.manage", "billing.view",
]
BUSINESS_ICON_CHOICES = {"cart", "box", "home", "users", "cash", "gear"}
MAX_BUSINESS_LOGO_BYTES = 512 * 1024
_DATABASE_LOCK = threading.RLock()
_DATABASE: psycopg.Connection | None = None
_DATABASE_INITIALIZED = False
_TENANT_DATABASE_PATH: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "ozzvon_pos_tenant_database", default=None
)


class ApiError(Exception):
    pass


def cloud_proxy_path_allowed(method: str, path: str) -> bool:
    exact_paths = {
        ("POST", "/api/pos/pos_comercio/login"),
        ("GET", "/api/pos/pos_comercio/branches"),
        ("POST", "/api/pos/logout"),
    }
    if (method, path) in exact_paths:
        return True
    if re.fullmatch(r"/api/pos/pos_comercio/sucursales/[1-9]\d*/login", path):
        return method == "POST"
    match = re.fullmatch(
        r"/api/pos/pos_comercio/sucursales/[1-9]\d*/api/(.+)", path
    )
    if not match:
        return False
    return cloud_pos_operation_allowed(method, match.group(1))


def cloud_pos_operation_allowed(method: str, path: str) -> bool:
    exact_paths = {
        "GET": {
            "products", "clients", "sales", "suppliers", "purchases",
            "cash/current", "cash/history", "reports", "settings", "tax-rate",
            "ticket-templates", "invoices", "users", "roles",
            "business-name",
        },
        "POST": {
            "products/bulk", "logout", "users", "clients", "suppliers",
            "purchases", "payments", "sales", "cash/open", "cash/movement",
            "cash/close", "settings", "ticket-templates", "invoices",
        },
    }
    if path in exact_paths.get(method, set()):
        return True
    return method in {"PUT", "DELETE"} and bool(
        re.fullmatch(r"(?:products|clients|users|ticket-templates)/[1-9]\d*", path)
    )


def cloud_api_url(path: str, query: str) -> str:
    parsed = urlparse(CLOUD_API_BASE)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError(
            "OZZVON_API_BASE debe ser un origen HTTPS sin ruta, usuario ni parámetros."
        )
    return f"{CLOUD_API_BASE}{path}" + (f"?{query}" if query else "")


class NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None

DatabaseError = psycopg.Error
DatabaseIntegrityError = psycopg.IntegrityError


class PostgresCursor:
    def __init__(self, cursor: psycopg.Cursor, returns_id: bool = False) -> None:
        self._cursor = cursor
        self._returns_id = returns_id
        row = cursor.fetchone() if returns_id else None
        self._lastrowid = row["id"] if row is not None else None

    @property
    def lastrowid(self):
        return self._lastrowid

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class PostgresConnection:
    _ID_TABLES = {
        "cajas", "movimientos_caja", "roles", "usuarios", "ventas",
        "detalle_ventas", "facturas", "ticket_templates", "proveedores",
        "compras", "detalle_compras", "clientes", "productos",
    }

    def __init__(self, database: psycopg.Connection) -> None:
        self._database = database

    def __getattr__(self, name):
        return getattr(self._database, name)

    def execute(self, sql: str, params=()):
        pragma = re.fullmatch(r'\s*PRAGMA\s+table_info\("?(?P<table>[^")]+)"?\)\s*', sql, re.I)
        if pragma:
            cursor = self._database.execute(
                "SELECT column_name AS name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s "
                "ORDER BY ordinal_position",
                (pragma.group("table"),),
            )
            return PostgresCursor(cursor)

        if "sqlite_master" in sql:
            sql = (
                "SELECT table_name AS name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
                "AND table_name NOT LIKE 'sqlite_%'"
            )

        ignore_conflict = bool(re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\b", sql, re.I))
        if ignore_conflict:
            sql = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, count=1, flags=re.I)
            sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

        insert = re.match(
            r'\s*INSERT\s+INTO\s+(?:"(?P<quoted>[^"]+)"|(?P<plain>[a-zA-Z_][\w]*))',
            sql,
            re.I,
        )
        returns_id = bool(
            insert
            and (insert.group("quoted") or insert.group("plain")).lower() in self._ID_TABLES
            and "RETURNING" not in sql.upper()
        )
        if returns_id:
            sql = sql.rstrip().rstrip(";") + " RETURNING id"

        sql = sql.replace("?", "%s")
        cursor = self._database.execute(sql, params if params else None, prepare=False)
        return PostgresCursor(cursor, returns_id=returns_id)

    def executescript(self, sql: str) -> None:
        sql = sql.replace(
            "INTEGER PRIMARY KEY AUTOINCREMENT",
            "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        )
        sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql)
        for statement in sql.split(";"):
            statement = statement.strip()
            if statement:
                self._database.execute(statement, prepare=False)

def query_db(sql: str, params: tuple | list | dict = ()):
    """Ejecuta una consulta SQL en Supabase PostgreSQL."""
    database = connection()
    try:
        return database.execute(sql, params).fetchall()
    finally:
        database.close()




def publish_event(resource: str, action: str = "updated") -> None:
    event = json.dumps({"resource": resource, "action": action}, ensure_ascii=False)
    for stream in list(EVENT_STREAMS):
        try:
            stream.put_nowait(event)
        except queue.Full:
            pass


class ReusableDatabaseConnection:
    def __init__(self, database: PostgresConnection):
        self._database = database
        self._closed = False

    def __getattr__(self, name):
        return getattr(self._database, name)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._database.info.transaction_status != psycopg.pq.TransactionStatus.IDLE:
                self._database.rollback()
        finally:
            _DATABASE_LOCK.release()


def connection() -> ReusableDatabaseConnection:
    global _DATABASE, _DATABASE_INITIALIZED
    tenant_database_path = _TENANT_DATABASE_PATH.get()
    if tenant_database_path is not None:
        database = sqlite3.connect(
            tenant_database_path,
            timeout=10,
            factory=ClosingSQLiteConnection,
        )
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys = ON")
        return database
    _DATABASE_LOCK.acquire()
    try:
        if not SUPABASE_DATABASE_URL:
            raise RuntimeError("Configura SUPABASE_DATABASE_URL con la conexión PostgreSQL privada de Supabase.")
        if _DATABASE is None:
            _DATABASE = psycopg.connect(SUPABASE_DATABASE_URL, row_factory=dict_row)
        if not _DATABASE_INITIALIZED:
            _initialize_database(PostgresConnection(_DATABASE))
            _DATABASE_INITIALIZED = True
        return ReusableDatabaseConnection(PostgresConnection(_DATABASE))
    except Exception:
        if _DATABASE is not None and not _DATABASE_INITIALIZED:
            _DATABASE.close()
            _DATABASE = None
        _DATABASE_LOCK.release()
        raise


class ClosingSQLiteConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def use_tenant_database(database_path: str):
    return _TENANT_DATABASE_PATH.set(database_path)


def reset_tenant_database(token) -> None:
    _TENANT_DATABASE_PATH.reset(token)


def _initialize_database(database: PostgresConnection) -> None:
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            telefono TEXT,
            saldo_deudor REAL DEFAULT 0.0
        );
        CREATE TABLE IF NOT EXISTS productos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            nombre TEXT NOT NULL,
            precio_compra REAL NOT NULL,
            precio_venta REAL NOT NULL,
            stock INTEGER NOT NULL
        );
        """
    )
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS cajas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_apertura TEXT NOT NULL,
            fondo_inicial REAL NOT NULL DEFAULT 0,
            fecha_cierre TEXT,
            efectivo_final REAL,
            estado TEXT NOT NULL DEFAULT 'abierta'
        );
        CREATE TABLE IF NOT EXISTS movimientos_caja (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caja_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            monto REAL NOT NULL,
            concepto TEXT NOT NULL DEFAULT '',
            fecha TEXT NOT NULL,
            FOREIGN KEY (caja_id) REFERENCES cajas(id)
        );
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            permisos TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            usuario TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            rol_id INTEGER NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (rol_id) REFERENCES roles(id)
        );
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            total REAL NOT NULL,
            subtotal REAL,
            iva REAL,
            tasa_iva REAL,
            metodo_pago TEXT NOT NULL DEFAULT 'Efectivo',
            cliente_id INTEGER,
            usuario_id INTEGER,
            FOREIGN KEY (cliente_id) REFERENCES clientes(id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
        CREATE TABLE IF NOT EXISTS detalle_ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas(id)
        );
        CREATE TABLE IF NOT EXISTS ajustes (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS facturas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id INTEGER NOT NULL,
            cliente_id INTEGER,
            rfc TEXT NOT NULL,
            razon_social TEXT NOT NULL,
            uso_cfdi TEXT NOT NULL DEFAULT 'G03',
            serie TEXT NOT NULL DEFAULT 'A',
            folio INTEGER NOT NULL,
            estado TEXT NOT NULL DEFAULT 'pendiente',
            uuid TEXT,
            fecha TEXT NOT NULL,
            FOREIGN KEY (venta_id) REFERENCES ventas(id),
            FOREIGN KEY (cliente_id) REFERENCES clientes(id)
        );
        CREATE TABLE IF NOT EXISTS ticket_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            diseno TEXT NOT NULL,
            predeterminada INTEGER NOT NULL DEFAULT 0,
            actualizada TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proveedores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            contacto TEXT NOT NULL DEFAULT '',
            telefono TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            creado TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proveedor_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            total REAL NOT NULL,
            notas TEXT NOT NULL DEFAULT '',
            usuario_id INTEGER,
            FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        );
        CREATE TABLE IF NOT EXISTS detalle_compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            compra_id INTEGER NOT NULL,
            producto_id INTEGER NOT NULL,
            codigo TEXT NOT NULL,
            producto TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            costo_unitario REAL NOT NULL,
            subtotal REAL NOT NULL,
            FOREIGN KEY (compra_id) REFERENCES compras(id)
        );
        """
    )
    ensure_column(database, "ventas", "usuario_id", "INTEGER")
    ensure_column(database, "ventas", "subtotal", "REAL")
    ensure_column(database, "ventas", "iva", "REAL")
    ensure_column(database, "ventas", "tasa_iva", "REAL")
    ensure_column(database, "cajas", "usuario_id", "INTEGER")
    ensure_column(database, "movimientos_caja", "usuario_id", "INTEGER")
    database.executescript(
        """
        ALTER TABLE cajas ENABLE ROW LEVEL SECURITY;
        ALTER TABLE movimientos_caja ENABLE ROW LEVEL SECURITY;
        ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ventas ENABLE ROW LEVEL SECURITY;
        ALTER TABLE detalle_ventas ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ajustes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE facturas ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ticket_templates ENABLE ROW LEVEL SECURITY;
        ALTER TABLE proveedores ENABLE ROW LEVEL SECURITY;
        ALTER TABLE compras ENABLE ROW LEVEL SECURITY;
        ALTER TABLE detalle_compras ENABLE ROW LEVEL SECURITY;
        ALTER TABLE clientes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE productos ENABLE ROW LEVEL SECURITY;
        REVOKE ALL ON cajas, movimientos_caja, roles, usuarios, ventas,
            detalle_ventas, ajustes, facturas, ticket_templates, proveedores,
            compras, detalle_compras, clientes, productos FROM anon, authenticated;
        """
    )
    seed_security(database)
    seed_settings(database)
    seed_ticket_templates(database)
    database.commit()


def close_database() -> None:
    global _DATABASE, _DATABASE_INITIALIZED
    with _DATABASE_LOCK:
        if _DATABASE is not None:
            _DATABASE.close()
            _DATABASE = None
        _DATABASE_INITIALIZED = False


def ensure_column(database: PostgresConnection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in database.execute(f'PRAGMA table_info("{table}")')}
    if column not in columns:
        database.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}')


PASSWORD_HASH_ITERATIONS = 310_000


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(stored_hash: str, password: str) -> bool:
    if stored_hash.startswith("pbkdf2_sha256$"):
        try:
            algorithm, iterations, salt_hex, digest_hex = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False
            actual = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            ).hex()
            return secrets.compare_digest(actual, digest_hex)
        except (ValueError, UnicodeEncodeError):
            return False
    if re.fullmatch(r"[0-9a-f]{64}", stored_hash):
        return secrets.compare_digest(
            stored_hash, hashlib.sha256(password.encode("utf-8")).hexdigest()
        )
    return False


DUMMY_PASSWORD_HASH = password_hash("not-a-real-pos-user-password")


def password_needs_rehash(stored_hash: str) -> bool:
    return not stored_hash.startswith(f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}$")


def seed_security(database: PostgresConnection) -> None:
    roles = {
        "Administrador": ALL_PERMISSIONS,
        "Cajero": ["dashboard.view", "sales.create", "inventory.view", "clients.view", "cash.view"],
        "Encargado": ["dashboard.view", "sales.create", "inventory.view", "inventory.manage", "clients.view", "clients.manage", "reports.view", "cash.view", "cash.manage"],
    }
    for name, permissions in roles.items():
        database.execute(
            "INSERT OR IGNORE INTO roles (nombre, permisos) VALUES (?, ?)",
            (name, json.dumps(permissions, ensure_ascii=False)),
        )
    admin_role = database.execute("SELECT id FROM roles WHERE nombre = 'Administrador'").fetchone()["id"]
    if not database.execute("SELECT 1 FROM usuarios WHERE usuario = 'admin'").fetchone():
        initial_password = os.getenv("POS_INITIAL_ADMIN_PASSWORD", "")
        if len(initial_password) < 12:
            raise RuntimeError(
                "Configura POS_INITIAL_ADMIN_PASSWORD con al menos 12 caracteres antes del primer inicio."
            )
        database.execute(
            "INSERT INTO usuarios (nombre, usuario, password_hash, rol_id) VALUES (?, ?, ?, ?)",
            ("Administrador", "admin", password_hash(initial_password), admin_role),
        )


def seed_settings(database: PostgresConnection) -> None:
    defaults = {
        "business_name": "OZZVON POS",
        "business_icon": "cart",
        "business_logo": "",
        "business_rfc": "",
        "business_phone": "",
        "business_address": "",
        "ticket_footer": "Gracias por su compra",
        "currency": "MXN",
        "vat_rate": "16",
    }
    for key, value in defaults.items():
        database.execute("INSERT OR IGNORE INTO ajustes (clave, valor) VALUES (?, ?)", (key, value))
    database.execute(
        "UPDATE ajustes SET valor = ? WHERE clave = ? AND valor = ?",
        ("OZZVON POS", "business_name", "Ferretería Centro"),
    )


def seed_ticket_templates(database: PostgresConnection) -> None:
    templates = {
        "Clásica": [
            {"type": "business", "text": "{{business_name}}", "x": 24, "y": 24, "w": 252, "h": 30, "size": 20, "align": "center", "bold": True},
            {"type": "meta", "text": "{{business_rfc}}\n{{business_phone}}", "x": 24, "y": 62, "w": 252, "h": 42, "size": 11, "align": "center", "bold": False},
            {"type": "divider", "text": "------------------------------", "x": 24, "y": 116, "w": 252, "h": 24, "size": 11, "align": "center", "bold": False},
            {"type": "items", "text": "{{items}}", "x": 24, "y": 148, "w": 252, "h": 120, "size": 12, "align": "left", "bold": False},
            {"type": "total", "text": "TOTAL  {{total}}", "x": 24, "y": 282, "w": 252, "h": 32, "size": 16, "align": "right", "bold": True},
            {"type": "footer", "text": "{{ticket_footer}}", "x": 24, "y": 334, "w": 252, "h": 42, "size": 11, "align": "center", "bold": False},
        ],
        "Compacta": [
            {"type": "business", "text": "{{business_name}}", "x": 18, "y": 18, "w": 264, "h": 28, "size": 17, "align": "left", "bold": True},
            {"type": "meta", "text": "{{date}}  #{{sale_id}}", "x": 18, "y": 52, "w": 264, "h": 22, "size": 11, "align": "left", "bold": False},
            {"type": "items", "text": "{{items}}", "x": 18, "y": 82, "w": 264, "h": 140, "size": 11, "align": "left", "bold": False},
            {"type": "total", "text": "TOTAL {{total}}", "x": 18, "y": 238, "w": 264, "h": 30, "size": 15, "align": "right", "bold": True},
            {"type": "footer", "text": "{{ticket_footer}}", "x": 18, "y": 282, "w": 264, "h": 40, "size": 10, "align": "center", "bold": False},
        ],
        "Minimalista": [
            {"type": "business", "text": "{{business_name}}", "x": 24, "y": 30, "w": 252, "h": 32, "size": 18, "align": "center", "bold": True},
            {"type": "total", "text": "{{total}}", "x": 24, "y": 92, "w": 252, "h": 44, "size": 26, "align": "center", "bold": True},
            {"type": "items", "text": "{{items}}", "x": 24, "y": 154, "w": 252, "h": 120, "size": 12, "align": "center", "bold": False},
            {"type": "footer", "text": "{{ticket_footer}}", "x": 24, "y": 294, "w": 252, "h": 42, "size": 11, "align": "center", "bold": False},
        ],
    }
    for name, blocks in templates.items():
        database.execute(
            "INSERT OR IGNORE INTO ticket_templates (nombre, diseno, predeterminada, actualizada) VALUES (?, ?, ?, ?)",
            (name, json.dumps(blocks, ensure_ascii=False), 1 if name == "Clásica" else 0, datetime.now().isoformat(timespec="seconds")),
        )


def tables(database: PostgresConnection) -> list[str]:
    rows = database.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return [row["name"] for row in rows]


def find_products_table(database: PostgresConnection) -> tuple[str, list[str]]:
    candidates = ("products", "productos", "product", "inventario", "inventory")
    available = tables(database)
    table = next((name for name in candidates if name in available), None)
    if table is None:
        raise ApiError(f"No se encontró una tabla de productos. Tablas: {available}")
    columns = [row["name"] for row in database.execute(f'PRAGMA table_info("{table}")')]
    return table, columns


def first_column(columns: list[str], options: tuple[str, ...], required: bool = True) -> str | None:
    column = next((name for name in options if name in columns), None)
    if required and column is None:
        raise ApiError(f"Falta una columna requerida. Disponibles: {columns}")
    return column


def user_payload(database: PostgresConnection, user_id: int) -> dict:
    row = database.execute(
        "SELECT usuarios.id, usuarios.nombre, usuarios.usuario, roles.nombre AS rol, roles.permisos "
        "FROM usuarios JOIN roles ON roles.id = usuarios.rol_id "
        "WHERE usuarios.id = ? AND usuarios.activo = 1",
        (user_id,),
    ).fetchone()
    if row is None:
        raise ApiError("Usuario no encontrado o inactivo")
    return {
        "id": row["id"],
        "name": row["nombre"],
        "username": row["usuario"],
        "role": row["rol"],
        "permissions": json.loads(row["permisos"]),
    }


def authenticate(payload: dict) -> tuple[str, dict]:
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    database = connection()
    try:
        row = database.execute(
            "SELECT id, password_hash FROM usuarios WHERE usuario = ? AND activo = 1",
            (username,),
        ).fetchone()
        matches = (
            verify_password(
                row["password_hash"] if row else DUMMY_PASSWORD_HASH, password
            )
        )
        if row is None or not matches:
            raise ApiError("Usuario o contraseña incorrectos")
        if password_needs_rehash(row["password_hash"]):
            database.execute(
                "UPDATE usuarios SET password_hash = ? WHERE id = ?",
                (password_hash(password), row["id"]),
            )
            database.commit()
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = row["id"]
        return token, user_payload(database, row["id"])
    finally:
        database.close()


def current_user(token: str | None) -> dict:
    if not token or token not in SESSIONS:
        raise ApiError("Sesión no válida")
    database = connection()
    try:
        return user_payload(database, SESSIONS[token])
    finally:
        database.close()


def logout(token: str | None) -> None:
    if token:
        SESSIONS.pop(token, None)


def user_has_permission(user: dict, permission: str) -> bool:
    return permission in user["permissions"]


def list_users() -> list[dict]:
    database = connection()
    try:
        rows = database.execute(
            "SELECT usuarios.id, usuarios.nombre AS name, usuarios.usuario AS username, "
            "usuarios.activo AS active, roles.nombre AS role "
            "FROM usuarios JOIN roles ON roles.id = usuarios.rol_id ORDER BY usuarios.nombre"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        database.close()


def list_roles() -> list[dict]:
    database = connection()
    try:
        rows = database.execute("SELECT id, nombre AS name, permisos AS permissions FROM roles ORDER BY nombre").fetchall()
        return [{**dict(row), "permissions": json.loads(row["permissions"])} for row in rows]
    finally:
        database.close()


def create_user(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    role_id = int(payload.get("role_id", 0))
    if not name or not username or len(password) < 6 or not role_id:
        raise ApiError("Nombre, usuario, contraseña de 6 caracteres y rol son obligatorios")
    database = connection()
    try:
        cursor = database.execute(
            "INSERT INTO usuarios (nombre, usuario, password_hash, rol_id) VALUES (?, ?, ?, ?)",
            (name, username, password_hash(password), role_id),
        )
        database.commit()
        return {"id": cursor.lastrowid, "name": name, "username": username, "role_id": role_id, "active": 1}
    except DatabaseIntegrityError as error:
        raise ApiError("El nombre de usuario ya existe") from error
    finally:
        database.close()


def update_user(user_id: int, payload: dict) -> dict:
    database = connection()
    try:
        values = []
        assignments = []
        if "name" in payload:
            assignments.append("nombre = ?")
            values.append(str(payload["name"]).strip())
        if "role_id" in payload:
            assignments.append("rol_id = ?")
            values.append(int(payload["role_id"]))
        if "active" in payload:
            assignments.append("activo = ?")
            values.append(1 if payload["active"] else 0)
        if payload.get("password"):
            assignments.append("password_hash = ?")
            values.append(password_hash(str(payload["password"])))
        if not assignments:
            raise ApiError("No hay campos para actualizar")
        values.append(user_id)
        cursor = database.execute(f'UPDATE usuarios SET {", ".join(assignments)} WHERE id = ?', values)
        if cursor.rowcount == 0:
            raise ApiError("Usuario no encontrado")
        database.commit()
        return {"id": user_id, **payload}
    finally:
        database.close()


def delete_user(user_id: int, requester_id: int) -> None:
    if user_id == requester_id:
        raise ApiError("No puedes borrar tu propia cuenta activa")
    database = connection()
    try:
        user = database.execute(
            "SELECT usuario FROM usuarios WHERE id = ?",
            (user_id,),
        ).fetchone()
        if user is None:
            raise ApiError("Usuario no encontrado")
        if user["usuario"] == "admin":
            raise ApiError("La cuenta admin principal no se puede borrar")
        database.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        database.commit()
        SESSIONS_copy = [token for token, active_id in SESSIONS.items() if active_id == user_id]
        for token in SESSIONS_copy:
            SESSIONS.pop(token, None)
    finally:
        database.close()


def product_mapping(columns: list[str]) -> dict[str, str | None]:
    options = {
        "id": ("id", "product_id", "producto_id"),
        "code": ("code", "codigo", "sku", "barcode"),
        "name": ("name", "nombre", "product_name"),
        "cat": ("category", "categoria", "cat"),
        "cost": ("cost", "costo", "precio_compra", "purchase_price"),
        "price": ("price", "precio", "precio_venta", "sale_price"),
        "stock": ("stock", "existencia", "quantity", "cantidad"),
        "min": ("min", "minimum_stock", "stock_minimo", "min_stock"),
    }
    return {
        key: first_column(columns, names, required=key in ("id", "code", "name"))
        for key, names in options.items()
    }


def get_products() -> list[dict]:
    database = connection()
    try:
        table, columns = find_products_table(database)
        mapping = product_mapping(columns)
        product_id = mapping["id"]
        code = mapping["code"]
        name = mapping["name"]
        category = mapping["cat"]
        cost = mapping["cost"]
        price = mapping["price"]
        stock = mapping["stock"]
        minimum = mapping["min"]

        selected = [
            f'"{product_id}" AS id',
            f'"{code}" AS code',
            f'"{name}" AS name',
            f'"{category}" AS cat' if category else "'' AS cat",
            f'"{cost}" AS cost' if cost else "0 AS cost",
            f'"{price}" AS price' if price else "0 AS price",
            f'"{stock}" AS stock' if stock else "0 AS stock",
            f'"{minimum}" AS min' if minimum else "0 AS min",
        ]
        rows = database.execute(
            f'SELECT {", ".join(selected)} FROM "{table}" ORDER BY "{name}"'
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        database.close()


def create_products(payload: dict) -> list[dict]:
    products = payload.get("products", [])
    if not isinstance(products, list) or not products:
        raise ApiError("Se requiere una lista de productos")

    database = connection()
    try:
        table, columns = find_products_table(database)
        target_columns = product_mapping(columns)
        target_columns.pop("id")
        inserted = []
        for product in products:
            values = {
                column: product.get(key, 0 if key in ("cost", "price", "stock", "min") else "")
                for key, column in target_columns.items()
                if column
            }
            columns_sql = ", ".join(f'"{column}"' for column in values)
            placeholders = ", ".join("?" for _ in values)
            database.execute(
                f'INSERT INTO "{table}" ({columns_sql}) VALUES ({placeholders})',
                list(values.values()),
            )
            inserted.append(product)
        database.commit()
        return inserted
    finally:
        database.close()


def update_product(product_id: int, payload: dict) -> dict:
    database = connection()
    try:
        table, columns = find_products_table(database)
        mapping = product_mapping(columns)
        values = {
            mapping[key]: payload[key]
            for key in ("code", "name", "cat", "cost", "price", "stock", "min")
            if mapping[key] and key in payload
        }
        if not values:
            raise ApiError("No hay campos para actualizar")
        assignments = ", ".join(f'"{column}" = ?' for column in values)
        cursor = database.execute(
            f'UPDATE "{table}" SET {assignments} WHERE "{mapping["id"]}" = ?',
            [*values.values(), product_id],
        )
        if cursor.rowcount == 0:
            raise ApiError("Producto no encontrado")
        database.commit()
        return {"id": product_id, **payload}
    finally:
        database.close()


def delete_product(product_id: int) -> None:
    database = connection()
    try:
        table, columns = find_products_table(database)
        product_id_column = product_mapping(columns)["id"]
        cursor = database.execute(
            f'DELETE FROM "{table}" WHERE "{product_id_column}" = ?',
            (product_id,),
        )
        if cursor.rowcount == 0:
            raise ApiError("Producto no encontrado")
        database.commit()
    finally:
        database.close()


def get_suppliers() -> list[dict]:
    database = connection()
    try:
        rows = database.execute(
            "SELECT id, nombre AS name, contacto AS contact, telefono AS phone, email "
            "FROM proveedores ORDER BY nombre"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        database.close()


def create_supplier(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ApiError("El nombre del proveedor es obligatorio")
    contact = str(payload.get("contact", "")).strip()
    phone = str(payload.get("phone", "")).strip()
    email = str(payload.get("email", "")).strip()
    database = connection()
    try:
        cursor = database.execute(
            "INSERT INTO proveedores (nombre, contacto, telefono, email, creado) VALUES (?, ?, ?, ?, ?)",
            (name, contact, phone, email, datetime.now().isoformat(timespec="seconds")),
        )
        database.commit()
        return {"id": cursor.lastrowid, "name": name, "contact": contact, "phone": phone, "email": email}
    finally:
        database.close()


def get_purchases() -> list[dict]:
    database = connection()
    try:
        purchases = database.execute(
            "SELECT compras.id, compras.proveedor_id AS supplier_id, compras.fecha, compras.total, compras.notas, "
            "proveedores.nombre AS supplier_name, usuarios.nombre AS user_name "
            "FROM compras JOIN proveedores ON proveedores.id = compras.proveedor_id "
            "LEFT JOIN usuarios ON usuarios.id = compras.usuario_id ORDER BY compras.id DESC"
        ).fetchall()
        result = []
        for purchase in purchases:
            item = dict(purchase)
            item["items"] = [dict(row) for row in database.execute(
                "SELECT codigo AS code, producto AS name, cantidad AS quantity, "
                "costo_unitario AS unit_cost, subtotal FROM detalle_compras WHERE compra_id = ? ORDER BY id",
                (purchase["id"],),
            ).fetchall()]
            result.append(item)
        return result
    finally:
        database.close()


def create_purchase(payload: dict, user_id: int | None = None) -> dict:
    try:
        supplier_id = int(payload.get("supplier_id", 0))
    except (TypeError, ValueError) as error:
        raise ApiError("Selecciona un proveedor válido") from error
    items = payload.get("items")
    if not supplier_id or not isinstance(items, list) or not items:
        raise ApiError("Selecciona un proveedor y agrega al menos un producto")

    database = connection()
    try:
        supplier = database.execute("SELECT id FROM proveedores WHERE id = ?", (supplier_id,)).fetchone()
        if supplier is None:
            raise ApiError("Proveedor no encontrado")
        products_table, product_columns = find_products_table(database)
        mapping = product_mapping(product_columns)
        if not mapping["stock"]:
            raise ApiError("La tabla de productos no tiene una columna de existencias")

        lines = []
        total = 0.0
        seen_codes = set()
        for item in items:
            if not isinstance(item, dict):
                raise ApiError("Hay una línea de compra inválida")
            code = str(item.get("product_code", "")).strip()
            try:
                quantity = int(item.get("quantity", 0))
                unit_cost = float(item.get("unit_cost", 0))
            except (TypeError, ValueError) as error:
                raise ApiError("Cantidad o costo inválido") from error
            if not code or code in seen_codes or quantity <= 0 or not math.isfinite(unit_cost) or unit_cost < 0:
                raise ApiError("Cada producto necesita código, cantidad positiva y costo no negativo")
            seen_codes.add(code)
            selected = [
                f'"{mapping["id"]}" AS id', f'"{mapping["code"]}" AS code',
                f'"{mapping["name"]}" AS name', f'"{mapping["stock"]}" AS stock',
            ]
            product = database.execute(
                f'SELECT {", ".join(selected)} FROM "{products_table}" WHERE "{mapping["code"]}" = ?',
                (code,),
            ).fetchone()
            new_product = None
            if product is None:
                new_product_payload = item.get("new_product")
                if not isinstance(new_product_payload, dict):
                    raise ApiError(f"Producto no encontrado: {code}. Agrégalo como producto nuevo para continuar")
                if not mapping["price"]:
                    raise ApiError("La tabla de productos no tiene una columna de precio de venta")
                product_name = str(new_product_payload.get("name", "")).strip()
                category = str(new_product_payload.get("category", "")).strip()
                try:
                    sale_price = float(new_product_payload.get("price", 0))
                except (TypeError, ValueError) as error:
                    raise ApiError("El precio de venta del producto nuevo no es válido") from error
                if not product_name or not math.isfinite(sale_price) or sale_price < 0:
                    raise ApiError("El producto nuevo necesita nombre y precio de venta válido")
                new_product = {"name": product_name, "category": category, "price": sale_price}
            subtotal = quantity * unit_cost
            total += subtotal
            lines.append({"code": code, "product": product, "new_product": new_product, "quantity": quantity, "unit_cost": unit_cost, "subtotal": subtotal})

        database.execute("BEGIN")
        purchase = database.execute(
            "INSERT INTO compras (proveedor_id, fecha, total, notas, usuario_id) VALUES (?, ?, ?, ?, ?)",
            (supplier_id, datetime.now().isoformat(timespec="seconds"), total, str(payload.get("notes", "")).strip(), user_id),
        )
        for line in lines:
            product = line["product"]
            if product is None:
                new_product = line["new_product"]
                product_values = {
                    mapping["code"]: line["code"],
                    mapping["name"]: new_product["name"],
                    mapping["stock"]: 0,
                }
                if mapping["cat"]:
                    product_values[mapping["cat"]] = new_product["category"]
                if mapping["cost"]:
                    product_values[mapping["cost"]] = line["unit_cost"]
                if mapping["price"]:
                    product_values[mapping["price"]] = new_product["price"]
                product_columns_sql = ", ".join(f'"{column}"' for column in product_values)
                placeholders = ", ".join("?" for _ in product_values)
                cursor = database.execute(
                    f'INSERT INTO "{products_table}" ({product_columns_sql}) VALUES ({placeholders})',
                    list(product_values.values()),
                )
                product = {"id": cursor.lastrowid, "code": line["code"], "name": new_product["name"]}
                line["product"] = product
            database.execute(
                "INSERT INTO detalle_compras (compra_id, producto_id, codigo, producto, cantidad, costo_unitario, subtotal) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (purchase.lastrowid, product["id"], product["code"], product["name"], line["quantity"], line["unit_cost"], line["subtotal"]),
            )
            assignments = f'"{mapping["stock"]}" = "{mapping["stock"]}" + ?'
            values = [line["quantity"]]
            if mapping["cost"]:
                assignments += f', "{mapping["cost"]}" = ?'
                values.append(line["unit_cost"])
            database.execute(
                f'UPDATE "{products_table}" SET {assignments} WHERE "{mapping["id"]}" = ?',
                [*values, product["id"]],
            )
        database.commit()
        return {"id": purchase.lastrowid, "total": total, "supplier_id": supplier_id}
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def find_clients_table(database: PostgresConnection) -> tuple[str, list[str]]:
    candidates = ("clients", "clientes", "client")
    available = tables(database)
    table = next((name for name in candidates if name in available), None)
    if table is None:
        raise ApiError(f"No se encontró una tabla de clientes. Tablas: {available}")
    columns = [row["name"] for row in database.execute(f'PRAGMA table_info("{table}")')]
    return table, columns


def client_mapping(columns: list[str]) -> dict[str, str | None]:
    options = {
        "id": ("id", "client_id", "cliente_id"),
        "name": ("name", "nombre", "client_name"),
        "phone": ("phone", "telefono", "teléfono"),
        "balance": ("balance", "saldo", "saldo_deudor", "debt"),
    }
    return {
        key: first_column(columns, names, required=key in ("id", "name"))
        for key, names in options.items()
    }


def get_clients() -> list[dict]:
    database = connection()
    try:
        table, columns = find_clients_table(database)
        mapping = client_mapping(columns)
        selected = [
            f'"{mapping["id"]}" AS id',
            f'"{mapping["name"]}" AS name',
            f'"{mapping["phone"]}" AS phone' if mapping["phone"] else "'' AS phone",
            f'"{mapping["balance"]}" AS balance' if mapping["balance"] else "0 AS balance",
        ]
        rows = database.execute(
            f'SELECT {", ".join(selected)} FROM "{table}" ORDER BY "{mapping["name"]}"'
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        database.close()


def create_client(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ApiError("El nombre del cliente es obligatorio")
    database = connection()
    try:
        table, columns = find_clients_table(database)
        mapping = client_mapping(columns)
        values = {mapping["name"]: name}
        if mapping["phone"]:
            values[mapping["phone"]] = str(payload.get("phone", "")).strip()
        if mapping["balance"]:
            values[mapping["balance"]] = float(payload.get("balance", 0) or 0)
        columns_sql = ", ".join(f'"{column}"' for column in values)
        placeholders = ", ".join("?" for _ in values)
        cursor = database.execute(
            f'INSERT INTO "{table}" ({columns_sql}) VALUES ({placeholders})',
            list(values.values()),
        )
        database.commit()
        return {"id": cursor.lastrowid, "name": name, "phone": values.get(mapping["phone"], ""), "balance": values.get(mapping["balance"], 0)}
    finally:
        database.close()


def update_client(client_id: int, payload: dict) -> dict:
    database = connection()
    try:
        table, columns = find_clients_table(database)
        mapping = client_mapping(columns)
        values = {}
        if "name" in payload and mapping["name"]:
            values[mapping["name"]] = str(payload["name"]).strip()
        if "phone" in payload and mapping["phone"]:
            values[mapping["phone"]] = str(payload["phone"]).strip()
        if not values:
            raise ApiError("No hay campos para actualizar")
        assignments = ", ".join(f'"{column}" = ?' for column in values)
        cursor = database.execute(
            f'UPDATE "{table}" SET {assignments} WHERE "{mapping["id"]}" = ?',
            [*values.values(), client_id],
        )
        if cursor.rowcount == 0:
            raise ApiError("Cliente no encontrado")
        database.commit()
        return {"id": client_id, **payload}
    finally:
        database.close()


def delete_client(client_id: int) -> None:
    database = connection()
    try:
        table, columns = find_clients_table(database)
        mapping = client_mapping(columns)
        cursor = database.execute(
            f'DELETE FROM "{table}" WHERE "{mapping["id"]}" = ?',
            (client_id,),
        )
        if cursor.rowcount == 0:
            raise ApiError("Cliente no encontrado")
        database.commit()
    finally:
        database.close()


def register_payment(client_id: int, amount: float) -> dict:
    if amount <= 0:
        raise ApiError("El abono debe ser mayor que cero")
    database = connection()
    try:
        table, columns = find_clients_table(database)
        mapping = client_mapping(columns)
        if not mapping["balance"]:
            raise ApiError("La tabla de clientes no tiene saldo")
        cursor = database.execute(
            f'UPDATE "{table}" SET "{mapping["balance"]}" = MAX(0, "{mapping["balance"]}" - ?) WHERE "{mapping["id"]}" = ?',
            (amount, client_id),
        )
        if cursor.rowcount == 0:
            raise ApiError("Cliente no encontrado")
        database.commit()
        return {"client_id": client_id, "amount": amount}
    finally:
        database.close()


def get_sales() -> list[dict]:
    database = connection()
    try:
        sales = database.execute(
            "SELECT ventas.id, ventas.fecha, ventas.total, ventas.subtotal, ventas.iva, ventas.tasa_iva, ventas.metodo_pago, "
            "clientes.nombre AS client_name "
            "FROM ventas LEFT JOIN clientes ON clientes.id = ventas.cliente_id "
            "ORDER BY ventas.id DESC"
        ).fetchall()
        return [
            {
                "id": row["id"],
                "f": str(row["id"]).zfill(4),
                "h": row["fecha"].replace("T", " ")[:16],
                "c": row["client_name"] or "Mostrador",
                "t": row["total"],
                "subtotal": row["subtotal"] if "subtotal" in row.keys() else None,
                "iva": row["iva"] if "iva" in row.keys() else None,
                "vat_rate": row["tasa_iva"] if "tasa_iva" in row.keys() else 16,
                "m": row["metodo_pago"],
            }
            for row in sales
        ]
    finally:
        database.close()


def create_sale(payload: dict, user_id: int | None = None) -> dict:
    items = payload.get("items", [])
    if not isinstance(items, list) or not items:
        raise ApiError("La venta necesita al menos un producto")

    database = connection()
    try:
        products_table, product_columns = find_products_table(database)
        products = product_mapping(product_columns)
        client_id = payload.get("client_id")
        payment_method = str(payload.get("payment_method", "Efectivo"))
        lines = []
        total = 0.0

        for item in items:
            code = str(item.get("product_code", "")).strip()
            quantity = int(item.get("quantity", 0))
            if not code or quantity <= 0:
                raise ApiError("Producto o cantidad inválida")
            row = database.execute(
                f'SELECT "{products["id"]}" AS id, "{products["name"]}" AS name, '
                f'"{products["price"]}" AS price, "{products["stock"]}" AS stock '
                f'FROM "{products_table}" WHERE "{products["code"]}" = ?',
                (code,),
            ).fetchone()
            if row is None:
                raise ApiError(f"Producto no encontrado: {code}")
            if row["stock"] < quantity:
                raise ApiError(f"Stock insuficiente para {row["name"]}")
            subtotal = float(row["price"]) * quantity
            total += subtotal
            lines.append({"product_id": row["id"], "quantity": quantity, "price": row["price"], "subtotal": subtotal})

        discount = float(payload.get("discount", 0) or 0)
        total = max(0, total - total * discount / 100)
        vat_rate = float(get_settings().get("vat_rate", "16") or 16)
        subtotal = total / (1 + vat_rate / 100) if vat_rate > 0 else total
        iva = total - subtotal
        if payment_method == "Crédito":
            if not client_id:
                raise ApiError("Selecciona un cliente para vender a crédito")
            clients_table, client_columns = find_clients_table(database)
            client_map = client_mapping(client_columns)
            if not client_map["balance"]:
                raise ApiError("La tabla de clientes no tiene saldo")

        database.execute("BEGIN")
        sale = database.execute(
            "INSERT INTO ventas (fecha, total, subtotal, iva, tasa_iva, metodo_pago, cliente_id, usuario_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), total, subtotal, iva, vat_rate, payment_method, client_id, user_id),
        )
        for line in lines:
            database.execute(
                "INSERT INTO detalle_ventas (venta_id, producto_id, cantidad, precio_unitario, subtotal) "
                "VALUES (?, ?, ?, ?, ?)",
                (sale.lastrowid, line["product_id"], line["quantity"], line["price"], line["subtotal"]),
            )
            database.execute(
                f'UPDATE "{products_table}" SET "{products["stock"]}" = "{products["stock"]}" - ? '
                f'WHERE "{products["id"]}" = ?',
                (line["quantity"], line["product_id"]),
            )
        if payment_method == "Crédito":
            database.execute(
                f'UPDATE "{clients_table}" SET "{client_map["balance"]}" = "{client_map["balance"]}" + ? '
                f'WHERE "{client_map["id"]}" = ?',
                (total, client_id),
            )
        database.commit()
        return {"id": sale.lastrowid, "total": total, "subtotal": subtotal, "iva": iva, "vat_rate": vat_rate, "payment_method": payment_method}
    except Exception:
        database.rollback()
        raise
    finally:
        database.close()


def current_cash_register() -> dict | None:
    database = connection()
    try:
        row = database.execute(
            "SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        movements = database.execute(
            "SELECT * FROM movimientos_caja WHERE caja_id = ? ORDER BY id DESC",
            (row["id"],),
        ).fetchall()
        return {"register": dict(row), "movements": [dict(item) for item in movements]}
    finally:
        database.close()


def open_cash_register(initial_amount: float, user_id: int | None = None) -> dict:
    if initial_amount < 0:
        raise ApiError("El fondo inicial no puede ser negativo")
    database = connection()
    try:
        existing = database.execute(
            "SELECT id FROM cajas WHERE estado = 'abierta' LIMIT 1"
        ).fetchone()
        if existing:
            raise ApiError("Ya existe una caja abierta")
        cursor = database.execute(
            "INSERT INTO cajas (fecha_apertura, fondo_inicial, usuario_id) VALUES (?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), initial_amount, user_id),
        )
        database.commit()
        return {"id": cursor.lastrowid, "fondo_inicial": initial_amount, "estado": "abierta"}
    finally:
        database.close()


def add_cash_movement(payload: dict, user_id: int | None = None) -> dict:
    movement_type = payload.get("type")
    amount = float(payload.get("amount", 0) or 0)
    if movement_type not in ("entrada", "retiro") or amount <= 0:
        raise ApiError("Movimiento inválido")
    database = connection()
    try:
        register = database.execute(
            "SELECT id FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not register:
            raise ApiError("No hay una caja abierta")
        cursor = database.execute(
            "INSERT INTO movimientos_caja (caja_id, tipo, monto, concepto, fecha, usuario_id) VALUES (?, ?, ?, ?, ?, ?)",
            (register["id"], movement_type, amount, str(payload.get("concept", "")).strip(), datetime.now().isoformat(timespec="seconds"), user_id),
        )
        database.commit()
        return {"id": cursor.lastrowid, "type": movement_type, "amount": amount}
    finally:
        database.close()


def close_cash_register(final_amount: float, user_id: int | None = None) -> dict:
    if final_amount < 0:
        raise ApiError("El efectivo contado no puede ser negativo")
    database = connection()
    try:
        register = database.execute(
            "SELECT * FROM cajas WHERE estado = 'abierta' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not register:
            raise ApiError("No hay una caja abierta")
        movements = database.execute(
            "SELECT tipo, monto FROM movimientos_caja WHERE caja_id = ?",
            (register["id"],),
        ).fetchall()
        expected = register["fondo_inicial"]
        expected += sum(item["monto"] for item in movements if item["tipo"] == "entrada")
        expected -= sum(item["monto"] for item in movements if item["tipo"] == "retiro")
        database.execute(
            "UPDATE cajas SET fecha_cierre = ?, efectivo_final = ?, estado = 'cerrada' WHERE id = ?",
            (datetime.now().isoformat(timespec="seconds"), final_amount, register["id"]),
        )
        database.commit()
        return {"expected": expected, "counted": final_amount, "difference": final_amount - expected}
    finally:
        database.close()


def cash_history(date_filter: str | None = None) -> list[dict]:
    database = connection()
    try:
        query = (
            "SELECT cajas.*, usuarios.nombre AS user_name FROM cajas "
            "LEFT JOIN usuarios ON usuarios.id = cajas.usuario_id"
        )
        params: tuple = ()
        if date_filter:
            query += " WHERE date(cajas.fecha_apertura) = date(?) OR date(cajas.fecha_cierre) = date(?)"
            params = (date_filter, date_filter)
        rows = database.execute(query + " ORDER BY cajas.id DESC", params).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            movements = database.execute(
                "SELECT movimientos_caja.*, usuarios.nombre AS user_name FROM movimientos_caja "
                "LEFT JOIN usuarios ON usuarios.id = movimientos_caja.usuario_id "
                "WHERE caja_id = ? ORDER BY id",
                (row["id"],),
            ).fetchall()
            item["movements"] = [dict(movement) for movement in movements]
            result.append(item)
        return result
    finally:
        database.close()


def report_data(period: str, anchor: str | None = None) -> dict:
    today = datetime.now().date()
    try:
        selected = datetime.strptime(anchor, "%Y-%m-%d").date() if anchor else today
    except ValueError as error:
        raise ApiError("Fecha inválida") from error
    if period == "day":
        start = end = today
    elif period == "week":
        start = selected.fromordinal(selected.toordinal() - selected.weekday())
        end = start + timedelta(days=6)
    elif period == "month":
        start = selected.replace(day=1)
        end = selected.replace(day=28) + timedelta(days=4)
        end = end.replace(day=1) - timedelta(days=1)
    elif period == "year":
        start = selected.replace(month=1, day=1)
        end = selected.replace(month=12, day=31)
    else:
        raise ApiError("Periodo inválido")
    database = connection()
    try:
        where = "date(fecha) BETWEEN date(?) AND date(?)"
        date_params = (start.isoformat(), end.isoformat())
        summary = database.execute(
            f"SELECT COUNT(*) AS count, COALESCE(SUM(total), 0) AS total FROM ventas WHERE {where}", date_params
        ).fetchone()
        methods = database.execute(
            f"SELECT metodo_pago AS method, COALESCE(SUM(total), 0) AS total FROM ventas WHERE {where} GROUP BY metodo_pago", date_params
        ).fetchall()
        users = database.execute(
            f"SELECT COALESCE(usuarios.nombre, 'Sin usuario') AS user_name, COUNT(*) AS count, COALESCE(SUM(total), 0) AS total "
            f"FROM ventas LEFT JOIN usuarios ON usuarios.id = ventas.usuario_id WHERE {where} GROUP BY ventas.usuario_id", date_params
        ).fetchall()
        return {"period": period, "start": start.isoformat(), "end": end.isoformat(), "count": summary["count"], "total": summary["total"], "methods": [dict(row) for row in methods], "users": [dict(row) for row in users]}
    finally:
        database.close()


def get_settings() -> dict[str, str]:
    database = connection()
    try:
        return {row["clave"]: row["valor"] for row in database.execute("SELECT clave, valor FROM ajustes ORDER BY clave")}
    finally:
        database.close()


def validate_business_logo(value: str) -> str:
    if not value:
        return ""
    if len(value) > (MAX_BUSINESS_LOGO_BYTES * 4 // 3) + 128:
        raise ApiError("La imagen del logo no puede superar 512 KB")
    prefix, separator, encoded = value.partition(",")
    mime = prefix.removeprefix("data:image/").removesuffix(";base64")
    if separator != "," or mime not in {"png", "jpeg", "webp"}:
        raise ApiError("El logo debe ser una imagen PNG, JPG o WebP")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ApiError("La imagen del logo no es válida") from error
    if len(image) > MAX_BUSINESS_LOGO_BYTES:
        raise ApiError("La imagen del logo no puede superar 512 KB")
    valid_signature = {
        "png": image.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpeg": image.startswith(b"\xff\xd8\xff"),
        "webp": image.startswith(b"RIFF") and image[8:12] == b"WEBP",
    }
    if not valid_signature[mime]:
        raise ApiError("El contenido no coincide con el formato de imagen declarado")
    return value


def update_settings(payload: dict) -> dict[str, str]:
    database = connection()
    try:
        for key, value in payload.items():
            if key not in {row["clave"] for row in database.execute("SELECT clave FROM ajustes") }:
                raise ApiError(f"Ajuste no permitido: {key}")
            value = str(value).strip()
            if key == "business_icon" and value not in BUSINESS_ICON_CHOICES:
                raise ApiError("El icono seleccionado no es válido")
            if key == "business_logo":
                value = validate_business_logo(value)
            database.execute("UPDATE ajustes SET valor = ? WHERE clave = ?", (value, key))
        database.commit()
        return get_settings()
    finally:
        database.close()


def get_ticket_templates() -> list[dict]:
    database = connection()
    try:
        rows = database.execute(
            "SELECT id, nombre AS name, diseno AS design, predeterminada AS default_template, actualizada AS updated_at "
            "FROM ticket_templates ORDER BY predeterminada DESC, nombre"
        ).fetchall()
        return [{**dict(row), "design": json.loads(row["design"])} for row in rows]
    finally:
        database.close()


def save_ticket_template(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    design = payload.get("design")
    if not name or not isinstance(design, list):
        raise ApiError("Nombre y diseño de ticket son obligatorios")
    database = connection()
    try:
        template_id = payload.get("id")
        if template_id:
            database.execute(
                "UPDATE ticket_templates SET nombre = ?, diseno = ?, actualizada = ? WHERE id = ?",
                (name, json.dumps(design, ensure_ascii=False), datetime.now().isoformat(timespec="seconds"), int(template_id)),
            )
        else:
            cursor = database.execute(
                "INSERT INTO ticket_templates (nombre, diseno, predeterminada, actualizada) VALUES (?, ?, 0, ?)",
                (name, json.dumps(design, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")),
            )
            template_id = cursor.lastrowid
        database.commit()
        return {"id": template_id, "name": name, "design": design}
    except DatabaseIntegrityError as error:
        raise ApiError("Ya existe una plantilla con ese nombre") from error
    finally:
        database.close()


def delete_ticket_template(template_id: int) -> None:
    database = connection()
    try:
        row = database.execute("SELECT predeterminada FROM ticket_templates WHERE id = ?", (template_id,)).fetchone()
        if not row:
            raise ApiError("Plantilla no encontrada")
        if row["predeterminada"]:
            raise ApiError("La plantilla predeterminada no se puede borrar")
        database.execute("DELETE FROM ticket_templates WHERE id = ?", (template_id,))
        database.commit()
    finally:
        database.close()


def get_invoices() -> list[dict]:
    database = connection()
    try:
        rows = database.execute(
            "SELECT facturas.*, ventas.total, clientes.nombre AS client_name "
            "FROM facturas JOIN ventas ON ventas.id = facturas.venta_id "
            "LEFT JOIN clientes ON clientes.id = facturas.cliente_id ORDER BY facturas.id DESC"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        database.close()


def create_invoice(payload: dict) -> dict:
    sale_id = int(payload.get("sale_id", 0))
    rfc = str(payload.get("rfc", "")).strip().upper()
    company = str(payload.get("razon_social", "")).strip()
    if not sale_id or not rfc or not company:
        raise ApiError("Venta, RFC y razón social son obligatorios")
    database = connection()
    try:
        sale = database.execute("SELECT id FROM ventas WHERE id = ?", (sale_id,)).fetchone()
        if not sale:
            raise ApiError("Venta no encontrada")
        duplicate = database.execute("SELECT id FROM facturas WHERE venta_id = ?", (sale_id,)).fetchone()
        if duplicate:
            raise ApiError("Esta venta ya tiene factura")
        folio = database.execute("SELECT COALESCE(MAX(folio), 0) + 1 FROM facturas").fetchone()[0]
        cursor = database.execute(
            "INSERT INTO facturas (venta_id, cliente_id, rfc, razon_social, uso_cfdi, serie, folio, fecha) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sale_id, payload.get("client_id"), rfc, company, payload.get("uso_cfdi", "G03"), payload.get("serie", "A"), folio, datetime.now().isoformat(timespec="seconds")),
        )
        database.commit()
        return {"id": cursor.lastrowid, "venta_id": sale_id, "folio": folio, "estado": "pendiente"}
    finally:
        database.close()


class Handler(SimpleHTTPRequestHandler):
    def _same_local_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed_origin = urlparse(origin)
        host = self.headers.get("Host", "")
        return (
            parsed_origin.scheme == "http"
            and parsed_origin.netloc.lower() == host.lower()
            and parsed_origin.hostname in {"127.0.0.1", "localhost"}
        )

    def _reject_legacy_desktop_api(self, path: str) -> bool:
        if (
            os.getenv("OZZVON_DESKTOP_REMOTE") != "1"
            or not path.startswith("/api/")
        ):
            return False
        self.send_json(
            {"error": "El POS de escritorio utiliza el servicio seguro de Ozzvon."},
            HTTPStatus.NOT_FOUND,
        )
        return True

    def _proxy_cloud_api(self) -> None:
        parsed_path = urlparse(self.path)
        if not self._same_local_origin():
            self.send_json({"error": "Origen no autorizado."}, HTTPStatus.FORBIDDEN)
            return
        upstream_path = parsed_path.path.removeprefix("/cloud")
        if not cloud_proxy_path_allowed(self.command, upstream_path):
            self.send_json({"error": "Endpoint no disponible."}, HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json({"error": "Longitud de solicitud no válida."}, HTTPStatus.BAD_REQUEST)
            return
        if content_length < 0 or content_length > CLOUD_PROXY_MAX_BODY:
            self.send_json(
                {"error": "La solicitud excede el tamaño permitido."},
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )
            return
        self.connection.settimeout(10)
        body = self.rfile.read(content_length) if content_length else None
        headers = {"Accept": "application/json"}
        content_type = self.headers.get("Content-Type")
        if content_type:
            headers["Content-Type"] = content_type
        authorization = self.headers.get("Authorization", "")
        if authorization.startswith("Bearer ") and len(authorization) <= 4096:
            headers["Authorization"] = authorization

        upstream = None
        try:
            target_url = cloud_api_url(upstream_path, parsed_path.query)
            request = Request(
                target_url,
                data=body,
                headers=headers,
                method=self.command,
            )
            opener = build_opener(NoRedirectHandler())
            try:
                upstream = opener.open(request, timeout=20)
            except HTTPError as error:
                upstream = error
            response_body = upstream.read(CLOUD_PROXY_MAX_BODY + 1)
            if len(response_body) > CLOUD_PROXY_MAX_BODY:
                self.send_json(
                    {"error": "La respuesta del servicio excede el tamaño permitido."},
                    HTTPStatus.BAD_GATEWAY,
                )
                return
            self.send_response(upstream.code)
            self.send_header(
                "Content-Type",
                upstream.headers.get("Content-Type", "application/json; charset=utf-8"),
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(response_body)))
            self.end_cors()
            self.end_headers()
            if response_body:
                self.wfile.write(response_body)
        except (
            HTTPException,
            URLError,
            TimeoutError,
            OSError,
            RuntimeError,
            ValueError,
        ) as error:
            self.log_error("Ozzvon API proxy failed (%s)", type(error).__name__)
            status = (
                HTTPStatus.GATEWAY_TIMEOUT
                if isinstance(error, TimeoutError)
                else HTTPStatus.BAD_GATEWAY
            )
            self.send_json(
                {
                    "error": (
                        "No se pudo conectar con el servidor de Ozzvon. "
                        "Revisa tu conexión a Internet e inténtalo de nuevo."
                    )
                },
                status,
            )
        finally:
            if upstream is not None:
                upstream.close()

    def token(self) -> str | None:
        return self.headers.get("Authorization", "").removeprefix("Bearer ").strip() or None

    def session_user(self, permission: str | None = None) -> dict:
        user = current_user(self.token())
        if permission and not user_has_permission(user, permission):
            raise ApiError("No tienes permiso para esta acción")
        return user

    def stream_events(self, token: str | None) -> None:
        current_user(token)
        stream: queue.Queue = queue.Queue(maxsize=50)
        EVENT_STREAMS.append(stream)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_cors()
        self.end_headers()
        self.wfile.write(b": connected\n\n")
        self.wfile.flush()
        try:
            while True:
                payload = stream.get()
                self.wfile.write(f"event: data.changed\ndata: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            if stream in EVENT_STREAMS:
                EVENT_STREAMS.remove(stream)

    def json_payload(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        payload = json.loads(text or "{}")
        if not isinstance(payload, dict):
            raise ApiError("El cuerpo debe ser un objeto JSON")
        return payload

    def end_cors(self) -> None:
        if self._same_local_origin() and self.headers.get("Origin"):
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Vary", "Origin")
            self.send_header(
                "Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS"
            )
            self.send_header(
                "Access-Control-Allow-Headers", "Content-Type, Authorization"
            )

    def do_OPTIONS(self) -> None:
        if not self._same_local_origin():
            self.send_response(HTTPStatus.FORBIDDEN)
            self.end_headers()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.end_cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/cloud/"):
            self._proxy_cloud_api()
            return
        if self._reject_legacy_desktop_api(path):
            return
        try:
            if path == "/api/products":
                self.session_user("inventory.view")
                self.send_json(get_products())
                return
            if path == "/api/clients":
                self.session_user("clients.view")
                self.send_json(get_clients())
                return
            if path == "/api/sales":
                self.session_user("sales.create")
                self.send_json(get_sales())
                return
            if path == "/api/suppliers":
                self.session_user("inventory.view")
                self.send_json(get_suppliers())
                return
            if path == "/api/purchases":
                self.session_user("inventory.view")
                self.send_json(get_purchases())
                return
            if path == "/api/cash/current":
                self.session_user("cash.view")
                self.send_json(current_cash_register())
                return
            if path == "/api/cash/history":
                self.session_user("cash.view")
                query = parse_qs(urlparse(self.path).query)
                self.send_json(cash_history(query.get("date", [None])[0]))
                return
            if path == "/api/reports":
                self.session_user("reports.view")
                query = parse_qs(urlparse(self.path).query)
                self.send_json(report_data(query.get("period", ["month"])[0], query.get("date", [None])[0]))
                return
            if path == "/api/settings":
                self.session_user("settings.manage")
                self.send_json(get_settings())
                return
            if path == "/api/tax-rate":
                self.session_user("sales.create")
                self.send_json({"vat_rate": float(get_settings().get("vat_rate", "16") or 16)})
                return
            if path == "/api/ticket-templates":
                self.session_user("settings.manage")
                self.send_json(get_ticket_templates())
                return
            if path == "/api/invoices":
                self.session_user("billing.view")
                self.send_json(get_invoices())
                return
            if path == "/api/users":
                self.session_user("users.manage")
                self.send_json(list_users())
                return
            if path == "/api/roles":
                self.session_user("users.manage")
                self.send_json(list_roles())
                return
            if path == "/api/business-name":
                self.session_user("dashboard.view")
                settings = get_settings()
                self.send_json({key: settings.get(key, "") for key in ("business_name", "business_icon", "business_logo")})
                return
            if path == "/api/events":
                query = parse_qs(urlparse(self.path).query)
                self.stream_events(query.get("token", [None])[0])
                return
            self.path = "/index.html" if path == "/" else path
            super().do_GET()
        except ApiError as error:
            self.send_json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        except DatabaseError as error:
            self.send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/cloud/"):
            self._proxy_cloud_api()
            return
        if self._reject_legacy_desktop_api(path):
            return
        try:
            payload = self.json_payload()
            if path == "/api/products/bulk":
                self.session_user("inventory.manage")
                self.send_json(create_products(payload), HTTPStatus.CREATED)
                publish_event("products", "created")
                return
            if path == "/api/login":
                token, user = authenticate(payload)
                self.send_json({"token": token, "user": user})
                return
            if path == "/api/logout":
                logout(self.token())
                self.send_json(None, HTTPStatus.NO_CONTENT)
                return
            if path == "/api/users":
                self.session_user("users.manage")
                self.send_json(create_user(payload), HTTPStatus.CREATED)
                publish_event("users", "created")
                return
            if path == "/api/clients":
                self.session_user("clients.manage")
                self.send_json(create_client(payload), HTTPStatus.CREATED)
                publish_event("clients", "created")
                return
            if path == "/api/suppliers":
                self.session_user("inventory.manage")
                self.send_json(create_supplier(payload), HTTPStatus.CREATED)
                publish_event("suppliers", "created")
                return
            if path == "/api/purchases":
                user = self.session_user("inventory.manage")
                self.send_json(create_purchase(payload, user["id"]), HTTPStatus.CREATED)
                publish_event("purchases", "created")
                publish_event("products", "updated")
                return
            if path == "/api/payments":
                self.session_user("clients.manage")
                self.send_json(
                    register_payment(int(payload["client_id"]), float(payload["amount"])),
                    HTTPStatus.CREATED,
                )
                publish_event("clients", "payment")
                return
            if path == "/api/sales":
                user = self.session_user("sales.create")
                self.send_json(create_sale(payload, user["id"]), HTTPStatus.CREATED)
                publish_event("sales", "created")
                return
            if path == "/api/cash/open":
                user = self.session_user("cash.manage")
                self.send_json(open_cash_register(float(payload.get("initial_amount", 0)), user["id"]), HTTPStatus.CREATED)
                publish_event("cash", "opened")
                return
            if path == "/api/cash/movement":
                user = self.session_user("cash.manage")
                self.send_json(add_cash_movement(payload, user["id"]), HTTPStatus.CREATED)
                publish_event("cash", "movement")
                return
            if path == "/api/cash/close":
                user = self.session_user("cash.manage")
                self.send_json(close_cash_register(float(payload.get("final_amount", 0)), user["id"]))
                publish_event("cash", "closed")
                return
            if path == "/api/settings":
                self.session_user("settings.manage")
                self.send_json(update_settings(payload))
                publish_event("settings", "updated")
                return
            if path == "/api/ticket-templates":
                self.session_user("settings.manage")
                self.send_json(save_ticket_template(payload), HTTPStatus.CREATED)
                publish_event("ticket_templates", "saved")
                return
            if path == "/api/invoices":
                self.session_user("billing.view")
                self.send_json(create_invoice(payload), HTTPStatus.CREATED)
                publish_event("invoices", "created")
                return
            self.send_json({"error": "Endpoint no disponible"}, HTTPStatus.NOT_FOUND)
        except ApiError as error:
            self.send_json({"error": str(error)}, HTTPStatus.FORBIDDEN)
        except (UnicodeDecodeError, json.JSONDecodeError, DatabaseError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/cloud/"):
            self._proxy_cloud_api()
            return
        if self._reject_legacy_desktop_api(path):
            return
        try:
            payload = self.json_payload()
            if path.startswith("/api/products/"):
                self.session_user("inventory.manage")
                product_id = int(path.rsplit("/", 1)[-1])
                self.send_json(update_product(product_id, payload))
                publish_event("products", "updated")
                return
            if path.startswith("/api/clients/"):
                self.session_user("clients.manage")
                client_id = int(path.rsplit("/", 1)[-1])
                self.send_json(update_client(client_id, payload))
                publish_event("clients", "updated")
                return
            if path.startswith("/api/users/"):
                self.session_user("users.manage")
                user_id = int(path.rsplit("/", 1)[-1])
                self.send_json(update_user(user_id, payload))
                publish_event("users", "updated")
                return
            if path.startswith("/api/ticket-templates/"):
                self.session_user("settings.manage")
                template_id = int(path.rsplit("/", 1)[-1])
                payload["id"] = template_id
                self.send_json(save_ticket_template(payload))
                publish_event("ticket_templates", "updated")
                return
            self.send_json({"error": "Endpoint no disponible"}, HTTPStatus.NOT_FOUND)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError, DatabaseError, ApiError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/cloud/"):
            self._proxy_cloud_api()
            return
        if self._reject_legacy_desktop_api(path):
            return
        try:
            if path.startswith("/api/products/"):
                self.session_user("inventory.manage")
                delete_product(int(path.rsplit("/", 1)[-1]))
                self.send_json(None, HTTPStatus.NO_CONTENT)
                publish_event("products", "deleted")
                return
            if path.startswith("/api/clients/"):
                self.session_user("clients.manage")
                delete_client(int(path.rsplit("/", 1)[-1]))
                self.send_json(None, HTTPStatus.NO_CONTENT)
                publish_event("clients", "deleted")
                return
            if path.startswith("/api/users/"):
                user = self.session_user("users.manage")
                delete_user(int(path.rsplit("/", 1)[-1]), user["id"])
                self.send_json(None, HTTPStatus.NO_CONTENT)
                publish_event("users", "deleted")
                return
            if path.startswith("/api/ticket-templates/"):
                self.session_user("settings.manage")
                delete_ticket_template(int(path.rsplit("/", 1)[-1]))
                self.send_json(None, HTTPStatus.NO_CONTENT)
                publish_event("ticket_templates", "deleted")
                return
            self.send_json({"error": "Endpoint no disponible"}, HTTPStatus.NOT_FOUND)
        except (ValueError, DatabaseError, ApiError) as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    if not SUPABASE_DATABASE_URL:
        raise RuntimeError("Configura SUPABASE_DATABASE_URL en el archivo .env de OZZVON POS.")
    database = connection()
    database.close()
    print(f"OZZVON POS disponible en http://{HOST}:{port}")
    print("Base de datos: Supabase PostgreSQL")
    server = ThreadingHTTPServer((HOST, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        close_database()
