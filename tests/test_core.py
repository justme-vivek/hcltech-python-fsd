import os, tempfile, time, json
os.environ["DATABASE_DIR"] = tempfile.mkdtemp()
os.environ["JWT_SECRET"] = "test-secret-with-enough-entropy"
from shared.security import hash_password, verify_password, create_token, decode_token
from shared.resilience import CircuitBreaker, State
import pytest

def test_password_hashing_and_verification():
    encoded=hash_password("correct-horse-battery")
    assert encoded != "correct-horse-battery"
    assert verify_password("correct-horse-battery", encoded)
    assert not verify_password("wrong", encoded)

def test_jwt_claims_and_expiry():
    token=create_token("user-1","customer",1)
    assert decode_token(token)["sub"] == "user-1"

def test_jwt_rejects_non_hs256_header():
    token=create_token("user-1","customer",1)
    header, payload, signature = token.split(".")
    replacement = __import__("base64").urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(Exception):
        decode_token(replacement + "." + payload + "." + signature)

def test_circuit_breaker_open_and_recover():
    cb=CircuitBreaker(threshold=2,reset_seconds=0)
    cb.failure(); cb.failure()
    assert cb.state == State.OPEN
    assert cb.allow()
    assert cb.state == State.HALF_OPEN
    cb.success()
    assert cb.state == State.CLOSED
