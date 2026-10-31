import os, uuid, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.storage import connect, init_db
from shared.security import hash_password
init_db("auth", """CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
 role TEXT NOT NULL DEFAULT 'customer', created_at TEXT DEFAULT CURRENT_TIMESTAMP
)""")
email=os.getenv("ADMIN_EMAIL","admin@example.local")
password=os.getenv("ADMIN_PASSWORD")
if not password or len(password)<12:
    raise SystemExit("Set ADMIN_PASSWORD to at least 12 characters.")
with connect("auth") as db:
    db.execute("INSERT OR IGNORE INTO users(id,email,password_hash,role) VALUES(?,?,?,'admin')",
               (str(uuid.uuid4()),email,hash_password(password)))
print(f"Admin account ensured: {email}")
