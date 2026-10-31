"""Service-owned persistence adapter.

Use DATABASE_URL_<SERVICE> (PostgreSQL) in Compose; DATABASE_DIR is the local SQLite fallback.
"""
import os, re, sqlite3
from pathlib import Path
from contextlib import contextmanager

def _url(service: str):
    return os.getenv(f"DATABASE_URL_{service.upper()}") or os.getenv("DATABASE_URL")

def _pg_sql(sql: str) -> str:
    sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    sql = sql.replace("TEXT DEFAULT CURRENT_TIMESTAMP", "TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP")
    ignore_insert = "INSERT OR IGNORE INTO" in sql
    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
    sql = re.sub(r"(?<!%)\?", "%s", sql)
    if ignore_insert and "ON CONFLICT" not in sql.upper():
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    sql = sql.replace("=?", "=%s").replace("LIMIT ?", "LIMIT %s").replace("OFFSET ?", "OFFSET %s")
    if "INSERT INTO notifications" in sql and "ON CONFLICT" not in sql:
        sql += " ON CONFLICT (event_id) DO NOTHING"
    return sql

class PGConnection:
    def __init__(self, conn):
        self.conn = conn
    def execute(self, sql, params=()):
        return self.conn.execute(_pg_sql(sql), params)
    def executescript(self, script):
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.conn.execute(_pg_sql(statement))
    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self): self.conn.close()
    def __enter__(self): return self
    def __exit__(self, typ, value, tb):
        if typ: self.rollback()
        else: self.commit()
        self.close()

def db_path(service: str) -> str:
    directory = Path(os.getenv("DATABASE_DIR", "./var"))
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / f"{service}.sqlite3")

@contextmanager
def connect(service: str):
    url = _url(service)
    if url:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(url, row_factory=dict_row, connect_timeout=5)
        wrapped = PGConnection(conn)
        try:
            yield wrapped
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(db_path(service), timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def init_db(service: str, schema: str):
    with connect(service) as db:
        db.executescript(schema)
