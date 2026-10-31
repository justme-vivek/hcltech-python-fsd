from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from shared.storage import init_db, connect
from shared.security import hash_password, verify_password, create_token, current_user
from shared.rate_limit import check_rate_limit

app = FastAPI(title="Auth Service", version="1.0.0")
init_db("auth", """CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'customer', created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")

class Register(BaseModel):
    email: str
    password: str = Field(min_length=10)
class Login(BaseModel):
    email: str
    password: str

@app.get("/health/live")
def live(): return {"status":"alive","service":"auth-service"}
@app.get("/health/ready")
def ready():
    with connect("auth") as db: db.execute("SELECT 1")
    return {"status":"ready"}

@app.post("/api/v1/auth/register", status_code=201)
def register(body: Register):
    check_rate_limit("auth-register:"+body.email, 5, 60)
    import uuid
    try:
        with connect("auth") as db:
            db.execute("INSERT INTO users(id,email,password_hash) VALUES(?,?,?)",
                       (str(uuid.uuid4()), body.email.lower(), hash_password(body.password)))
    except Exception:
        raise HTTPException(409, "Email already registered")
    return {"message":"User registered"}

@app.post("/api/v1/auth/login")
def login(body: Login):
    check_rate_limit("auth-login:"+body.email, 10, 60)
    with connect("auth") as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (body.email.lower(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token":create_token(row["id"], row["role"]), "token_type":"bearer",
            "expires_in":1800}

@app.get("/api/v1/auth/me")
def me(user=Depends(current_user)):
    return {"user_id":user["sub"],"role":user["role"]}
