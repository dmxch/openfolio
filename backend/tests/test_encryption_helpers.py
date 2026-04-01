"""Tests for encryption_helpers: encrypt/decrypt/mask functions."""

import pytest

from services.encryption_helpers import encrypt_field, decrypt_field, decrypt_and_mask_iban


class TestEncryptField:
    def test_roundtrip(self):
        """Encrypted value decrypts back to original."""
        original = "CH93 0076 2011 6238 5295 7"
        encrypted = encrypt_field(original)
        assert encrypted != original
        assert decrypt_field(encrypted) == original

    def test_none_passthrough(self):
        assert encrypt_field(None) is None

    def test_empty_string_passthrough(self):
        assert encrypt_field("") == ""

    def test_unicode(self):
        original = "Zürich Kantonalbank — Sparkonto"
        encrypted = encrypt_field(original)
        assert decrypt_field(encrypted) == original

    def test_different_encryptions_differ(self):
        """Fernet uses unique IVs so same plaintext produces different ciphertext."""
        a = encrypt_field("test")
        b = encrypt_field("test")
        assert a != b  # Different nonces
        assert decrypt_field(a) == decrypt_field(b) == "test"


class TestDecryptField:
    def test_none_passthrough(self):
        assert decrypt_field(None) is None

    def test_empty_string_passthrough(self):
        assert decrypt_field("") == ""

    def test_legacy_plaintext_fallback(self):
        """Non-encrypted string returns as-is (legacy data migration)."""
        assert decrypt_field("just-plain-text") == "just-plain-text"

    def test_valid_encrypted(self):
        encrypted = encrypt_field("secret")
        assert decrypt_field(encrypted) == "secret"


class TestDecryptAndMaskIban:
    def test_masked_output(self):
        iban = "CH93 0076 2011 6238 5295 7"
        encrypted = encrypt_field(iban)
        masked = decrypt_and_mask_iban(encrypted)
        assert masked.endswith("95 7")
        assert masked.startswith("•")
        assert "CH93" not in masked

    def test_none_returns_none(self):
        assert decrypt_and_mask_iban(None) is None

    def test_empty_returns_none(self):
        assert decrypt_and_mask_iban("") is None

    def test_short_value(self):
        """Values <= 4 chars returned fully visible."""
        encrypted = encrypt_field("AB12")
        result = decrypt_and_mask_iban(encrypted)
        assert result == "AB12"

    def test_legacy_plaintext_iban(self):
        """Unencrypted IBANs (legacy) are still masked."""
        masked = decrypt_and_mask_iban("CH1234567890")
        assert masked.endswith("7890")
        assert masked.startswith("•")
