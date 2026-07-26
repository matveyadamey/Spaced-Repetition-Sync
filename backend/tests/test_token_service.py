from app.services.token_service import generate_token, hash_token, verify_token


def test_generate_token_length_and_charset():
    token = generate_token()
    assert len(token) >= 32
    assert token.isalnum()


def test_hash_is_sha256_hex():
    token = "a" * 32
    digest = hash_token(token)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_verify_token():
    token = generate_token()
    digest = hash_token(token)
    assert verify_token(token, digest)
    assert not verify_token(token + "x", digest)


def test_tokens_are_unique():
    tokens = {generate_token() for _ in range(50)}
    assert len(tokens) == 50
