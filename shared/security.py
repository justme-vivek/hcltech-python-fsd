import base64, hashlib, hmac, json, os, time
from fastapi import Header, HTTPException

_SECRET_DEFAULT = "local-development-secret-change-me"
ISSUER = os.getenv("JWT_ISSUER", "ecommerce-microservices")
AUDIENCE = os.getenv("JWT_AUDIENCE", "ecommerce-api")

def _secret() -> str:
    return os.getenv("JWT_SECRET", _SECRET_DEFAULT)

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return "scrypt$" + _b64(salt) + "$" + _b64(digest)

def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(actual, _unb64(expected))
    except Exception:
        return False

def create_token(user_id: str, role: str, minutes: int = 30) -> str:
    now = int(time.time())
    header = _b64(json.dumps({"alg":"HS256","typ":"JWT"}, separators=(",",":")).encode())
    payload = _b64(json.dumps({"sub":user_id,"role":role,"iat":now,"exp":now+minutes*60,
                               "iss":ISSUER,"aud":AUDIENCE}, separators=(",",":")).encode())
    body = header + "." + payload
    sig = _b64(hmac.new(_secret().encode(), body.encode(), hashlib.sha256).digest())
    return body + "." + sig

def decode_token(token: str) -> dict:
    try:
        h, p, s = token.split(".")
        header = json.loads(_unb64(h))
        if header.get("alg") != "HS256" or header.get("typ") != "JWT":
            raise ValueError("header")
        body = h + "." + p
        expected = _b64(hmac.new(_secret().encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(s, expected):
            raise ValueError("signature")
        data = json.loads(_unb64(p))
        if data["exp"] <= int(time.time()) or data["iss"] != ISSUER or data["aud"] != AUDIENCE:
            raise ValueError("claims")
        if not data.get("sub") or data.get("role") not in ("customer", "admin"):
            raise ValueError("subject")
        return data
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired access token")

def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    return decode_token(authorization[7:])

def require_admin(user: dict) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
