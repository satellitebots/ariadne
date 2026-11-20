"""Sessions on disk: the message list of one conversation, resumable by id.

A session is what `worker.py` resumes when a gate fails, so it is the same unit the store calls a session - one
conversation per task (or per caller's session). Files, not sqlite, because a message list is a document: you can read
one without the runtime.
"""
import json
import re
import time
from pathlib import Path

DIR = "runtime-sessions"


def slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "session"))[:100]


def path(home, session):
    return Path(home) / DIR / f"{slug(session)}.json"


def load(home, session):
    try:
        return json.loads(path(home, session).read_text(encoding="utf-8")).get("messages") or []
    except (OSError, ValueError):
        return []


def save(home, session, messages):
    p = path(home, session)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"id": session, "updated": time.time(), "messages": messages}, ensure_ascii=False),
                 encoding="utf-8")
    return p
