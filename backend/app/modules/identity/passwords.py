"""Password hashing helpers without storing or logging plaintext secrets."""

from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import pbkdf2_hmac
from hmac import compare_digest
from secrets import token_bytes

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 210_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    """Return a salted PBKDF2-SHA256 representation suitable for database storage."""
    salt = token_bytes(SALT_BYTES)
    digest = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return "$".join(
        (
            ALGORITHM,
            str(ITERATIONS),
            urlsafe_b64encode(salt).decode("ascii"),
            urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str | None) -> bool:
    """Verify a password in constant time; malformed hashes are rejected."""
    if not encoded:
        return False
    try:
        algorithm, iterations, salt_value, digest_value = encoded.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        salt = urlsafe_b64decode(salt_value.encode("ascii"))
        expected = urlsafe_b64decode(digest_value.encode("ascii"))
        actual = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except (ValueError, UnicodeError):
        return False
    return compare_digest(actual, expected)
