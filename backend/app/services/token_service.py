import hashlib
import secrets
import string

TOKEN_ALPHABET = string.ascii_letters + string.digits
TOKEN_LENGTH = 48


def generate_token(length: int = TOKEN_LENGTH) -> str:
    if length < 32:
        raise ValueError("Token length must be at least 32 characters")
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(length))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token(token: str, token_hash: str) -> bool:
    return secrets.compare_digest(hash_token(token), token_hash)
