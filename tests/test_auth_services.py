"""Tests for auth service helpers that do not require external services."""

from __future__ import annotations

from auth_services import generate_temp_password, hash_password, is_valid_email, verify_password


def test_hash_password_roundtrip() -> None:
    password = "S3cure!Password"
    hashed = hash_password(password)

    assert hashed.startswith("pbkdf2_sha256$")
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_generate_temp_password_min_length() -> None:
    generated = generate_temp_password(8)

    assert len(generated) >= 10


def test_is_valid_email() -> None:
    assert is_valid_email("user@example.com")
    assert is_valid_email("user.name+tag@example.co.uk")
    assert not is_valid_email("bad-email")
    assert not is_valid_email("user@")
