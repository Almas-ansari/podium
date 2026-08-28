"""SQLite storage. stdlib sqlite3, no ORM. Schema is seeded on first run.

Shape: a parent signs in, and owns one or more child profiles. Everything a
child accumulates - sessions, topic history, and crucially their pitch and
volume baseline - hangs off the child profile, never off the browser. Two
siblings on one laptop get genuinely separate baselines.

All statements use `?` placeholders and RETURNING rather than lastrowid, so
moving to Postgres later is a driver swap rather than a rewrite.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .config import DATABASE_URL, DB_PATH, USE_POSTGRES

SCHEMA = """
CREATE TABLE IF NOT EXISTS parents (
    id             TEXT PRIMARY KEY,
    google_sub     TEXT UNIQUE,
    email          TEXT NOT NULL,
    name           TEXT,
    picture        TEXT,
    created_at     TEXT NOT NULL,
    last_login_at  TEXT
);

CREATE TABLE IF NOT EXISTS children (
    id            TEXT PRIMARY KEY,
    parent_id     TEXT NOT NULL REFERENCES parents(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    age_band      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    consent_at    TEXT,
    consent_name  TEXT
);

CREATE INDEX IF NOT EXISTS idx_children_parent ON children(parent_id);

CREATE TABLE IF NOT EXISTS sessions (
    id              {SERIAL},
    child_id        TEXT NOT NULL REFERENCES children(id) ON DELETE CASCADE,
    created_at      TEXT NOT NULL,
    mode            TEXT NOT NULL,
    age_band        TEXT NOT NULL,
    topic_id        INTEGER,
    topic_text      TEXT NOT NULL,
    target_seconds  INTEGER NOT NULL,
    duration        REAL NOT NULL,
    transcript      TEXT NOT NULL,
    words_json      TEXT NOT NULL,
    metrics_json    TEXT NOT NULL,
    ideas_json      TEXT,
    feedback_json   TEXT NOT NULL,
    audio_path      TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_child ON sessions(child_id, created_at);

CREATE TABLE IF NOT EXISTS topic_history (
    child_id  TEXT NOT NULL,
    topic_id  INTEGER NOT NULL,
    used_at   TEXT NOT NULL,
    PRIMARY KEY (child_id, topic_id)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


# --- connection layer -----------------------------------------------------
#
# One statement style for both backends. Queries are written with `?` and
# translated for Postgres, and every insert uses RETURNING rather than
# lastrowid, so the only real differences are the ones handled here.

def _schema_sql() -> str:
    serial = "BIGSERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return SCHEMA.replace("{SERIAL}", serial)


def _adapt(sql: str) -> str:
    """Translate `?` placeholders to `%s` for Postgres, leaving strings alone."""
    if not USE_POSTGRES:
        return sql
    out, in_string = [], False
    for ch in sql:
        if ch == "'":
            in_string = not in_string
        out.append("%s" if (ch == "?" and not in_string) else ch)
    return "".join(out)


# One pool for the process. Without it every connect() paid a fresh TCP and TLS
# handshake to the database region, and a single page makes about ten calls -
# which turned a 15ms page into a 15 second one.
_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=1,
            max_size=8,
            timeout=15,
            max_idle=300,
            kwargs={"row_factory": dict_row, "autocommit": True},
            open=True,
        )
    return _pool


def close_pool() -> None:
    """Shut the pool down. Without this its worker threads outlive the
    interpreter and raise PythonFinalizationError at exit."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


class Conn:
    """Thin wrapper so callers can use `with connect() as conn` on either backend."""

    def __init__(self, raw, is_postgres: bool, pool=None):
        self.raw = raw
        self.is_postgres = is_postgres
        self.pool = pool
        self.wrote = False

    def execute(self, sql: str, params=()):
        # The two drivers want opposite things for a parameterless query.
        # psycopg only parses placeholders when params is not None, and an empty
        # tuple makes it try - so a literal % in the SQL, a LIKE pattern say,
        # raises "only '%s', '%b', '%t' are allowed". sqlite3 meanwhile rejects
        # None and wants a sequence.
        if not sql.lstrip()[:6].upper().startswith("SELECT"):
            self.wrote = True
        args = tuple(params)
        if self.is_postgres and not args:
            return self.raw.execute(_adapt(sql))
        return self.raw.execute(_adapt(sql), args)

    def transaction(self):
        """All-or-nothing for multi-statement writes. Under autocommit Postgres
        needs this explicitly; SQLite already commits once at block exit."""
        if self.is_postgres:
            return self.raw.transaction()
        import contextlib
        return contextlib.nullcontext()

    def executescript(self, script: str) -> None:
        self.wrote = True
        if self.is_postgres:
            for statement in filter(None, (s.strip() for s in script.split(";"))):
                self.raw.execute(statement)
        else:
            self.raw.executescript(script)

    def __enter__(self) -> "Conn":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.is_postgres:
                pass          # autocommit: nothing outstanding either way
            elif exc_type is None:
                self.raw.commit()
            else:
                self.raw.rollback()
        finally:
            if self.pool is not None:
                self.pool.putconn(self.raw)   # back to the pool, not closed
            else:
                self.raw.close()


def connect() -> Conn:
    if USE_POSTGRES:
        pool = _get_pool()
        return Conn(pool.getconn(), True, pool=pool)

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # If the file has gone (deleted by hand, wiped by a container restart), rebuild
    # the schema here rather than 500ing every request until someone restarts.
    fresh = not DB_PATH.exists()
    raw = sqlite3.connect(DB_PATH)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    if fresh:
        raw.executescript(_schema_sql())
        raw.commit()
    return Conn(raw, False)


def _schema_is_stale(conn: Conn) -> bool:
    """True if a database from before accounts existed is sitting here."""
    if conn.is_postgres:
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'children' AND column_name = 'parent_id'"
        ).fetchone()
        has_table = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = 'children'"
        ).fetchone()
        return bool(has_table) and not row

    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='children'"
    ).fetchone():
        return False
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(children)").fetchall()}
    return "parent_id" not in columns


def init_db() -> None:
    with connect() as conn:
        if _schema_is_stale(conn):
            for table in ("sessions", "topic_history", "children"):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(_schema_sql())


# --- parents --------------------------------------------------------------

def upsert_parent(google_sub: str, email: str, name: str = "",
                  picture: str = "") -> sqlite3.Row:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM parents WHERE google_sub = ?", (google_sub,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE parents SET email = ?, name = ?, picture = ?, last_login_at = ? "
                "WHERE id = ?",
                (email, name, picture, now_iso(), row["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO parents (id, google_sub, email, name, picture, created_at, "
                "last_login_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_id(), google_sub, email, name, picture, now_iso(), now_iso()),
            )
        return conn.execute(
            "SELECT * FROM parents WHERE google_sub = ?", (google_sub,)
        ).fetchone()


def get_parent(parent_id: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute("SELECT * FROM parents WHERE id = ?", (parent_id,)).fetchone()


# --- children -------------------------------------------------------------

def create_child(parent_id: str, name: str, age_band: str) -> str:
    child_id = new_id()
    with connect() as conn:
        conn.execute(
            "INSERT INTO children (id, parent_id, name, age_band, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (child_id, parent_id, name.strip()[:60], age_band, now_iso()),
        )
    return child_id


def list_children(parent_id: str) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM children WHERE parent_id = ? ORDER BY created_at ASC", (parent_id,)
        ).fetchall()


def get_child(child_id: str, parent_id: Optional[str] = None) -> Optional[sqlite3.Row]:
    """parent_id scopes the lookup, so one parent can never read another's child."""
    with connect() as conn:
        if parent_id:
            return conn.execute(
                "SELECT * FROM children WHERE id = ? AND parent_id = ?", (child_id, parent_id)
            ).fetchone()
        return conn.execute("SELECT * FROM children WHERE id = ?", (child_id,)).fetchone()


def update_child(child_id: str, parent_id: str, name: str, age_band: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE children SET name = ?, age_band = ? WHERE id = ? AND parent_id = ?",
            (name.strip()[:60], age_band, child_id, parent_id),
        )


def set_age_band(child_id: str, age_band: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE children SET age_band = ? WHERE id = ?", (age_band, child_id))


def record_consent(child_id: str, parent_name: str) -> None:
    """Parental consent is the gate on recording (DPDP Act 2023), stored per child."""
    with connect() as conn:
        conn.execute(
            "UPDATE children SET consent_at = ?, consent_name = ? WHERE id = ?",
            (now_iso(), parent_name.strip()[:120], child_id),
        )


def has_consent(child_id: str) -> bool:
    row = get_child(child_id)
    return bool(row and row["consent_at"])


# --- sessions -------------------------------------------------------------

def insert_session(data: dict[str, Any]) -> int:
    cols = (
        "child_id", "created_at", "mode", "age_band", "topic_id", "topic_text",
        "target_seconds", "duration", "transcript", "words_json", "metrics_json",
        "ideas_json", "feedback_json", "audio_path",
    )
    values = [data.get(c) for c in cols]
    with connect() as conn:
        row = conn.execute(
            f"INSERT INTO sessions ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))}) RETURNING id",
            values,
        ).fetchone()
        return int(row["id"])


def get_session(session_id: int, child_id: str) -> Optional[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE id = ? AND child_id = ?", (session_id, child_id)
        ).fetchone()


def list_sessions(child_id: str, limit: int = 200) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE child_id = ? ORDER BY created_at ASC, id ASC LIMIT ?",
            (child_id, limit),
        ).fetchall()


def session_count(child_id: str) -> int:
    with connect() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM sessions WHERE child_id = ?", (child_id,)
            ).fetchone()["n"]
        )


def metrics_history(child_id: str) -> list[dict[str, Any]]:
    """Every past session's raw metrics, oldest first. Used for baselines."""
    out = []
    for row in list_sessions(child_id):
        try:
            out.append(json.loads(row["metrics_json"]))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


# --- topic history --------------------------------------------------------

def mark_topic_used(child_id: str, topic_id: int) -> None:
    """Idempotent insert. The two backends spell "ignore a duplicate" differently."""
    if USE_POSTGRES:
        sql = ("INSERT INTO topic_history (child_id, topic_id, used_at) "
               "VALUES (?, ?, ?) ON CONFLICT (child_id, topic_id) DO NOTHING")
    else:
        sql = ("INSERT OR IGNORE INTO topic_history (child_id, topic_id, used_at) "
               "VALUES (?, ?, ?)")
    with connect() as conn:
        conn.execute(sql, (child_id, topic_id, now_iso()))


def used_topic_ids(child_id: str) -> set[int]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT topic_id FROM topic_history WHERE child_id = ?", (child_id,)
        ).fetchall()
    return {int(r["topic_id"]) for r in rows}


def reset_topic_history(child_id: str, topic_ids: list[int]) -> None:
    """Called when a band's pool is exhausted, so rotation can start again."""
    if not topic_ids:
        return
    with connect() as conn:
        conn.execute(
            f"DELETE FROM topic_history WHERE child_id = ? AND topic_id IN "
            f"({','.join('?' * len(topic_ids))})",
            [child_id, *topic_ids],
        )


# --- deletion -------------------------------------------------------------

def delete_child(child_id: str, parent_id: str) -> list[str]:
    """Removes one child profile and everything under it. Returns audio paths."""
    with connect() as conn:
        owned = conn.execute(
            "SELECT 1 FROM children WHERE id = ? AND parent_id = ?", (child_id, parent_id)
        ).fetchone()
        if not owned:
            return []
        paths = [
            r["audio_path"] for r in conn.execute(
                "SELECT audio_path FROM sessions WHERE child_id = ? AND audio_path IS NOT NULL",
                (child_id,),
            ).fetchall()
        ]
        with conn.transaction():
            conn.execute("DELETE FROM sessions WHERE child_id = ?", (child_id,))
            conn.execute("DELETE FROM topic_history WHERE child_id = ?", (child_id,))
            conn.execute("DELETE FROM children WHERE id = ?", (child_id,))
    return [p for p in paths if p]


def delete_all_for_parent(parent_id: str) -> list[str]:
    """Wipes the parent, every child under them, and all their data."""
    paths: list[str] = []
    for child in list_children(parent_id):
        paths.extend(delete_child(child["id"], parent_id))
    with connect() as conn:
        conn.execute("DELETE FROM parents WHERE id = ?", (parent_id,))
    return paths
