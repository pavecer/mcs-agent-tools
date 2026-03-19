"""Simplified authentication and user management services for DB-backed login."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import re
import secrets
from dataclasses import dataclass
from typing import Any

from env_config import read_env_config
from loguru import logger

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


@dataclass
class AuthResult:
    """Authentication result for DB-backed users."""

    success: bool
    requires_password_reset: bool = False
    message: str = ""


class AuthConfigError(RuntimeError):
    """Raised when auth configuration is missing or invalid."""


def is_db_auth_enabled() -> bool:
    """Whether DB-backed authentication is configured."""
    return bool(read_env_config().auth_db_dsn)


def get_admin_email() -> str:
    """Configured admin email for user management."""
    return read_env_config().auth_admin_email


def is_admin_login_enabled() -> bool:
    """Whether dedicated admin login credentials are configured via env vars."""
    env = read_env_config()
    return bool(env.auth_admin_email and env.auth_admin_password)


def authenticate_env_admin(email: str, password: str) -> AuthResult:
    """Validate dedicated admin credentials configured via env vars."""
    env = read_env_config()
    admin_email = env.auth_admin_email
    admin_password = env.auth_admin_password
    normalized = (email or "").strip().lower()
    if not admin_email or not admin_password:
        return AuthResult(success=False, message="")
    if not hmac.compare_digest(normalized, admin_email):
        return AuthResult(success=False, message="")
    if hmac.compare_digest(password or "", admin_password):
        return AuthResult(success=True)
    return AuthResult(success=False, message="Invalid username or password.")


def is_valid_email(email: str) -> bool:
    """Lightweight email syntax validation."""
    return bool(_EMAIL_RE.fullmatch((email or "").strip()))


def hash_password(password: str, *, iterations: int = 210_000) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and random salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against PBKDF2 hash."""
    try:
        algorithm, iterations_raw, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64.encode("utf-8"))
        expected = base64.b64decode(digest_b64.encode("utf-8"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def generate_temp_password(length: int = 14) -> str:
    """Generate a secure temporary password."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(max(10, length)))


def _db_connect():
    dsn = read_env_config().auth_db_dsn
    if not dsn:
        raise AuthConfigError("AUTH_DB_DSN is not configured.")
    try:
        psycopg = importlib.import_module("psycopg")
    except ImportError as exc:
        raise AuthConfigError("psycopg is not installed. Run dependency sync.") from exc
    return psycopg.connect(dsn)


def ensure_auth_schema() -> None:
    """Create the auth_users table needed for DB-backed authentication."""
    if not is_db_auth_enabled():
        return

    ddl = """
    CREATE TABLE IF NOT EXISTS auth_users (
        email TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE,
        must_reset_password BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """

    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
            # Migration path for existing databases created before must_reset_password existed.
            cur.execute(
                """
                ALTER TABLE auth_users
                ADD COLUMN IF NOT EXISTS must_reset_password BOOLEAN NOT NULL DEFAULT FALSE
                """
            )
        conn.commit()


def _send_email(*, recipient_email: str, subject: str, plain_text: str, html_text: str) -> None:
    """Send an email through Azure Communication Services Email."""
    env = read_env_config()
    connection_string = env.acs_email_connection_string
    sender = env.acs_email_sender
    if not connection_string or not sender:
        raise AuthConfigError("ACS email configuration is missing.")

    try:
        email_module = importlib.import_module("azure.communication.email")
        email_client_cls = getattr(email_module, "EmailClient")
    except ImportError as exc:
        raise AuthConfigError("azure-communication-email package is not installed.") from exc

    message: dict[str, Any] = {
        "senderAddress": sender,
        "content": {
            "subject": subject,
            "plainText": plain_text,
            "html": html_text,
        },
        "recipients": {
            "to": [{"address": recipient_email}],
        },
    }

    client = email_client_cls.from_connection_string(connection_string)
    poller = client.begin_send(message)
    result = poller.result()
    status = (result.get("status") or "").lower()
    if status not in {"queued", "outfordelivery", "success"}:
        raise RuntimeError(f"ACS send operation failed with status: {status}")


def send_generated_credentials(email: str, temp_password: str) -> None:
    """Send first-login credentials and reset instruction to a newly created user."""
    subject = "Your PP Agent Toolkit account is ready"
    plain_text = (
        "Your account was created by an administrator.\n\n"
        f"Username: {email}\n"
        f"Temporary password: {temp_password}\n\n"
        "You must change your password at first sign-in."
    )
    html_text = (
        "<p>Your account was created by an administrator.</p>"
        f"<p><strong>Username:</strong> {email}<br/>"
        f"<strong>Temporary password:</strong> {temp_password}</p>"
        "<p>You must change your password at first sign-in.</p>"
    )
    _send_email(recipient_email=email, subject=subject, plain_text=plain_text, html_text=html_text)


def list_users() -> list[dict]:
    """List all users from the database."""
    if not is_db_auth_enabled():
        return []
    ensure_auth_schema()

    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT email, is_active, must_reset_password, created_at, updated_at
                    FROM auth_users
                    ORDER BY created_at DESC
                    """
                )
                rows = cur.fetchall()
                return [
                    {
                        "email": row[0],
                        "is_active": row[1],
                        "must_reset_password": row[2],
                        "created_at": row[3].isoformat() if row[3] else None,
                        "updated_at": row[4].isoformat() if row[4] else None,
                    }
                    for row in rows
                ]
    except Exception as exc:
        logger.exception("Failed to list users: {}", exc)
        return []


def add_user(email: str, password: str = "") -> tuple[bool, str, str]:
    """
    Add a new user account.
    
    Returns:
        (success: bool, message: str, generated_password: str or empty if custom password used)
    """
    normalized = (email or "").strip().lower()
    if not is_valid_email(normalized):
        return False, "Enter a valid email address.", ""
    if not is_db_auth_enabled():
        return False, "User management is not configured.", ""

    ensure_auth_schema()

    # Use provided password or generate temporary one
    pwd_to_use = (password or "").strip()
    if not pwd_to_use:
        pwd_to_use = generate_temp_password()
        generated = True
    else:
        generated = False

    password_hash = hash_password(pwd_to_use)
    must_reset_password = bool(generated)

    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth_users (email, password_hash, is_active, must_reset_password)
                    VALUES (%s, %s, TRUE, %s)
                    ON CONFLICT (email)
                    DO UPDATE SET password_hash = EXCLUDED.password_hash,
                                  is_active = TRUE,
                                  must_reset_password = EXCLUDED.must_reset_password,
                                  updated_at = NOW()
                    """,
                    (normalized, password_hash, must_reset_password),
                )
            conn.commit()
        msg = f"User {normalized} added successfully."
        if generated:
            try:
                send_generated_credentials(normalized, pwd_to_use)
                return True, f"{msg} Credentials were emailed to the user.", ""
            except Exception:
                logger.exception("Failed to send generated credentials for {}", normalized)
                return (
                    True,
                    f"{msg} Email delivery failed, share the temporary password manually.",
                    pwd_to_use,
                )
        return True, msg, ""
    except Exception as exc:
        logger.exception("Failed to add user {}", normalized)
        return False, f"Failed to add user: {exc}", ""


def delete_user(email: str) -> tuple[bool, str]:
    """Delete a user account by marking it inactive."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return False, "Email is required."
    if not is_db_auth_enabled():
        return False, "User management is not configured."

    ensure_auth_schema()

    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth_users
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE email = %s
                    """,
                    (normalized,),
                )
                if cur.rowcount == 0:
                    return False, f"User {normalized} not found."
            conn.commit()
        return True, f"User {normalized} deleted successfully."
    except Exception as exc:
        logger.exception("Failed to delete user {}", normalized)
        return False, f"Failed to delete user: {exc}"


def authenticate_db_user(email: str, password: str) -> AuthResult:
    """Validate a DB-backed user account."""
    normalized = (email or "").strip().lower()
    if not normalized or not password:
        return AuthResult(success=False, message="Invalid username or password.")
    if not is_db_auth_enabled():
        return AuthResult(success=False, message="")

    ensure_auth_schema()

    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT password_hash, is_active, must_reset_password FROM auth_users WHERE email = %s",
                    (normalized,),
                )
                row = cur.fetchone()
                if not row:
                    return AuthResult(success=False, message="")
                password_hash, is_active, must_reset_password = row
                if not is_active:
                    return AuthResult(success=False, message="Account is not active.")
                if not verify_password(password, password_hash):
                    return AuthResult(success=False, message="Invalid username or password.")
    except Exception as exc:
        logger.exception("Database authentication failed: {}", exc)
        return AuthResult(success=False, message="")

    return AuthResult(success=True, requires_password_reset=bool(must_reset_password), message="")


def reset_user_password(email: str, new_password: str) -> tuple[bool, str]:
    """Set a new password for an existing user and clear first-login reset flag."""
    normalized = (email or "").strip().lower()
    if not normalized:
        return False, "Email is required."
    if not new_password or len(new_password) < 10:
        return False, "Password must be at least 10 characters long."
    if not is_db_auth_enabled():
        return False, "User management is not configured."

    ensure_auth_schema()
    password_hash = hash_password(new_password)
    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE auth_users
                    SET password_hash = %s,
                        must_reset_password = FALSE,
                        updated_at = NOW()
                    WHERE email = %s AND is_active = TRUE
                    """,
                    (password_hash, normalized),
                )
                if cur.rowcount == 0:
                    return False, "User account not found or inactive."
            conn.commit()
        return True, "Password updated successfully."
    except Exception as exc:
        logger.exception("Failed to reset password for {}", normalized)
        return False, f"Failed to reset password: {exc}"
