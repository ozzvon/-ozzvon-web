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

    def test_master_database_migrates_existing_user_table(self):
        legacy_path = Path(self.temp_directory.name) / "legacy.db"
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
        self.assertIsNotNone(legacy_app)

    def test_register_creates_hashed_user_and_pos_tables(self):
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
        self.assertTrue(tenant_path.is_file())
        with closing(sqlite3.connect(tenant_path)) as connection, connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertTrue({"productos", "clientes", "ventas"}.issubset(tables))

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
