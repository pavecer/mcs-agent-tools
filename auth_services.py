"""Authentication and account-request services for DB-backed login flow."""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from typing import Any
from urllib import parse, request

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
    return bool(os.getenv("AUTH_DB_DSN", "").strip())


def is_signup_enabled() -> bool:
    """Whether account request flow is enabled."""
    raw = os.getenv("AUTH_SIGNUP_ENABLED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def get_admin_email() -> str:
    """Configured admin email address used for approval workflow and notifications."""
    return os.getenv("AUTH_ADMIN_EMAIL", "").strip().lower()


def is_admin_login_enabled() -> bool:
    """Whether dedicated admin login credentials are configured via env vars."""
    return bool(get_admin_email() and os.getenv("AUTH_ADMIN_PASSWORD", "").strip())


def authenticate_env_admin(email: str, password: str) -> AuthResult:
    """Validate dedicated admin credentials configured via env vars."""
    admin_email = get_admin_email()
    admin_password = os.getenv("AUTH_ADMIN_PASSWORD", "").strip()
    normalized = (email or "").strip().lower()
    if not admin_email or not admin_password:
        return AuthResult(success=False, message="")
    if not hmac.compare_digest(normalized, admin_email):
        return AuthResult(success=False, message="")
    if hmac.compare_digest(password or "", admin_password):
        return AuthResult(success=True)
    return AuthResult(success=False, message="Invalid username or password.")


def is_valid_email(email: str) -> bool:
    """Lightweight email syntax validation for signup requests."""
    return bool(_EMAIL_RE.fullmatch((email or "").strip()))


def hash_password(password: str, *, iterations: int = 210_000) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and random salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against PBKDF2 hash; supports legacy plain value mismatch safely."""
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
    """Generate a temporary password with a broad character set."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@$%&*"
    return "".join(secrets.choice(alphabet) for _ in range(max(10, length)))


def _db_connect():
    dsn = os.getenv("AUTH_DB_DSN", "").strip()
    if not dsn:
        raise AuthConfigError("AUTH_DB_DSN is not configured.")
    try:
        psycopg = importlib.import_module("psycopg")
    except ImportError as exc:
        raise AuthConfigError("psycopg is not installed. Run dependency sync.") from exc
    return psycopg.connect(dsn)


def _app_base_url() -> str:
    """Public app base URL used in email links."""
    configured = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    port = (os.getenv("FRONTEND_PORT", "3000") or "3000").strip()
    return f"http://localhost:{port}"


def ensure_auth_schema() -> None:
    """Create DB objects needed for account requests and DB-backed authentication."""
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

    CREATE TABLE IF NOT EXISTS auth_account_requests (
        request_id TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        status TEXT NOT NULL,
        captcha_provider TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        reviewed_at TIMESTAMPTZ,
        reviewed_by TEXT,
        review_note TEXT
    );

    CREATE TABLE IF NOT EXISTS auth_audit_events (
        event_id BIGSERIAL PRIMARY KEY,
        event_type TEXT NOT NULL,
        email TEXT,
        details TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE INDEX IF NOT EXISTS idx_auth_account_requests_email
        ON auth_account_requests (email);
    CREATE INDEX IF NOT EXISTS idx_auth_account_requests_status
        ON auth_account_requests (status);
    """

    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(ddl)
        conn.commit()


def verify_turnstile(token: str, remote_ip: str | None = None) -> tuple[bool, str]:
    """Verify Cloudflare Turnstile token server-side."""
    secret = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        return False, "Captcha is not configured."
    if not token.strip():
        return False, "Captcha verification is required."

    payload: dict[str, str] = {
        "secret": secret,
        "response": token.strip(),
    }
    if remote_ip:
        payload["remoteip"] = remote_ip

    data = parse.urlencode(payload).encode("utf-8")
    req = request.Request(
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("success"):
                return True, ""
            return False, "Captcha verification failed."
    except Exception as exc:
        logger.warning("Turnstile verification call failed: {}", exc)
        return False, "Captcha verification is temporarily unavailable."


def create_account_request(email: str, captcha_provider: str = "turnstile") -> tuple[bool, str]:
    """Persist an account request as pending approval."""
    normalized = (email or "").strip().lower()
    if not is_valid_email(normalized):
        return False, "Enter a valid email address."
    if not is_db_auth_enabled():
        return False, "Signup storage is not configured."

    ensure_auth_schema()
    request_id = secrets.token_urlsafe(18)

    created_request = False

    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM auth_users WHERE email = %s",
                (normalized,),
            )
            if cur.fetchone():
                cur.execute(
                    "INSERT INTO auth_audit_events (event_type, email, details) VALUES (%s, %s, %s)",
                    ("signup_duplicate_existing_user", normalized, "Existing user requested signup."),
                )
                conn.commit()
                return True, "If your request is approved, credentials will be sent by email."

            cur.execute(
                "SELECT 1 FROM auth_account_requests WHERE email = %s AND status = 'pending'",
                (normalized,),
            )
            if cur.fetchone():
                conn.commit()
                return True, "If your request is approved, credentials will be sent by email."

            cur.execute(
                """
                INSERT INTO auth_account_requests (request_id, email, status, captcha_provider)
                VALUES (%s, %s, 'pending', %s)
                """,
                (request_id, normalized, captcha_provider),
            )
            created_request = True
            cur.execute(
                "INSERT INTO auth_audit_events (event_type, email, details) VALUES (%s, %s, %s)",
                ("signup_requested", normalized, f"request_id={request_id}"),
            )
        conn.commit()

    if created_request:
        try:
            send_admin_request_notification(requester_email=normalized, request_id=request_id)
            with _db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO auth_audit_events (event_type, email, details) VALUES (%s, %s, %s)",
                        ("signup_admin_notified", normalized, f"request_id={request_id};admin={get_admin_email()}"),
                    )
                conn.commit()
        except Exception as exc:
            logger.exception("Failed sending admin signup notification for {}", normalized)
            with _db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO auth_audit_events (event_type, email, details) VALUES (%s, %s, %s)",
                        ("signup_admin_notify_failed", normalized, f"request_id={request_id};error={exc}"),
                    )
                conn.commit()

    return True, "If your request is approved, credentials will be sent by email."


def authenticate_db_user(email: str, password: str) -> AuthResult:
    """Validate a DB-backed user account."""
    normalized = (email or "").strip().lower()
    if not normalized or not password:
        return AuthResult(success=False, message="Invalid username or password.")
    if not is_db_auth_enabled():
        return AuthResult(success=False, message="")

    ensure_auth_schema()

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
                return AuthResult(success=False, message="Account is not active yet.")
            if not verify_password(password, password_hash):
                return AuthResult(success=False, message="Invalid username or password.")

            cur.execute(
                "INSERT INTO auth_audit_events (event_type, email, details) VALUES (%s, %s, %s)",
                ("login_success", normalized, "DB auth login."),
            )
        conn.commit()

    return AuthResult(success=True, requires_password_reset=bool(must_reset_password), message="")


def _send_acs_email(*, recipient_email: str, subject: str, plain_text: str, html_text: str) -> None:
    """Send an email via Azure Communication Services Email."""
    connection_string = os.getenv("ACS_EMAIL_CONNECTION_STRING", "").strip()
    sender = os.getenv("ACS_EMAIL_SENDER", "").strip()
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


def send_signup_credentials(email: str, temp_password: str) -> None:
    """Send temporary credentials through Azure Communication Services Email."""
    subject = "Your PP Agent Toolkit access request was approved"
    plain_text = (
        "Your account request has been approved.\n\n"
        f"Username: {email}\n"
        f"Temporary password: {temp_password}\n\n"
        "Sign in and change this password immediately."
    )

    html_text = (
        "<p>Your account request has been approved.</p>"
        f"<p><strong>Username:</strong> {email}<br/>"
        f"<strong>Temporary password:</strong> {temp_password}</p>"
        "<p>Sign in and change this password immediately.</p>"
    )
    _send_acs_email(recipient_email=email, subject=subject, plain_text=plain_text, html_text=html_text)


def send_admin_request_notification(requester_email: str, request_id: str) -> None:
    """Notify the configured admin that a new account request is pending."""
    admin_email = get_admin_email()
    if not admin_email:
        raise AuthConfigError("AUTH_ADMIN_EMAIL is not configured.")

    approval_url = f"{_app_base_url()}/request-approval?{parse.urlencode({'request_id': request_id})}"
    subject = "New PP Agent Toolkit account request pending approval"
    plain_text = (
        "A new account request was submitted.\n\n"
        f"Requester: {requester_email}\n"
        f"Request ID: {request_id}\n"
        f"Approval page: {approval_url}\n"
    )
    html_text = (
        "<p>A new account request was submitted.</p>"
        f"<p><strong>Requester:</strong> {requester_email}<br/>"
        f"<strong>Request ID:</strong> {request_id}</p>"
        f"<p><a href=\"{approval_url}\">Open approval page</a></p>"
    )
    _send_acs_email(recipient_email=admin_email, subject=subject, plain_text=plain_text, html_text=html_text)


def approve_account_request(request_id: str, reviewer: str) -> tuple[bool, str]:
    """Approve pending account request, provision temp password, and send ACS email."""
    if not is_db_auth_enabled():
        return False, "Signup storage is not configured."
    ensure_auth_schema()

    rid = (request_id or "").strip()
    if not rid:
        return False, "Request ID is required."

    with _db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, status FROM auth_account_requests WHERE request_id = %s",
                (rid,),
            )
            row = cur.fetchone()
            if not row:
                return False, "Request not found."
            email, status = row
            if status != "pending":
                return False, "Only pending requests can be approved."

            temp_password = generate_temp_password(
                int(os.getenv("TEMP_PASSWORD_LENGTH", "14") or "14")
            )
            password_hash = hash_password(temp_password)

            cur.execute(
                """
                INSERT INTO auth_users (email, password_hash, is_active, must_reset_password)
                VALUES (%s, %s, TRUE, TRUE)
                ON CONFLICT (email)
                DO UPDATE SET password_hash = EXCLUDED.password_hash,
                              is_active = TRUE,
                              must_reset_password = TRUE,
                              updated_at = NOW()
                """,
                (email, password_hash),
            )
            cur.execute(
                """
                UPDATE auth_account_requests
                SET status = 'approved',
                    reviewed_at = NOW(),
                    reviewed_by = %s,
                    review_note = %s
                WHERE request_id = %s
                """,
                (reviewer, "Approved and credentials provisioned.", rid),
            )
            cur.execute(
                "INSERT INTO auth_audit_events (event_type, email, details) VALUES (%s, %s, %s)",
                ("signup_approved", email, f"request_id={rid};reviewer={reviewer}"),
            )
        conn.commit()

    try:
        send_signup_credentials(email, temp_password)
    except Exception as exc:
        logger.exception("Failed sending signup credentials for {}", email)
        with _db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO auth_audit_events (event_type, email, details) VALUES (%s, %s, %s)",
                    ("signup_email_failed", email, str(exc)),
                )
            conn.commit()
        return False, "Request approved, but sending email failed."

    return True, "Request approved and temporary credentials emailed."