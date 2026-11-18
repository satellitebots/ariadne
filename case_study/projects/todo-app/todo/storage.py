"""JSON-backed storage for the todo app.

On-disk format:

    {"next_id": int, "items": [{"id": int, "text": str, "done": bool}]}

``next_id`` is a persisted monotonic counter, so ids are never reused even
after items are removed.
"""

import json
import os
from pathlib import Path

DEFAULT_FILENAME = "todo.json"


class TodoError(Exception):
    """Base error for todo storage operations."""


class UnknownIdError(TodoError):
    """Raised when an operation names an id that does not exist."""

    def __init__(self, item_id):
        super().__init__(f"no todo item with id {item_id}")
        self.item_id = item_id


class TodoStore:
    """Read and write a JSON todo file.

    The file path comes from, in priority order:

    1. the ``path`` argument,
    2. the ``TODO_FILE`` environment variable,
    3. ``todo.json`` in the current working directory.
    """

    def __init__(self, path=None):
        if path is None:
            path = os.environ.get("TODO_FILE") or DEFAULT_FILENAME
        self.path = Path(path)

    # -- persistence -------------------------------------------------------

    def _load(self):
        if not self.path.exists():
            return {"next_id": 1, "items": []}
        with self.path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("next_id", 1)
        data.setdefault("items", [])
        return data

    def _save(self, data):
        with self.path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")

    # -- operations ----------------------------------------------------------

    def add(self, text):
        data = self._load()
        item = {"id": data["next_id"], "text": text, "done": False}
        data["next_id"] += 1
        data["items"].append(item)
        self._save(data)
        return item

    def list(self):
        return list(self._load()["items"])

    def _find_index(self, data, item_id):
        for index, item in enumerate(data["items"]):
            if item["id"] == item_id:
                return index
        raise UnknownIdError(item_id)

    def mark_done(self, item_id):
        data = self._load()
        item = data["items"][self._find_index(data, item_id)]
        item["done"] = True
        self._save(data)
        return item

    def remove(self, item_id):
        data = self._load()
        index = self._find_index(data, item_id)
        item = data["items"].pop(index)
        self._save(data)
        return item

    def clear_done(self):
        data = self._load()
        remaining = [item for item in data["items"] if not item["done"]]
        removed = len(data["items"]) - len(remaining)
        data["items"] = remaining
        self._save(data)
        return removed
