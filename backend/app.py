from __future__ import annotations

import logging
import hashlib
import importlib.util
import io
import os
import re
import secrets
import sqlite3
import smtplib
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import bcrypt
from flask import Flask, current_app, jsonify, request, session
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_PASSWORD_BYTES = 72
PASSWORD_RESET_TTL = timedelta(hours=1)
POS_SESSION_TTL = timedelta(hours=12)
SOFTWARE_CATALOG = {
    "pos_comercio": "OZZVON POS",
    "pos_restaurante": "OZZVAN POS Restaurante",
}
_POS_COMERCIO_RUNTIME = None


def _connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def _initialize_master_database(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(database_path)) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre_negocio TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                db_path TEXT NOT NULL UNIQUE,
                fecha_creacion TEXT NOT NULL,
                licencia_estado TEXT NOT NULL DEFAULT 'activa'
                    CHECK (licencia_estado IN ('activa', 'suspendida', 'baja')),
                google_sub TEXT UNIQUE
            )
            """
        )
        columns = {
            row["name"] for row in connection.execute('PRAGMA table_info("usuarios")')
        }
        if "licencia_estado" not in columns:
            connection.execute(
                "ALTER TABLE usuarios ADD COLUMN licencia_estado TEXT NOT NULL DEFAULT 'activa'"
            )
        if "google_sub" not in columns:
            connection.execute("ALTER TABLE usuarios ADD COLUMN google_sub TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_google_sub "
                "ON usuarios (google_sub) WHERE google_sub IS NOT NULL"
            )
        connection.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS validate_licencia_estado_insert
            BEFORE INSERT ON usuarios
            WHEN NEW.licencia_estado NOT IN ('activa', 'suspendida', 'baja')
            BEGIN
                SELECT RAISE(ABORT, 'Estado de licencia no válido');
            END;
            CREATE TRIGGER IF NOT EXISTS validate_licencia_estado_update
            BEFORE UPDATE OF licencia_estado ON usuarios
            WHEN NEW.licencia_estado NOT IN ('activa', 'suspendida', 'baja')
            BEGIN
                SELECT RAISE(ABORT, 'Estado de licencia no válido');
            END;
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS password_resets (
                token_hash TEXT PRIMARY KEY,
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS software_catalog (
                clave TEXT PRIMARY KEY,
                nombre TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usuario_software (
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                software_key TEXT NOT NULL REFERENCES software_catalog(clave),
                activo INTEGER NOT NULL DEFAULT 0 CHECK (activo IN (0, 1)),
                sucursales_max INTEGER NOT NULL DEFAULT 1 CHECK (sucursales_max >= 1),
                PRIMARY KEY (usuario_id, software_key)
            );
            CREATE TABLE IF NOT EXISTS sucursales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                software_key TEXT NOT NULL,
                numero INTEGER NOT NULL CHECK (numero >= 1),
                nombre TEXT NOT NULL,
                db_path TEXT NOT NULL UNIQUE,
                activa INTEGER NOT NULL DEFAULT 1 CHECK (activa IN (0, 1)),
                fecha_creacion TEXT NOT NULL,
                UNIQUE (usuario_id, software_key, numero),
                FOREIGN KEY (usuario_id, software_key)
                    REFERENCES usuario_software(usuario_id, software_key)
                    ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS pos_access_tokens (
                token_hash TEXT PRIMARY KEY,
                usuario_id INTEGER NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
                software_key TEXT NOT NULL,
                sucursal_id INTEGER REFERENCES sucursales(id) ON DELETE CASCADE,
                pos_usuario_id INTEGER,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            "INSERT INTO software_catalog (clave, nombre) VALUES (?, ?) "
            "ON CONFLICT(clave) DO NOTHING",
            SOFTWARE_CATALOG.items(),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO usuario_software (
                usuario_id, software_key, activo, sucursales_max
            )
            SELECT id, 'pos_comercio', 1, 1 FROM usuarios
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO usuario_software (
                usuario_id, software_key, activo, sucursales_max
            )
            SELECT u.id, catalog.clave, 0, 1
            FROM usuarios AS u CROSS JOIN software_catalog AS catalog
            WHERE catalog.clave != 'pos_comercio'
            """
        )
        legacy_accounts = connection.execute(
            """
            SELECT u.id, u.db_path FROM usuarios AS u
            JOIN usuario_software AS us ON us.usuario_id = u.id
            WHERE us.software_key = 'pos_comercio' AND us.activo = 1
              AND NOT EXISTS (
                  SELECT 1 FROM sucursales AS s WHERE s.usuario_id = u.id
              )
            """
        ).fetchall()
        for user in legacy_accounts:
            if Path(user["db_path"]).is_file():
                connection.execute(
                    """
                    INSERT INTO sucursales (
                        usuario_id, software_key, numero, nombre, db_path,
                        fecha_creacion
                    ) VALUES (?, 'pos_comercio', 1, 'Sucursal 1', ?, ?)
                    """,
                    (user["id"], user["db_path"], datetime.now(timezone.utc).isoformat()),
                )


def _initialize_tenant_database(database_path: Path, software_key: str) -> None:
    if software_key not in SOFTWARE_CATALOG:
        raise ValueError(f"Plantilla de software no reconocida: {software_key}")
    schema_path = Path(__file__).parent / "schema" / f"{software_key}.sql"
    schema = schema_path.read_text(encoding="utf-8")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_existed = database_path.exists()
    try:
        with closing(_connect(database_path)) as connection, connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(schema)
            if software_key == "pos_comercio":
                for column, definition in (
                    ("subtotal", "REAL"),
                    ("iva", "REAL"),
                    ("tasa_iva", "REAL"),
                    ("usuario_id", "INTEGER"),
                ):
                    _ensure_tenant_column(
                        connection, "ventas", column, definition
                    )
                _ensure_tenant_column(connection, "cajas", "usuario_id", "INTEGER")
                _ensure_tenant_column(
                    connection, "movimientos_caja", "usuario_id", "INTEGER"
                )
            else:
                _ensure_tenant_column(
                    connection,
                    "categories",
                    "menu_id",
                    "TEXT REFERENCES menus(id) ON DELETE CASCADE",
                )
                connection.execute(
                    "UPDATE categories SET menu_id = 'menu-default' WHERE menu_id IS NULL"
                )
                for column, definition in (
                    ("payment_method", "TEXT"),
                    ("amount_received", "REAL"),
                    ("change_amount", "REAL NOT NULL DEFAULT 0"),
                    ("source", "TEXT NOT NULL DEFAULT 'pos'"),
                    ("source_message_id", "TEXT"),
                ):
                    _ensure_tenant_column(connection, "orders", column, definition)
                _ensure_tenant_column(
                    connection, "order_items", "source_product_id", "TEXT"
                )
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_source_message_id "
                    "ON orders(source_message_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_categories_menu_id "
                    "ON categories(menu_id)"
                )
    except sqlite3.Error:
        if not database_existed:
            database_path.unlink(missing_ok=True)
        raise


def _ensure_tenant_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f'PRAGMA table_info("{table}")')
    }
    if column not in columns:
        connection.execute(
            f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition}'
        )


def _error(message: str, status: int):
    return jsonify({"mensaje": message}), status


def _user_profile(user_id: int) -> dict[str, Any] | None:
    with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
        user = connection.execute(
            """
            SELECT id, nombre_negocio, email, fecha_creacion, licencia_estado
            FROM usuarios WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if user is None:
            return None
        software_rows = connection.execute(
            """
            SELECT sc.clave, sc.nombre, us.activo, us.sucursales_max
            FROM usuario_software AS us
            JOIN software_catalog AS sc ON sc.clave = us.software_key
            WHERE us.usuario_id = ?
            ORDER BY sc.clave
            """,
            (user_id,),
        ).fetchall()
        branch_rows = connection.execute(
            """
            SELECT id, software_key, numero, nombre, activa
            FROM sucursales WHERE usuario_id = ?
            ORDER BY software_key, numero
            """,
            (user_id,),
        ).fetchall()
    return {
        "id": user["id"],
        "nombre_negocio": user["nombre_negocio"],
        "email": user["email"],
        "fecha_creacion": user["fecha_creacion"],
        "licencia_estado": user["licencia_estado"],
        "software": [
            {
                "clave": software["clave"],
                "nombre": software["nombre"],
                "activo": bool(software["activo"]),
                "sucursales_max": software["sucursales_max"],
                "sucursales": [
                    {
                        "id": branch["id"],
                        "numero": branch["numero"],
                        "nombre": branch["nombre"],
                        "activa": bool(branch["activa"]),
                    }
                    for branch in branch_rows
                    if branch["software_key"] == software["clave"]
                ],
            }
            for software in software_rows
        ],
    }


def _software_name(software_key: str) -> str | None:
    with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
        row = connection.execute(
            "SELECT nombre FROM software_catalog WHERE clave = ?", (software_key,)
        ).fetchone()
    return row["nombre"] if row else None


def _check_software_access(user_id: int, software_key: str):
    with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
        entitlement = connection.execute(
            """
            SELECT u.licencia_estado, us.activo, us.sucursales_max
            FROM usuarios AS u
            LEFT JOIN usuario_software AS us
              ON us.usuario_id = u.id AND us.software_key = ?
            WHERE u.id = ?
            """,
            (software_key, user_id),
        ).fetchone()
    if entitlement is None:
        return None, _error("No se encontró la cuenta.", 401)
    if entitlement["licencia_estado"] != "activa":
        return None, _error("La licencia de esta cuenta no está activa.", 403)
    if not entitlement["activo"]:
        name = _software_name(software_key) or software_key
        return None, _error(f"Esta cuenta no tiene activo el plan para {name}.", 403)
    return entitlement, None


def _ensure_software_branches(user_id: int, software_key: str) -> list[dict[str, Any]]:
    master_path = Path(current_app.config["MASTER_DB_PATH"])
    tenant_directory = Path(current_app.config["TENANT_DATABASE_DIR"])
    with closing(_connect(master_path)) as connection, connection:
        account = connection.execute(
            """
            SELECT u.db_path, u.nombre_negocio, us.sucursales_max
            FROM usuarios AS u
            JOIN usuario_software AS us ON us.usuario_id = u.id
            WHERE u.id = ? AND us.software_key = ?
            """,
            (user_id, software_key),
        ).fetchone()
        if account is None:
            return []
        branches = connection.execute(
            """
            SELECT numero, db_path FROM sucursales
            WHERE usuario_id = ? AND software_key = ?
            """,
            (user_id, software_key),
        ).fetchall()
        branch_numbers = {branch["numero"] for branch in branches}
        has_assigned_database = connection.execute(
            "SELECT 1 FROM sucursales WHERE usuario_id = ? LIMIT 1",
            (user_id,),
        ).fetchone() is not None
        for number in range(1, account["sucursales_max"] + 1):
            if number in branch_numbers:
                continue
            if number == 1 and not has_assigned_database:
                database_path = Path(account["db_path"])
            else:
                database_path = tenant_directory / f"cliente_{secrets.token_hex(16)}.db"
            was_present = database_path.is_file()
            _initialize_tenant_database(database_path, software_key)
            try:
                connection.execute(
                    """
                    INSERT INTO sucursales (
                        usuario_id, software_key, numero, nombre, db_path, fecha_creacion
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        software_key,
                        number,
                        f"Sucursal {number}",
                        str(database_path.resolve()),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            except (sqlite3.Error, OSError):
                if number != 1 and not was_present:
                    database_path.unlink(missing_ok=True)
                raise
        active_branch_rows = connection.execute(
            """
            SELECT id, numero, nombre, db_path FROM sucursales
            WHERE usuario_id = ? AND software_key = ? AND numero <= ?
            ORDER BY numero
            """,
            (user_id, software_key, account["sucursales_max"]),
        ).fetchall()
        for branch in active_branch_rows:
            database_path = Path(branch["db_path"])
            if not database_path.is_file():
                raise FileNotFoundError(
                    f"No existe la base asignada a la sucursal {branch['id']}."
                )
            _initialize_tenant_database(database_path, software_key)
            with closing(_connect(database_path)) as tenant_connection, tenant_connection:
                if software_key == "pos_comercio":
                    tenant_connection.execute(
                        """
                        UPDATE ajustes SET valor = ?
                        WHERE clave = 'business_name' AND valor = 'OZZVON POS'
                        """,
                        (account["nombre_negocio"],),
                    )
                else:
                    tenant_connection.execute(
                        """
                        UPDATE settings SET value = ?
                        WHERE key = 'name' AND value = ''
                        """,
                        (account["nombre_negocio"],),
                    )
        connection.execute(
            """
            UPDATE sucursales SET activa = CASE WHEN numero <= ? THEN 1 ELSE 0 END
            WHERE usuario_id = ? AND software_key = ?
            """,
            (account["sucursales_max"], user_id, software_key),
        )
        return [
            dict(branch)
            for branch in connection.execute(
                """
                SELECT id, numero, nombre, activa FROM sucursales
                WHERE usuario_id = ? AND software_key = ? AND activa = 1
                ORDER BY numero
                """,
                (user_id, software_key),
            ).fetchall()
        ]


def _load_pos_comercio_runtime():
    global _POS_COMERCIO_RUNTIME
    if _POS_COMERCIO_RUNTIME is not None:
        return _POS_COMERCIO_RUNTIME
    deployed_path = Path(__file__).parent / "pos_comercio_runtime.py"
    development_path = (
        Path(__file__).resolve().parents[1] / "OZZVAN POS" / "backend" / "app.py"
    )
    runtime_path = deployed_path if deployed_path.is_file() else development_path
    if not runtime_path.is_file():
        raise FileNotFoundError(
            "Falta backend/pos_comercio_runtime.py en el servidor."
        )
    spec = importlib.util.spec_from_file_location(
        "ozzvon_pos_comercio_runtime", runtime_path
    )
    if spec is None or spec.loader is None:
        raise ImportError("No se pudo cargar el runtime de OZZVON POS Comercio.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _POS_COMERCIO_RUNTIME = module
    return module


def _ensure_branch_superuser(database_path: Path, business_name: str) -> int:
    runtime = _load_pos_comercio_runtime()
    token = runtime.use_tenant_database(str(database_path))
    try:
        database = runtime.connection()
        try:
            admin = database.execute(
                "SELECT id FROM usuarios WHERE usuario = 'admin'"
            ).fetchone()
            if admin is None:
                role = database.execute(
                    "SELECT id FROM roles WHERE nombre = 'Administrador'"
                ).fetchone()
                if role is None:
                    raise sqlite3.IntegrityError(
                        "No existe el rol Administrador en la base de la sucursal."
                    )
                random_password_hash = hashlib.sha256(
                    secrets.token_bytes(64)
                ).hexdigest()
                cursor = database.execute(
                    """
                    INSERT INTO usuarios (nombre, usuario, password_hash, rol_id)
                    VALUES (?, 'admin', ?, ?)
                    """,
                    ("Superusuario", random_password_hash, role["id"]),
                )
                admin_id = cursor.lastrowid
            else:
                admin_id = admin["id"]
                database.execute(
                    "UPDATE usuarios SET nombre = 'Superusuario', activo = 1 WHERE id = ?",
                    (admin_id,),
                )
            database.execute(
                "UPDATE ajustes SET valor = ? WHERE clave = 'business_name'",
                (business_name,),
            )
            database.commit()
            return admin_id
        finally:
            database.close()
    finally:
        runtime.reset_tenant_database(token)


def _pos_token_record(token: str | None):
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection, connection:
        connection.execute("DELETE FROM pos_access_tokens WHERE expires_at <= ?", (now,))
        return connection.execute(
            """
            SELECT token.usuario_id, token.software_key, token.sucursal_id,
                   token.pos_usuario_id, user.licencia_estado, entitlement.activo,
                   entitlement.sucursales_max, user.nombre_negocio
            FROM pos_access_tokens AS token
            JOIN usuarios AS user ON user.id = token.usuario_id
            JOIN usuario_software AS entitlement
              ON entitlement.usuario_id = token.usuario_id
             AND entitlement.software_key = token.software_key
            WHERE token.token_hash = ? AND token.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()


def _create_pos_access_token(
    user_id: int,
    branch_id: int | None = None,
    pos_user_id: int | None = None,
) -> str:
    raw_token = secrets.token_urlsafe(48)
    now = datetime.now(timezone.utc)
    with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection, connection:
        connection.execute(
            """
            INSERT INTO pos_access_tokens (
                token_hash, usuario_id, software_key, sucursal_id,
                pos_usuario_id, expires_at, created_at
            ) VALUES (?, ?, 'pos_comercio', ?, ?, ?, ?)
            """,
            (
                hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                user_id,
                branch_id,
                pos_user_id,
                (now + POS_SESSION_TTL).isoformat(),
                now.isoformat(),
            ),
        )
    return raw_token


def _pos_api_path_allowed(method: str, path: str) -> bool:
    exact_paths = {
        "GET": {
            "products", "clients", "sales", "suppliers", "purchases",
            "cash/current", "cash/history", "reports", "settings", "tax-rate",
            "ticket-templates", "invoices", "users", "roles", "health",
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
    if method not in {"PUT", "DELETE"}:
        return False
    return bool(
        re.fullmatch(r"(?:products|clients|users)/[1-9]\d*", path)
        or re.fullmatch(r"ticket-templates/[1-9]\d*", path)
    )


def _reset_email_configured() -> bool:
    configured = all(
        current_app.config.get(key)
        for key in (
            "SMTP_HOST",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "PUBLIC_BASE_URL",
        )
    )
    return bool(
        configured
        and urlparse(current_app.config["PUBLIC_BASE_URL"]).scheme == "https"
    )


def _send_password_reset_email(email: str, reset_url: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Restablece tu contraseña de Ozzvon"
    message["From"] = current_app.config["SMTP_FROM"]
    message["To"] = email
    message.set_content(
        "Recibimos una solicitud para restablecer la contraseña de tu cuenta "
        "Ozzvon. Abre este enlace dentro de la próxima hora:\n\n"
        f"{reset_url}\n\n"
        "Si no solicitaste el cambio, puedes ignorar este mensaje."
    )
    host = current_app.config["SMTP_HOST"]
    port = int(current_app.config.get("SMTP_PORT", 587))
    timeout = int(current_app.config.get("SMTP_TIMEOUT", 10))
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=timeout) as server:
            server.login(
                current_app.config["SMTP_USERNAME"],
                current_app.config["SMTP_PASSWORD"],
            )
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=timeout) as server:
            server.starttls()
            server.login(
                current_app.config["SMTP_USERNAME"],
                current_app.config["SMTP_PASSWORD"],
            )
            server.send_message(message)


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        MASTER_DB_PATH=os.environ.get(
            "MASTER_DB_PATH", str(Path(__file__).parent / "data" / "master.db")
        ),
        TENANT_DATABASE_DIR=os.environ.get(
            "TENANT_DATABASE_DIR", str(Path(__file__).parent / "data" / "tenants")
        ),
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID", ""),
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=os.environ.get("SMTP_PORT", "587"),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_FROM=os.environ.get("SMTP_FROM", ""),
        SMTP_TIMEOUT=os.environ.get("SMTP_TIMEOUT", "10"),
        PUBLIC_BASE_URL=os.environ.get("PUBLIC_BASE_URL", ""),
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "1") != "0",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        MAX_CONTENT_LENGTH=1_000_000,
    )
    if test_config:
        app.config.update(test_config)

    allowed_origins = [
        origin.strip()
        for origin in os.environ.get("CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}})
    _initialize_master_database(Path(app.config["MASTER_DB_PATH"]))

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_too_large(_exception: RequestEntityTooLarge):
        return _error("La solicitud excede el tamaño permitido.", 413)

    @app.post("/api/registro")
    def register():
        if not request.is_json:
            return _error("Envía los datos en formato JSON.", 400)

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _error("El contenido JSON no es válido.", 400)

        business_name = data.get("nombre_negocio")
        email = data.get("email")
        password = data.get("password")
        if not all(isinstance(value, str) for value in (business_name, email, password)):
            return _error("Completa el nombre del negocio, correo y contraseña.", 400)

        business_name = business_name.strip()
        email = email.strip().casefold()
        if not business_name or len(business_name) > 100:
            return _error("El nombre del negocio debe tener entre 1 y 100 caracteres.", 400)
        if len(email) > 254 or not EMAIL_PATTERN.fullmatch(email):
            return _error("Escribe un correo electrónico válido.", 400)
        try:
            password_size = len(password.encode("utf-8"))
        except UnicodeEncodeError:
            return _error("La contraseña contiene caracteres no válidos.", 400)
        if password_size < 8 or password_size > MAX_PASSWORD_BYTES:
            return _error("La contraseña debe tener entre 8 y 72 bytes.", 400)

        master_database_path = Path(current_app.config["MASTER_DB_PATH"])
        tenant_directory = Path(current_app.config["TENANT_DATABASE_DIR"])
        tenant_path = tenant_directory / f"cliente_{secrets.token_hex(8)}.db"
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("ascii")

        try:
            with closing(_connect(master_database_path)) as connection, connection:
                cursor = connection.execute(
                    """
                    INSERT INTO usuarios (
                        nombre_negocio, email, password_hash, db_path, fecha_creacion
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        business_name,
                        email,
                        password_hash,
                        str(tenant_path.resolve()),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                user_id = cursor.lastrowid
                connection.executemany(
                    """
                    INSERT INTO usuario_software (
                        usuario_id, software_key, activo, sucursales_max
                    ) VALUES (?, ?, 0, 1)
                    """,
                    [(user_id, software_key) for software_key in SOFTWARE_CATALOG],
                )
        except sqlite3.IntegrityError:
            tenant_path.unlink(missing_ok=True)
            return _error("Ya existe una cuenta con ese correo electrónico.", 409)
        except sqlite3.Error:
            tenant_path.unlink(missing_ok=True)
            current_app.logger.exception("No se pudo guardar la cuenta de usuario.")
            return _error("No se pudo crear la cuenta. Inténtalo de nuevo.", 500)
        except OSError:
            tenant_path.unlink(missing_ok=True)
            current_app.logger.exception("No se pudo guardar la cuenta de usuario.")
            return _error("No se pudo crear la cuenta. Inténtalo de nuevo.", 500)

        session.clear()
        session["usuario_id"] = user_id
        session.permanent = True
        return jsonify(
            {"mensaje": "¡Tu cuenta fue creada correctamente!", "usuario_id": user_id}
        ), 201

    @app.post("/api/auth/login")
    def login():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _error("Envía los datos en formato JSON.", 400)
        email = data.get("email")
        password = data.get("password")
        software_key = data.get("software")
        if not isinstance(email, str) or not isinstance(password, str):
            return _error("Escribe tu correo y contraseña.", 400)
        if software_key is not None and (
            not isinstance(software_key, str) or software_key not in SOFTWARE_CATALOG
        ):
            return _error("El software solicitado no es válido.", 400)

        with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
            user = connection.execute(
                "SELECT id, password_hash FROM usuarios WHERE email = ? COLLATE NOCASE",
                (email.strip(),),
            ).fetchone()
        try:
            password_matches = user is not None and bcrypt.checkpw(
                password.encode("utf-8"), user["password_hash"].encode("ascii")
            )
        except (ValueError, UnicodeEncodeError):
            password_matches = False
        if not password_matches:
            return _error("El correo o la contraseña no son correctos.", 401)

        session.clear()
        branches = None
        if software_key:
            _, access_error = _check_software_access(user["id"], software_key)
            if access_error:
                session.clear()
                return access_error
            try:
                branches = _ensure_software_branches(user["id"], software_key)
            except (sqlite3.Error, OSError):
                current_app.logger.exception(
                    "No se pudieron preparar las sucursales del software autorizado."
                )
                return _error("No se pudo preparar el espacio de trabajo.", 500)

        session["usuario_id"] = user["id"]
        session.permanent = True
        if software_key:
            profile = _user_profile(user["id"])
            return jsonify(
                {
                    "mensaje": "Sesión iniciada.",
                    "cuenta": profile,
                    "software": {
                        "clave": software_key,
                        "nombre": _software_name(software_key),
                    },
                    "sucursales": branches,
                }
            ), 200
        return jsonify({"mensaje": "Sesión iniciada."}), 200

    @app.post("/api/auth/logout")
    def logout():
        session.clear()
        return jsonify({"mensaje": "Sesión cerrada."}), 200

    @app.get("/api/cuenta")
    def account():
        user_id = session.get("usuario_id")
        if not isinstance(user_id, int):
            return _error("Inicia sesión para consultar tu cuenta.", 401)
        profile = _user_profile(user_id)
        if profile is None:
            session.clear()
            return _error("No se encontró la cuenta.", 401)
        return jsonify({"cuenta": profile}), 200

    @app.post("/api/pos/pos_comercio/login")
    def pos_owner_login():
        data = request.get_json(silent=True)
        email = data.get("email") if isinstance(data, dict) else None
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(email, str) or not isinstance(password, str):
            return _error("Escribe el correo y contraseña de tu cuenta Ozzvon.", 400)
        with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
            user = connection.execute(
                """
                SELECT id, email, password_hash, nombre_negocio, licencia_estado
                FROM usuarios WHERE email = ? COLLATE NOCASE
                """,
                (email.strip(),),
            ).fetchone()
        try:
            password_matches = user is not None and bcrypt.checkpw(
                password.encode("utf-8"), user["password_hash"].encode("ascii")
            )
        except (ValueError, UnicodeEncodeError):
            password_matches = False
        if not password_matches:
            return _error("El correo o la contraseña no son correctos.", 401)
        _, access_error = _check_software_access(user["id"], "pos_comercio")
        if access_error:
            return access_error
        try:
            branches = _ensure_software_branches(user["id"], "pos_comercio")
            for branch in branches:
                with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
                    branch_database = connection.execute(
                        "SELECT db_path FROM sucursales WHERE id = ? AND usuario_id = ?",
                        (branch["id"], user["id"]),
                    ).fetchone()
                if branch_database is None:
                    return _error("No se encontró la base de datos de una sucursal.", 500)
                _ensure_branch_superuser(
                    Path(branch_database["db_path"]), user["nombre_negocio"]
                )
        except (sqlite3.Error, OSError, ImportError, RuntimeError):
            current_app.logger.exception(
                "No se pudo preparar el acceso del propietario a OZZVON POS."
            )
            return _error("No se pudo preparar el acceso a las sucursales.", 500)
        access_token = _create_pos_access_token(user["id"])
        return jsonify(
            {
                "token": access_token,
                "user": {
                    "id": user["id"],
                    "name": user["nombre_negocio"],
                    "username": user["email"],
                    "role": "Superusuario",
                    "permissions": [
                        "dashboard.view", "sales.create", "inventory.view",
                        "inventory.manage", "clients.view", "clients.manage",
                        "reports.view", "cash.view", "cash.manage", "users.manage",
                        "settings.manage", "billing.view",
                    ],
                },
                "branches": branches,
            }
        ), 200

    @app.post("/api/pos/pos_comercio/sucursales/<int:branch_id>/login")
    def pos_staff_login(branch_id: int):
        data = request.get_json(silent=True)
        username = data.get("username") if isinstance(data, dict) else None
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(username, str) or not isinstance(password, str):
            return _error("Escribe tu usuario y contraseña del POS.", 400)
        with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
            branch = connection.execute(
                """
                SELECT s.id, s.usuario_id, s.db_path, u.licencia_estado, us.activo,
                       us.sucursales_max
                FROM sucursales AS s
                JOIN usuarios AS u ON u.id = s.usuario_id
                JOIN usuario_software AS us
                  ON us.usuario_id = s.usuario_id
                 AND us.software_key = s.software_key
                WHERE s.id = ? AND s.software_key = 'pos_comercio'
                  AND s.activa = 1 AND s.numero <= us.sucursales_max
                """,
                (branch_id,),
            ).fetchone()
        if (
            branch is None
            or branch["licencia_estado"] != "activa"
            or not branch["activo"]
        ):
            return _error("Esta sucursal no tiene un plan activo.", 403)
        try:
            runtime = _load_pos_comercio_runtime()
        except (OSError, ImportError, RuntimeError):
            current_app.logger.exception("No se pudo cargar el runtime de OZZVON POS.")
            return _error("El inicio de sesión del POS no está disponible.", 503)
        try:
            path = Path(branch["db_path"])
            if not path.is_file():
                return _error("No se encontró la base de datos de la sucursal.", 404)
            context_token = runtime.use_tenant_database(str(path))
            try:
                database = runtime.connection()
                try:
                    employee = database.execute(
                        """
                        SELECT id, nombre, usuario, password_hash
                        FROM usuarios WHERE usuario = ? AND activo = 1
                        """,
                        (username.strip(),),
                    ).fetchone()
                finally:
                    database.close()
            finally:
                runtime.reset_tenant_database(context_token)
        except (sqlite3.Error, OSError, ImportError, RuntimeError):
            current_app.logger.exception("No se pudo validar el usuario de sucursal.")
            return _error("No se pudo iniciar sesión en esta sucursal.", 500)
        password_hash = hashlib.sha256(password.encode("utf-8")).hexdigest()
        if employee is None or not secrets.compare_digest(
            employee["password_hash"], password_hash
        ):
            return _error("El usuario o la contraseña no son correctos.", 401)
        token = _create_pos_access_token(
            branch["usuario_id"], branch_id, employee["id"]
        )
        try:
            context_token = runtime.use_tenant_database(str(path))
            try:
                database = runtime.connection()
                try:
                    user = runtime.user_payload(database, employee["id"])
                finally:
                    database.close()
            finally:
                runtime.reset_tenant_database(context_token)
        except (sqlite3.Error, OSError, ImportError, RuntimeError, ValueError, runtime.ApiError):
            current_app.logger.exception("No se pudo cargar el perfil del usuario POS.")
            return _error("No se pudo cargar el perfil del usuario.", 500)
        return jsonify({"token": token, "user": user}), 200

    @app.get("/api/pos/pos_comercio/branches")
    def pos_list_branches():
        access = _pos_token_record(
            request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        )
        if access is None or access["sucursal_id"] is not None or access["pos_usuario_id"] is not None:
            return _error("Inicia sesión como propietario para consultar las sucursales.", 401)
        if access["licencia_estado"] != "activa" or not access["activo"]:
            return _error("El plan OZZVON POS no está activo.", 403)
        try:
            branches = _ensure_software_branches(access["usuario_id"], "pos_comercio")
        except (sqlite3.Error, OSError):
            current_app.logger.exception("No se pudieron actualizar las sucursales POS.")
            return _error("No se pudieron consultar las sucursales.", 500)
        return jsonify({"branches": branches}), 200

    @app.post("/api/pos/logout")
    def pos_logout():
        token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if token:
            with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection, connection:
                connection.execute(
                    "DELETE FROM pos_access_tokens WHERE token_hash = ?",
                    (hashlib.sha256(token.encode("utf-8")).hexdigest(),),
                )
        return jsonify({"mensaje": "Sesión cerrada."}), 200

    @app.route(
        "/api/pos/pos_comercio/sucursales/<int:branch_id>/api/<path:pos_path>",
        methods=["GET", "POST", "PUT", "DELETE"],
    )
    def pos_branch_api(branch_id: int, pos_path: str):
        if not _pos_api_path_allowed(request.method, pos_path):
            return _error("Endpoint del POS no disponible.", 404)
        raw_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        access = _pos_token_record(raw_token)
        if (
            access is None
            or access["licencia_estado"] != "activa"
            or not access["activo"]
        ):
            return _error("La sesión o el plan del POS ya no están activos.", 401)
        if access["sucursal_id"] is not None and access["sucursal_id"] != branch_id:
            return _error("Esta sesión no pertenece a la sucursal seleccionada.", 403)
        with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
            branch = connection.execute(
                """
                SELECT id, db_path FROM sucursales
                WHERE id = ? AND usuario_id = ? AND software_key = 'pos_comercio'
                  AND activa = 1 AND numero <= ?
                """,
                (branch_id, access["usuario_id"], access["sucursales_max"]),
            ).fetchone()
        if branch is None:
            return _error("La sucursal no existe o no está autorizada.", 404)
        database_path = Path(branch["db_path"])
        if not database_path.is_file():
            return _error("No se encontró la base de datos de la sucursal.", 404)
        try:
            runtime = _load_pos_comercio_runtime()
        except (OSError, ImportError, RuntimeError):
            current_app.logger.exception("No se pudo cargar el runtime de OZZVON POS.")
            return _error("El API de OZZVON POS no está disponible.", 503)
        try:
            if access["pos_usuario_id"] is None:
                user_id = _ensure_branch_superuser(
                    database_path, access["nombre_negocio"]
                )
            else:
                user_id = access["pos_usuario_id"]
                context_token = runtime.use_tenant_database(str(database_path))
                try:
                    database = runtime.connection()
                    try:
                        runtime.user_payload(database, user_id)
                    finally:
                        database.close()
                finally:
                    runtime.reset_tenant_database(context_token)
            internal_token = secrets.token_urlsafe(32)
            runtime.SESSIONS[internal_token] = user_id
            body = request.get_data(cache=True)

            class BufferedPosHandler(runtime.Handler):
                def __init__(self):
                    self.path = "/api/" + pos_path
                    if request.query_string:
                        self.path += "?" + request.query_string.decode("ascii")
                    self.headers = {
                        "Authorization": f"Bearer {internal_token}",
                        "Content-Length": str(len(body)),
                    }
                    self.rfile = io.BytesIO(body)
                    self.status = 200
                    self.payload = None

                def send_json(self, payload, status=200):
                    self.payload = payload
                    self.status = int(status)

            handler = BufferedPosHandler()
            context_token = runtime.use_tenant_database(str(database_path))
            try:
                getattr(handler, f"do_{request.method}")()
            finally:
                runtime.reset_tenant_database(context_token)
                runtime.SESSIONS.pop(internal_token, None)
        except runtime.ApiError as error:
            return jsonify({"error": str(error)}), 403
        except (sqlite3.Error, OSError, ValueError, TypeError):
            current_app.logger.exception("Falló una operación del POS en su sucursal.")
            return _error("No se pudo completar la operación del POS.", 500)
        if handler.status == 204:
            return "", 204
        return jsonify(handler.payload), handler.status

    @app.get("/api/software/<software_key>/sucursales")
    def software_branches(software_key: str):
        if software_key not in SOFTWARE_CATALOG:
            return _error("El software solicitado no es válido.", 404)
        user_id = session.get("usuario_id")
        if not isinstance(user_id, int):
            return _error("Inicia sesión para consultar tus sucursales.", 401)
        _, access_error = _check_software_access(user_id, software_key)
        if access_error:
            return access_error
        try:
            branches = _ensure_software_branches(user_id, software_key)
        except (sqlite3.Error, OSError):
            current_app.logger.exception("No se pudieron consultar las sucursales.")
            return _error("No se pudieron consultar las sucursales.", 500)
        return jsonify(
            {
                "software": {
                    "clave": software_key,
                    "nombre": _software_name(software_key),
                },
                "sucursales": branches,
            }
        ), 200

    @app.get(
        "/api/software/<software_key>/sucursales/<int:branch_id>/datos"
    )
    def software_branch_data(software_key: str, branch_id: int):
        if software_key not in SOFTWARE_CATALOG:
            return _error("El software solicitado no es válido.", 404)
        user_id = session.get("usuario_id")
        if not isinstance(user_id, int):
            return _error("Inicia sesión para consultar los datos.", 401)
        _, access_error = _check_software_access(user_id, software_key)
        if access_error:
            return access_error
        try:
            _ensure_software_branches(user_id, software_key)
            with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection:
                branch = connection.execute(
                    """
                    SELECT db_path FROM sucursales
                    WHERE id = ? AND usuario_id = ? AND software_key = ? AND activa = 1
                    """,
                    (branch_id, user_id, software_key),
                ).fetchone()
            if branch is None:
                return _error("La sucursal no existe o no está habilitada.", 404)
            with closing(_connect(Path(branch["db_path"]))) as connection:
                table_names = (
                    ("clientes", "productos", "cajas", "movimientos_caja", "ventas",
                     "detalle_ventas", "ajustes", "facturas", "proveedores", "compras",
                     "detalle_compras")
                    if software_key == "pos_comercio"
                    else ("menus", "settings", "categories", "products", "product_sizes",
                          "orders", "order_items")
                )
                data = {
                    table: [
                        dict(row)
                        for row in connection.execute(
                            f'SELECT * FROM "{table}" LIMIT 100'
                        ).fetchall()
                    ]
                    for table in table_names
                }
        except (sqlite3.Error, OSError):
            current_app.logger.exception("No se pudieron consultar los datos de la sucursal.")
            return _error("No se pudieron consultar los datos de la sucursal.", 500)
        return jsonify({"sucursal_id": branch_id, "datos": data}), 200

    @app.get("/api/auth/config")
    def auth_config():
        return jsonify(
            {"google_client_id": current_app.config["GOOGLE_CLIENT_ID"]}
        ), 200

    @app.post("/api/auth/google")
    def google_login():
        client_id = current_app.config["GOOGLE_CLIENT_ID"]
        data = request.get_json(silent=True)
        credential = data.get("credential") if isinstance(data, dict) else None
        if not client_id:
            return _error("El inicio con Google aún no está configurado.", 503)
        if not isinstance(credential, str) or not credential:
            return _error("No se recibió una credencial válida de Google.", 400)

        try:
            from google.auth import exceptions as google_exceptions
            from google.auth.transport import requests as google_requests
            from google.oauth2 import id_token
        except ImportError:
            current_app.logger.exception("Faltan dependencias para verificar Google.")
            return _error("El inicio con Google no está disponible en el servidor.", 503)
        try:
            google_user = id_token.verify_oauth2_token(
                credential, google_requests.Request(), client_id
            )
        except ValueError:
            return _error("No se pudo verificar tu cuenta de Google.", 401)
        except google_exceptions.GoogleAuthError:
            current_app.logger.exception("Falló la verificación remota de Google.")
            return _error("No se pudo verificar Google en este momento.", 503)

        google_sub = google_user.get("sub")
        email = google_user.get("email")
        if (
            not isinstance(google_sub, str)
            or not isinstance(email, str)
            or google_user.get("email_verified") is not True
        ):
            return _error("Google no confirmó un correo electrónico verificado.", 401)
        email = email.strip().casefold()

        master_database_path = Path(current_app.config["MASTER_DB_PATH"])
        with closing(_connect(master_database_path)) as connection, connection:
            user = connection.execute(
                "SELECT id, google_sub FROM usuarios WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
            if user is not None and user["google_sub"] != google_sub:
                return _error(
                    "Ese correo ya tiene una cuenta. Inicia sesión con tu contraseña.",
                    409,
                )
            if user is None:
                business_name = data.get("nombre_negocio")
                if not isinstance(business_name, str) or not business_name.strip():
                    return _error(
                        "Escribe el nombre de tu negocio antes de continuar con Google.",
                        400,
                    )
                business_name = business_name.strip()
                if len(business_name) > 100:
                    return _error("El nombre del negocio no puede exceder 100 caracteres.", 400)

                tenant_directory = Path(current_app.config["TENANT_DATABASE_DIR"])
                tenant_path = tenant_directory / f"cliente_{secrets.token_hex(8)}.db"
                try:
                    password_hash = bcrypt.hashpw(
                        secrets.token_bytes(32), bcrypt.gensalt()
                    ).decode("ascii")
                    cursor = connection.execute(
                        """
                        INSERT INTO usuarios (
                            nombre_negocio, email, password_hash, db_path,
                            fecha_creacion, google_sub
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            business_name,
                            email,
                            password_hash,
                            str(tenant_path.resolve()),
                            datetime.now(timezone.utc).isoformat(),
                            google_sub,
                        ),
                    )
                    user_id = cursor.lastrowid
                    connection.executemany(
                        """
                        INSERT INTO usuario_software (
                            usuario_id, software_key, activo, sucursales_max
                        ) VALUES (?, ?, 0, 1)
                        """,
                        [(user_id, software_key) for software_key in SOFTWARE_CATALOG],
                    )
                except (sqlite3.Error, OSError):
                    tenant_path.unlink(missing_ok=True)
                    current_app.logger.exception("No se pudo crear la cuenta de Google.")
                    return _error("No se pudo crear la cuenta. Inténtalo de nuevo.", 500)
            else:
                user_id = user["id"]

        session.clear()
        session["usuario_id"] = user_id
        session.permanent = True
        return jsonify({"mensaje": "Sesión iniciada con Google."}), 200

    @app.post("/api/auth/forgot-password")
    def forgot_password():
        if not _reset_email_configured():
            return _error(
                "El restablecimiento por correo aún no está configurado en el servidor.",
                503,
            )
        data = request.get_json(silent=True)
        email = data.get("email") if isinstance(data, dict) else None
        if not isinstance(email, str) or not EMAIL_PATTERN.fullmatch(email.strip()):
            return _error("Escribe un correo electrónico válido.", 400)
        email = email.strip().casefold()

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        now = datetime.now(timezone.utc)
        with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection, connection:
            connection.execute(
                "DELETE FROM password_resets WHERE expires_at <= ?",
                (now.isoformat(),),
            )
            user = connection.execute(
                "SELECT id FROM usuarios WHERE email = ? COLLATE NOCASE",
                (email,),
            ).fetchone()
            if user is not None:
                connection.execute(
                    """
                    INSERT INTO password_resets (token_hash, usuario_id, expires_at, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        token_hash,
                        user["id"],
                        (now + PASSWORD_RESET_TTL).isoformat(),
                        now.isoformat(),
                    ),
                )

        if user is not None:
            reset_url = (
                f"{current_app.config['PUBLIC_BASE_URL'].rstrip('/')}/"
                f"#restablecer={token}"
            )
            try:
                _send_password_reset_email(email, reset_url)
            except (OSError, ValueError, smtplib.SMTPException):
                with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection, connection:
                    connection.execute(
                        "DELETE FROM password_resets WHERE token_hash = ?", (token_hash,)
                    )
                current_app.logger.exception("No se pudo enviar el correo de restablecimiento.")
                return _error("No se pudo enviar el correo. Inténtalo más tarde.", 503)
        return jsonify(
            {"mensaje": "Si existe una cuenta con ese correo, recibirá un enlace para restablecer la contraseña."}
        ), 202

    @app.post("/api/auth/reset-password")
    def reset_password():
        data = request.get_json(silent=True)
        token = data.get("token") if isinstance(data, dict) else None
        password = data.get("password") if isinstance(data, dict) else None
        if not isinstance(token, str) or not isinstance(password, str):
            return _error("El enlace o la contraseña no son válidos.", 400)
        try:
            password_size = len(password.encode("utf-8"))
        except UnicodeEncodeError:
            return _error("La contraseña contiene caracteres no válidos.", 400)
        if password_size < 8 or password_size > MAX_PASSWORD_BYTES:
            return _error("La contraseña debe tener entre 8 y 72 bytes.", 400)

        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("ascii")
        with closing(_connect(Path(current_app.config["MASTER_DB_PATH"]))) as connection, connection:
            reset = connection.execute(
                "SELECT usuario_id, expires_at FROM password_resets WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
            if reset is None or datetime.fromisoformat(reset["expires_at"]) <= now:
                return _error("El enlace expiró o ya fue utilizado. Solicita uno nuevo.", 400)
            connection.execute(
                "UPDATE usuarios SET password_hash = ? WHERE id = ?",
                (password_hash, reset["usuario_id"]),
            )
            connection.execute(
                "DELETE FROM password_resets WHERE usuario_id = ?",
                (reset["usuario_id"],),
            )
            user_id = reset["usuario_id"]
        session.clear()
        session["usuario_id"] = user_id
        session.permanent = True
        return jsonify({"mensaje": "Contraseña actualizada correctamente."}), 200

    return app


app = create_app()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")))
