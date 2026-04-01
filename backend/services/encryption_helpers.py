"""Centralized encryption/decryption helpers for PII fields.

Used across all API routers that handle encrypted data (portfolio, positions,
analysis, precious_metals, real_estate, private_equity_service).
"""

import logging

from services.auth_service import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)


def encrypt_field(value: str | None) -> str | None:
    """Encrypt a field value, returning None/empty for falsy values."""
    if not value:
        return value
    return encrypt_value(value)


def decrypt_field(value: str | None) -> str | None:
    """Decrypt an encrypted field, falling back to plaintext for legacy data."""
    if not value:
        return value
    try:
        return decrypt_value(value)
    except Exception:
        logger.debug("Decryption failed, treating as legacy plaintext")
        return value  # Legacy plaintext


def decrypt_and_mask_iban(encrypted_iban: str | None) -> str | None:
    """Decrypt an encrypted IBAN and return only the last 4 characters visible."""
    import logging
    logger = logging.getLogger(__name__)

    if not encrypted_iban:
        return None
    try:
        plain = decrypt_value(encrypted_iban)
        if len(plain) > 4:
            return "•" * (len(plain) - 4) + plain[-4:]
        return plain
    except Exception as e:
        # If decryption fails, it may be a plaintext IBAN (legacy data)
        logger.debug(f"IBAN decryption failed, treating as plaintext: {e}")
        if len(encrypted_iban) > 4:
            return "•" * (len(encrypted_iban) - 4) + encrypted_iban[-4:]
        return encrypted_iban
