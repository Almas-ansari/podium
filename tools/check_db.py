"""Verifies the configured database end to end, without printing the credential.

Reads DATABASE_URL from .env. Creates the schema, writes a parent, a child and a
session, reads them back, then removes everything it made. Run this before
deploying so a broken connection string is found here rather than in production.

    python tools/check_db.py
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, db  # noqa: E402


def describe(url: str) -> str:
    """Host and database only. Never the password."""
    parsed = urlparse(url)
    return f"{parsed.hostname or '?'}/{(parsed.path or '/').lstrip('/') or '?'}"


def main() -> int:
    if config.USE_POSTGRES:
        print(f"backend  : postgres  ({describe(config.DATABASE_URL)})")
    else:
        print(f"backend  : sqlite    ({config.DB_PATH})")
        print("           set DATABASE_URL in .env to test Postgres")

    print("connecting…")
    db.init_db()
    print("schema   : ok")

    parent = db.upsert_parent("check:tmp", "check@example.invalid", "Check Run")
    child_id = db.create_child(parent["id"], "Check", "9-11")
    db.record_consent(child_id, "Check Run")
    assert db.has_consent(child_id), "consent did not persist"

    session_id = db.insert_session({
        "child_id": child_id, "created_at": db.now_iso(), "mode": "impromptu",
        "age_band": "9-11", "topic_id": 1, "topic_text": "connection check",
        "target_seconds": 60, "duration": 12.0, "transcript": "hello",
        "words_json": "[]", "metrics_json": json.dumps({"pace": {"wpm": 100}}),
        "ideas_json": None, "feedback_json": "{}", "audio_path": None,
    })
    assert isinstance(session_id, int), "RETURNING id did not come back as an int"
    print(f"write    : ok  (session id {session_id})")

    row = db.get_session(session_id, child_id)
    assert row and row["topic_text"] == "connection check", "read-back mismatch"
    assert db.session_count(child_id) == 1
    print("read     : ok")

    db.mark_topic_used(child_id, 1)
    db.mark_topic_used(child_id, 1)          # must be idempotent on both backends
    assert db.used_topic_ids(child_id) == {1}
    print("upsert   : ok")

    db.delete_all_for_parent(parent["id"])
    assert db.get_child(child_id) is None, "cleanup left rows behind"
    print("cleanup  : ok")

    print("\nDatabase is ready.")
    db.close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
