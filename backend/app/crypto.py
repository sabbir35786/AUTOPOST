import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from app.config import FACEBOOK_TOKEN_ENCRYPTION_KEY, SECRET_KEY

logger = logging.getLogger(__name__)


def _fernet() -> Fernet:
    raw_key = FACEBOOK_TOKEN_ENCRYPTION_KEY or SECRET_KEY
    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(encrypted_token: str) -> str | None:
    try:
        return _fernet().decrypt(encrypted_token.encode("utf-8")).decode("utf-8")
    except Exception:
        logger.exception(
            "Failed to decrypt Facebook token — FACEBOOK_TOKEN_ENCRYPTION_KEY "
            "or SECRET_KEY may have changed since the token was stored"
        )
        return None
