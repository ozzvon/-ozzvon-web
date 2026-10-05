from __future__ import annotations

import sqlite3
import hashlib
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import bcrypt

from app import create_app


class RegistrationApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.master_path = root / "master.db"
        self.tenant_directory = root / "tenants"
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-session-key",
                "SESSION_COOKIE_SECURE": False,
                "MASTER_DB_PATH": self.master_path,
                "TENANT_DATABASE_DIR": self.tenant_directory,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_directory.cleanup()

    def register(self, **overrides):
        payload = {
            "nombre_negocio": "Mi negocio",
            "email": "dueno@example.com",
            "password": "una-clave-segura",
        }
        payload.update(overrides)
        return self.client.post("/api/registro", json=payload)

    def activate_software(self, software_key, branch_limit=1, email="dueno@example.com"):
        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            connection.execute(
                """
                UPDATE usuario_software
                SET activo = 1, sucursales_max = ?
                WHERE usuario_id = (
                    SELECT id FROM usuarios WHERE email = ?
                ) AND software_key = ?
                """,
                (branch_limit, email, software_key),
            )

    def test_master_database_migrates_existing_user_table(self):
        legacy_path = Path(self.temp_directory.name) / "legacy.db"
        legacy_tenant_path = Path(self.temp_directory.name) / "legacy-tenant.db"
        legacy_tenant_path.touch()
        with closing(sqlite3.connect(legacy_path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre_negocio TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    db_path TEXT NOT NULL UNIQUE,
                    fecha_creacion TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                INSERT INTO usuarios (
                    nombre_negocio, email, password_hash, db_path, fecha_creacion
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "Negocio anterior",
                    "anterior@example.com",
                    "hash",
                    str(legacy_tenant_path),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        legacy_app = create_app(
            {
                "TESTING": True,
                "MASTER_DB_PATH": legacy_path,
                "TENANT_DATABASE_DIR": self.tenant_directory,
            }
        )
        with closing(sqlite3.connect(legacy_path)) as connection:
            columns = {
                row[1] for row in connection.execute('PRAGMA table_info("usuarios")')
            }
            invalid_status = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' "
                "AND name = 'validate_licencia_estado_update'"
            ).fetchone()

        self.assertIn("licencia_estado", columns)
        self.assertIn("google_sub", columns)
        self.assertIsNotNone(invalid_status)
        with closing(sqlite3.connect(legacy_path)) as connection:
            account_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue(
            {"software_catalog", "usuario_software", "sucursales"}.issubset(
                account_tables
            )
        )
        with closing(sqlite3.connect(legacy_path)) as connection:
            legacy_plan = connection.execute(
                """
                SELECT activo, sucursales_max FROM usuario_software
                WHERE usuario_id = 1 AND software_key = 'pos_comercio'
                """
            ).fetchone()
            legacy_branch = connection.execute(
                """
                SELECT numero, db_path FROM sucursales
                WHERE usuario_id = 1 AND software_key = 'pos_comercio'
                """
            ).fetchone()
        self.assertEqual(legacy_plan, (1, 1))
        self.assertEqual(legacy_branch, (1, str(legacy_tenant_path)))
        self.assertIsNotNone(legacy_app)

    def test_register_waits_for_plan_before_creating_software_schema(self):
        response = self.register()

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["mensaje"], "¡Tu cuenta fue creada correctamente!")
        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            user = connection.execute(
                "SELECT nombre_negocio, email, password_hash, db_path FROM usuarios"
            ).fetchone()

        self.assertEqual(user[0], "Mi negocio")
        self.assertEqual(user[1], "dueno@example.com")
        self.assertTrue(bcrypt.checkpw(b"una-clave-segura", user[2].encode("ascii")))
        tenant_path = Path(user[3])
        self.assertFalse(tenant_path.exists())
        account_response = self.client.get("/api/cuenta")
        self.assertEqual(account_response.status_code, 200)
        products = account_response.json["cuenta"]["software"]
        self.assertEqual(
            {product["clave"] for product in products},
            {"pos_comercio", "pos_restaurante"},
        )
        self.assertTrue(all(not product["activo"] for product in products))
        self.assertNotIn("db_path", account_response.json["cuenta"])
        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            connection.execute(
                "UPDATE software_catalog SET nombre = ? WHERE clave = ?",
                ("Ozzvon Comercio", "pos_comercio"),
            )
        renamed_products = self.client.get("/api/cuenta").json["cuenta"]["software"]
        self.assertEqual(
            next(
                product["nombre"]
                for product in renamed_products
                if product["clave"] == "pos_comercio"
            ),
            "Ozzvon Comercio",
        )

        self.activate_software("pos_comercio")
        login_response = self.client.post(
            "/api/auth/login",
            json={
                "email": "dueno@example.com",
                "password": "una-clave-segura",
                "software": "pos_comercio",
            },
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertTrue(tenant_path.is_file())
        with closing(sqlite3.connect(tenant_path)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            tables_for_pos = {
                "clientes", "productos", "cajas", "movimientos_caja", "roles",
                "usuarios", "ventas", "detalle_ventas", "ajustes", "facturas",
                "ticket_templates", "proveedores", "compras", "detalle_compras",
            }
            self.assertEqual(tables, tables_for_pos)
            self.assertEqual(
                connection.execute(
                    "SELECT valor FROM ajustes WHERE clave = 'business_name'"
                ).fetchone()[0],
                "Mi negocio",
            )

    def test_each_restaurant_branch_uses_restaurant_schema(self):
        self.assertEqual(self.register().status_code, 201)
        self.activate_software("pos_restaurante", branch_limit=3)

        response = self.client.post(
            "/api/auth/login",
            json={
                "email": "dueno@example.com",
                "password": "una-clave-segura",
                "software": "pos_restaurante",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json["sucursales"]), 3)
        with closing(sqlite3.connect(self.master_path)) as connection:
            paths = [
                row[0]
                for row in connection.execute(
                    "SELECT db_path FROM sucursales "
                    "WHERE software_key = 'pos_restaurante' ORDER BY numero"
                )
            ]
        expected_tables = {
            "menus", "settings", "categories", "products", "product_sizes",
            "orders", "order_items",
        }
        self.assertEqual(len(paths), 3)
        self.assertEqual(len(set(paths)), 3)
        for path in paths:
            with closing(sqlite3.connect(path)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                    )
                }
                self.assertEqual(tables, expected_tables)
                self.assertEqual(
                    connection.execute(
                        "SELECT value FROM settings WHERE key = 'name'"
                    ).fetchone()[0],
                    "Mi negocio",
                )

    def test_software_login_requires_server_enabled_plan(self):
        self.assertEqual(self.register().status_code, 201)

        response = self.client.post(
            "/api/auth/login",
            json={
                "email": "dueno@example.com",
                "password": "una-clave-segura",
                "software": "pos_comercio",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("plan", response.json["mensaje"])
        self.assertEqual(self.client.get("/api/cuenta").status_code, 401)
        with closing(sqlite3.connect(self.master_path)) as connection:
            branch_count = connection.execute(
                "SELECT COUNT(*) FROM sucursales"
            ).fetchone()[0]
        self.assertEqual(branch_count, 0)

    def test_software_login_provisions_isolated_store_databases_and_scoped_data(self):
        self.assertEqual(self.register().status_code, 201)
        self.activate_software("pos_restaurante", branch_limit=5)
        self.activate_software("pos_comercio", branch_limit=1)
        client = self.app.test_client()

        restaurant_login = client.post(
            "/api/auth/login",
            json={
                "email": "dueno@example.com",
                "password": "una-clave-segura",
                "software": "pos_restaurante",
            },
        )

        self.assertEqual(restaurant_login.status_code, 200)
        self.assertEqual(restaurant_login.json["software"]["clave"], "pos_restaurante")
        self.assertEqual(len(restaurant_login.json["sucursales"]), 5)
        self.assertTrue(
            all(branch["activa"] for branch in restaurant_login.json["sucursales"])
        )
        self.assertTrue(
            all("db_path" not in branch for branch in restaurant_login.json["sucursales"])
        )
        branch_ids = [branch["id"] for branch in restaurant_login.json["sucursales"]]
        with closing(sqlite3.connect(self.master_path)) as connection:
            paths = [
                row[0]
                for row in connection.execute(
                    "SELECT db_path FROM sucursales WHERE software_key = 'pos_restaurante' "
                    "ORDER BY numero"
                )
            ]
        self.assertEqual(len(set(paths)), 5)
        self.assertTrue(all(Path(path).is_file() for path in paths))
        expected_tables = {
            "menus", "settings", "categories", "products", "product_sizes",
            "orders", "order_items",
        }
        store_schemas = []
        for path in paths:
            with closing(sqlite3.connect(path)) as connection:
                store_schemas.append(
                    {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master "
                            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                        )
                    }
                )
        self.assertTrue(all(schema == expected_tables for schema in store_schemas))

        with closing(sqlite3.connect(paths[0])) as connection, connection:
            connection.execute(
                """
                INSERT INTO categories (id, menu_id, name)
                VALUES ('cat-1', 'menu-default', 'Comida')
                """
            )
            connection.execute(
                "INSERT INTO products (id, category_id, name) VALUES (?, ?, ?)",
                ("prod-1", "cat-1", "Producto restaurante"),
            )
            connection.execute(
                """
                INSERT INTO product_sizes (product_id, name, price)
                VALUES ('prod-1', 'Única', 30)
                """
            )
        data_response = client.get(
            f"/api/software/pos_restaurante/sucursales/{branch_ids[0]}/datos"
        )
        self.assertEqual(data_response.status_code, 200)
        self.assertEqual(
            data_response.json["datos"]["products"][0]["name"],
            "Producto restaurante",
        )

        commerce_login = client.post(
            "/api/auth/login",
            json={
                "email": "dueno@example.com",
                "password": "una-clave-segura",
                "software": "pos_comercio",
            },
        )
        self.assertEqual(commerce_login.status_code, 200)
        with closing(sqlite3.connect(self.master_path)) as connection:
            commerce_path = connection.execute(
                "SELECT db_path FROM sucursales WHERE software_key = 'pos_comercio'"
            ).fetchone()[0]
        self.assertNotIn(commerce_path, paths)

    def test_account_software_login_rejects_suspended_license_and_foreign_branch(self):
        self.assertEqual(self.register().status_code, 201)
        self.activate_software("pos_comercio")
        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            connection.execute(
                "UPDATE usuarios SET licencia_estado = 'suspendida' WHERE email = ?",
                ("dueno@example.com",),
            )

        suspended = self.app.test_client().post(
            "/api/auth/login",
            json={
                "email": "dueno@example.com",
                "password": "una-clave-segura",
                "software": "pos_comercio",
            },
        )
        self.assertEqual(suspended.status_code, 403)

        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            connection.execute(
                "UPDATE usuarios SET licencia_estado = 'activa' WHERE email = ?",
                ("dueno@example.com",),
            )
        owner_client = self.app.test_client()
        owner_login = owner_client.post(
            "/api/auth/login",
            json={
                "email": "dueno@example.com",
                "password": "una-clave-segura",
                "software": "pos_comercio",
            },
        )
        foreign_branch_id = owner_login.json["sucursales"][0]["id"]

        other_client = self.app.test_client()
        self.assertEqual(
            other_client.post(
                "/api/registro",
                json={
                    "nombre_negocio": "Otro negocio",
                    "email": "otro@example.com",
                    "password": "otra-clave-segura",
                },
            ).status_code,
            201,
        )
        self.activate_software("pos_comercio", email="otro@example.com")
        self.assertEqual(
            other_client.post(
                "/api/auth/login",
                json={
                    "email": "otro@example.com",
                    "password": "otra-clave-segura",
                    "software": "pos_comercio",
                },
            ).status_code,
            200,
        )
        self.assertEqual(
            other_client.get(
                f"/api/software/pos_comercio/sucursales/{foreign_branch_id}/datos"
            ).status_code,
            404,
        )

    def test_pos_owner_and_branch_users_use_their_selected_branch_database(self):
        self.assertEqual(self.register().status_code, 201)
        self.activate_software("pos_comercio", branch_limit=2)

        owner_login = self.client.post(
            "/api/pos/pos_comercio/login",
            json={"email": "dueno@example.com", "password": "una-clave-segura"},
        )

        self.assertEqual(owner_login.status_code, 200)
        owner_token = owner_login.json["token"]
        branches = owner_login.json["branches"]
        self.assertEqual(len(branches), 2)
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        first_branch = branches[0]
        second_branch = branches[1]
        first_api = (
            f"/api/pos/pos_comercio/sucursales/{first_branch['id']}/api"
        )
        second_api = (
            f"/api/pos/pos_comercio/sucursales/{second_branch['id']}/api"
        )

        users_response = self.client.get(f"{first_api}/users", headers=owner_headers)
        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(users_response.json[0]["username"], "admin")
        self.assertEqual(users_response.json[0]["role"], "Administrador")

        roles_response = self.client.get(f"{first_api}/roles", headers=owner_headers)
        self.assertEqual(roles_response.status_code, 200)
        admin_role_id = next(
            role["id"] for role in roles_response.json if role["name"] == "Administrador"
        )
        create_user_response = self.client.post(
            f"{first_api}/users",
            headers=owner_headers,
            json={
                "name": "Cajera sucursal 1",
                "username": "cajera1",
                "password": "clave-de-cajera",
                "role_id": admin_role_id,
            },
        )
        self.assertEqual(create_user_response.status_code, 201)

        branch_two_users = self.client.get(
            f"{second_api}/users", headers=owner_headers
        )
        self.assertEqual(branch_two_users.status_code, 200)
        self.assertEqual(
            [user["username"] for user in branch_two_users.json],
            ["admin"],
        )

        employee_login = self.client.post(
            f"/api/pos/pos_comercio/sucursales/{first_branch['id']}/login",
            json={"username": "cajera1", "password": "clave-de-cajera"},
        )
        self.assertEqual(employee_login.status_code, 200)
        employee_headers = {
            "Authorization": f"Bearer {employee_login.json['token']}"
        }
        wrong_branch = self.client.get(
            f"{second_api}/products", headers=employee_headers
        )
        self.assertEqual(wrong_branch.status_code, 403)
        correct_branch = self.client.get(
            f"{first_api}/products", headers=employee_headers
        )
        self.assertEqual(correct_branch.status_code, 200)

        self.assertEqual(
            self.client.get(f"{first_api}/../../app.py", headers=owner_headers).status_code,
            404,
        )

    def test_pos_owner_login_rejects_disabled_plan_and_license(self):
        self.assertEqual(self.register().status_code, 201)
        disabled_plan = self.client.post(
            "/api/pos/pos_comercio/login",
            json={"email": "dueno@example.com", "password": "una-clave-segura"},
        )
        self.assertEqual(disabled_plan.status_code, 403)

        self.activate_software("pos_comercio")
        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            connection.execute(
                "UPDATE usuarios SET licencia_estado = 'suspendida' WHERE email = ?",
                ("dueno@example.com",),
            )
        suspended_license = self.client.post(
            "/api/pos/pos_comercio/login",
            json={"email": "dueno@example.com", "password": "una-clave-segura"},
        )
        self.assertEqual(suspended_license.status_code, 403)

    def test_login_and_account_show_server_managed_license_status(self):
        self.assertEqual(self.register().status_code, 201)
        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            connection.execute(
                "UPDATE usuarios SET licencia_estado = 'suspendida' WHERE email = ?",
                ("dueno@example.com",),
            )

        profile_response = self.client.get("/api/cuenta")
        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(profile_response.json["cuenta"]["licencia_estado"], "suspendida")
        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            connection.execute(
                "UPDATE usuarios SET licencia_estado = 'baja' WHERE email = ?",
                ("dueno@example.com",),
            )
        self.assertEqual(
            self.client.get("/api/cuenta").json["cuenta"]["licencia_estado"],
            "baja",
        )

        another_client = self.app.test_client()
        login_response = another_client.post(
            "/api/auth/login",
            json={"email": "DUENO@example.com", "password": "una-clave-segura"},
        )
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(
            another_client.get("/api/cuenta").json["cuenta"]["nombre_negocio"],
            "Mi negocio",
        )
        self.assertEqual(
            another_client.post("/api/auth/logout").status_code,
            200,
        )
        self.assertEqual(another_client.get("/api/cuenta").status_code, 401)

    def test_login_rejects_wrong_password(self):
        self.assertEqual(self.register().status_code, 201)
        response = self.app.test_client().post(
            "/api/auth/login",
            json={"email": "dueno@example.com", "password": "incorrecta"},
        )
        self.assertEqual(response.status_code, 401)

    def test_password_reset_token_is_single_use_and_updates_password(self):
        self.assertEqual(self.register().status_code, 201)
        token = "one-time-reset-token"
        with closing(sqlite3.connect(self.master_path)) as connection, connection:
            user_id = connection.execute(
                "SELECT id FROM usuarios WHERE email = ?", ("dueno@example.com",)
            ).fetchone()[0]
            connection.execute(
                """
                INSERT INTO password_resets (token_hash, usuario_id, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    hashlib.sha256(token.encode()).hexdigest(),
                    user_id,
                    (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

        client = self.app.test_client()
        reset_response = client.post(
            "/api/auth/reset-password",
            json={"token": token, "password": "nueva-clave-segura"},
        )
        repeated_response = self.app.test_client().post(
            "/api/auth/reset-password",
            json={"token": token, "password": "otra-clave-segura"},
        )

        self.assertEqual(reset_response.status_code, 200)
        self.assertEqual(repeated_response.status_code, 400)
        login_response = self.app.test_client().post(
            "/api/auth/login",
            json={"email": "dueno@example.com", "password": "nueva-clave-segura"},
        )
        self.assertEqual(login_response.status_code, 200)

    def test_password_reset_sends_one_time_link_when_smtp_is_configured(self):
        self.assertEqual(self.register().status_code, 201)
        self.app.config.update(
            SMTP_HOST="smtp.example.com",
            SMTP_USERNAME="mailer",
            SMTP_PASSWORD="configured-secret",
            SMTP_FROM="Ozzvon <no-reply@example.com>",
            PUBLIC_BASE_URL="https://ozzvon.example.com",
        )
        with patch("app._send_password_reset_email") as send_email:
            response = self.app.test_client().post(
                "/api/auth/forgot-password",
                json={"email": "dueno@example.com"},
            )

        self.assertEqual(response.status_code, 202)
        reset_url = send_email.call_args.args[1]
        self.assertTrue(reset_url.startswith("https://ozzvon.example.com/#restablecer="))
        token = reset_url.partition("#restablecer=")[2]
        reset_response = self.app.test_client().post(
            "/api/auth/reset-password",
            json={"token": token, "password": "clave-recuperada"},
        )
        self.assertEqual(reset_response.status_code, 200)

    def test_password_reset_reports_missing_mail_configuration(self):
        response = self.app.test_client().post(
            "/api/auth/forgot-password",
            json={"email": "dueno@example.com"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("no está configurado", response.json["mensaje"])

    def test_google_auth_reports_missing_server_configuration(self):
        response = self.app.test_client().post(
            "/api/auth/google",
            json={"credential": "not-a-real-token"},
        )
        self.assertEqual(response.status_code, 503)

    def test_google_creates_account_only_for_verified_email(self):
        self.app.config["GOOGLE_CLIENT_ID"] = "web-client-id"
        claims = {
            "sub": "google-sub-123",
            "email": "google-owner@example.com",
            "email_verified": True,
        }
        client = self.app.test_client()
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            response = client.post(
                "/api/auth/google",
                json={
                    "credential": "verified-id-token",
                    "nombre_negocio": "Google negocio",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.get("/api/cuenta").json["cuenta"]["email"], claims["email"])
        with closing(sqlite3.connect(self.master_path)) as connection:
            user = connection.execute(
                "SELECT google_sub, licencia_estado FROM usuarios WHERE email = ?",
                (claims["email"],),
            ).fetchone()
        self.assertEqual(user, ("google-sub-123", "activa"))

    def test_google_rejects_unverified_email(self):
        self.app.config["GOOGLE_CLIENT_ID"] = "web-client-id"
        claims = {
            "sub": "google-sub-456",
            "email": "unverified@example.com",
            "email_verified": False,
        }
        with patch("google.oauth2.id_token.verify_oauth2_token", return_value=claims):
            response = self.app.test_client().post(
                "/api/auth/google",
                json={
                    "credential": "unverified-id-token",
                    "nombre_negocio": "Negocio",
                },
            )

        self.assertEqual(response.status_code, 401)
        with closing(sqlite3.connect(self.master_path)) as connection:
            count = connection.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        self.assertEqual(count, 0)

    def test_duplicate_email_returns_conflict_and_does_not_leave_tenant_database(self):
        first_response = self.register()
        tenant_files_before = set(self.tenant_directory.glob("*.db"))

        duplicate_response = self.register(email="DUENO@example.com")

        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(duplicate_response.status_code, 409)
        self.assertEqual(set(self.tenant_directory.glob("*.db")), tenant_files_before)

    def test_invalid_payloads_return_json_errors(self):
        invalid_email = self.register(email="no-es-correo")
        short_password = self.register(password="short")
        non_json = self.client.post(
            "/api/registro", data="nombre_negocio=prueba", content_type="text/plain"
        )

        self.assertEqual(invalid_email.status_code, 400)
        self.assertIn("mensaje", invalid_email.json)
        self.assertEqual(short_password.status_code, 400)
        self.assertEqual(non_json.status_code, 400)
        self.assertIn("mensaje", non_json.json)

    def test_confirmation_field_is_not_required_by_the_api(self):
        response = self.register(confirmar_password="different")

        self.assertEqual(response.status_code, 201)


if __name__ == "__main__":
    unittest.main()
