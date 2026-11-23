"""Storage sqlite: token user + instance."""
import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

from config import BOT_SECRET, DATA_DIR

DB_PATH = DATA_DIR / "bot.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    api_token   TEXT NOT NULL,
    added_at    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS instances (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    project_name TEXT NOT NULL,
    project_id   TEXT,
    env_id       TEXT,
    service_id   TEXT,
    region       TEXT NOT NULL,
    domain       TEXT,
    proxy_port   INTEGER,
    ssh_user     TEXT NOT NULL,
    password     TEXT NOT NULL,
    created_at   INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'creating'
);
CREATE INDEX IF NOT EXISTS idx_inst_user ON instances(user_id);
"""


def _key() -> bytes:
    return hashlib.sha256(BOT_SECRET.encode()).digest()


def _crypt(data: bytes) -> bytes:
    """XOR keystream sha256 — obfuscation at rest, bukan enkripsi kuat."""
    key = _key()
    out = bytearray()
    for i in range(0, len(data), 32):
        block = hashlib.sha256(key + i.to_bytes(8, "big")).digest()
        chunk = data[i:i + 32]
        out.extend(b ^ k for b, k in zip(chunk, block))
    return bytes(out)


def _enc(text: str) -> str:
    return _crypt(text.encode()).hex()


def _dec(hexstr: str) -> str:
    return _crypt(bytes.fromhex(hexstr)).decode()


MIGRATIONS = (
    ("instances", "project_id", "TEXT"),
    ("instances", "env_id", "TEXT"),
    ("instances", "service_id", "TEXT"),
    ("instances", "flavor", "TEXT DEFAULT 'lsio'"),
)


def init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    for table, column, ctype in MIGRATIONS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ctype}")
    conn.commit()
    conn.close()
    try:
        os.chmod(DB_PATH, 0o600)
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def set_token(user_id: int, token: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO users (user_id, api_token, added_at) VALUES (?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET api_token=excluded.api_token, added_at=excluded.added_at",
            (user_id, _enc(token.strip()), int(time.time())),
        )


def get_token(user_id: int) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT api_token FROM users WHERE user_id=?", (user_id,)).fetchone()
    return _dec(row["api_token"]) if row else None


def del_token(user_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM users WHERE user_id=?", (user_id,))


def new_id() -> str:
    return secrets.token_hex(4)


def count_instances(user_id: int) -> int:
    """Instance gagal provisioning nggak dihitung ke quota."""
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM instances WHERE user_id=? AND status!='failed'",
            (user_id,),
        ).fetchone()[0]


def add_instance(user_id: int, project_name: str, region: str, password: str,
                 ssh_user: str = "dev", flavor: str = "lsio") -> str:
    iid = new_id()
    with _conn() as c:
        c.execute(
            "INSERT INTO instances (id,user_id,project_name,region,ssh_user,password,"
            "flavor,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (iid, user_id, project_name, region, ssh_user, password, flavor, int(time.time())),
        )
    return iid


def set_railway_ids(iid: str, project_id: str, env_id: str, service_id: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE instances SET project_id=?, env_id=?, service_id=? WHERE id=?",
            (project_id, env_id, service_id, iid),
        )


def finish_instance(iid: str, domain: str, proxy_port: int) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE instances SET domain=?, proxy_port=?, status='active' WHERE id=?",
            (domain, proxy_port, iid),
        )


def fail_instance(iid: str) -> None:
    with _conn() as c:
        c.execute("UPDATE instances SET status='failed' WHERE id=?", (iid,))


def get_instance(iid: str) -> sqlite3.Row | None:
    with _conn() as c:
        return c.execute("SELECT * FROM instances WHERE id=?", (iid,)).fetchone()


def list_instances(user_id: int) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            "SELECT * FROM instances WHERE user_id=? ORDER BY created_at DESC", (user_id,)
        ).fetchall()


def delete_instance(iid: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM instances WHERE id=?", (iid,))
