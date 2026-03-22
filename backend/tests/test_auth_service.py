"""Tests for services/auth_service.py — password, JWT, TOTP, backup codes."""

import pytest
from services.auth_service import (
    hash_password,
    verify_password,
    validate_password,
    create_access_token,
    decode_access_token,
    create_refresh_token,
    hash_refresh_token,
    generate_backup_codes,
    hash_backup_code,
    encrypt_value,
    decrypt_value,
    encrypt_totp_secret,
    decrypt_totp_secret,
    generate_totp_secret,
    verify_totp,
    escape_like,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "TestPassword1"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)

    def test_wrong_password(self):
        hashed = hash_password("Correct1")
        assert not verify_password("Wrong1", hashed)

    def test_different_hashes(self):
        h1 = hash_password("Same1")
        h2 = hash_password("Same1")
        assert h1 != h2  # bcrypt uses random salt


class TestPasswordValidation:
    def test_valid_password(self):
        assert validate_password("GoodPass1!xyz") == []

    def test_too_short(self):
        errors = validate_password("Ab1!short")
        assert any("12" in e for e in errors)

    def test_no_uppercase(self):
        errors = validate_password("lowercase1")
        assert any("Grossbuchstabe" in e for e in errors)

    def test_no_digit(self):
        errors = validate_password("NoDigitHere")
        assert any("Zahl" in e for e in errors)

    def test_too_long(self):
        errors = validate_password("A1" + "a" * 127)
        assert any("128" in e for e in errors)


class TestJWT:
    def test_create_and_decode(self):
        token, expires_in = create_access_token("user-123", "test@example.com")
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["email"] == "test@example.com"
        assert expires_in == 900  # 15 minutes

    def test_invalid_token(self):
        assert decode_access_token("invalid-token") is None

    def test_refresh_token_generation(self):
        raw, hashed, expires_at = create_refresh_token()
        assert len(raw) > 20
        assert hashed == hash_refresh_token(raw)
        assert expires_at is not None


class TestEncryption:
    def test_encrypt_decrypt_value(self):
        plain = "my-secret-api-key"
        encrypted = encrypt_value(plain)
        assert encrypted != plain
        assert decrypt_value(encrypted) == plain

    def test_encrypt_decrypt_totp(self):
        secret = generate_totp_secret()
        encrypted = encrypt_totp_secret(secret)
        assert decrypt_totp_secret(encrypted) == secret


class TestTOTP:
    def test_verify_valid_code(self):
        import pyotp
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert verify_totp(secret, code)

    def test_verify_invalid_code(self):
        secret = generate_totp_secret()
        assert not verify_totp(secret, "000000")


class TestBackupCodes:
    def test_generate_format(self):
        codes = generate_backup_codes()
        assert len(codes) == 8
        for code in codes:
            assert len(code) == 17
            assert code[8] == "-"
            assert code.replace("-", "").isalnum()

    def test_generate_unique(self):
        codes = generate_backup_codes()
        assert len(set(codes)) == len(codes)

    def test_hash_normalization(self):
        # hash_backup_code normalizes: strip + upper + remove dashes
        # All these variants should produce a hash that verifies the same normalized form
        code = "ABF19559-AF17CDD3"
        normalized = code.strip().upper().replace("-", "")
        h1 = hash_backup_code(code)                    # with dash
        h2 = hash_backup_code("abf19559-af17cdd3")     # lowercase
        h3 = hash_backup_code(" ABF19559AF17CDD3 ")    # whitespace, no dash
        assert verify_password(normalized, h1)
        assert verify_password(normalized, h2)
        assert verify_password(normalized, h3)

    def test_custom_count(self):
        codes = generate_backup_codes(count=4)
        assert len(codes) == 4


class TestEscapeLike:
    def test_escape_percent(self):
        assert escape_like("100%") == "100\\%"

    def test_escape_underscore(self):
        assert escape_like("a_b") == "a\\_b"

    def test_no_escape_needed(self):
        assert escape_like("normal") == "normal"
