"""Local encryption boundary for write-only administrative secrets."""

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import PROJECT_ROOT

KEY_PATH = PROJECT_ROOT / ".local-secrets" / "ai-provider.key"


def _cipher() -> Fernet:
    if KEY_PATH.exists():
        key = KEY_PATH.read_bytes().strip()
    else:
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        KEY_PATH.write_bytes(key)
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    return _cipher().encrypt(api_key.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted: str | None) -> str:
    if not encrypted:
        return ""
    try:
        return _cipher().decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as cause:
        raise RuntimeError("Сохранённый API key не удалось расшифровать") from cause
