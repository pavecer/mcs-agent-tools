#!/usr/bin/env python3
"""Reset (drop and recreate) the authentication database schema."""

from __future__ import annotations

import os
import sys

# Make sure we can import auth_services
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from auth_services import _db_connect, is_db_auth_enabled


def reset_schema() -> None:
    """Drop existing auth tables and recreate them."""
    if not is_db_auth_enabled():
        print("ERROR: AUTH_DB_DSN is not configured. Cannot reset schema.")
        return

    print("Connecting to database...")
    try:
        with _db_connect() as conn:
            with conn.cursor() as cur:
                print("Dropping existing tables...")
                drop_sql = """
                DROP TABLE IF EXISTS auth_audit_events CASCADE;
                DROP TABLE IF EXISTS auth_account_requests CASCADE;
                DROP TABLE IF EXISTS auth_users CASCADE;
                """
                cur.execute(drop_sql)
                print("Tables dropped.")

            conn.commit()

        print("Recreating schema...")
        with _db_connect() as conn:
            with conn.cursor() as cur:
                create_sql = """
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
                cur.execute(create_sql)
                print("Schema created.")

            conn.commit()

    except Exception as exc:
        print(f"Error: {exc}")
        sys.exit(1)

    print("Auth schema reset complete.")


if __name__ == "__main__":
    reset_schema()
