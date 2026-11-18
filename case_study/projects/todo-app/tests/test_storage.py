"""Tests for todo.storage."""

import json
import os
from pathlib import Path

import pytest

from todo.storage import TodoStore, UnknownIdError, DEFAULT_FILENAME


def test_json_round_trip(tmp_path):
    """Adding, listing, and clearing round-trips through the JSON file."""
    store = TodoStore(tmp_path / "todos.json")
    item1 = store.add("alpha")
    assert item1 == {"id": 1, "text": "alpha", "done": False}
    item2 = store.add("beta")
    assert item2["id"] == 2

    items = store.list()
    assert len(items) == 2
    assert items[0]["text"] == "alpha"
    assert items[1]["text"] == "beta"

    removed = store.clear_done()
    assert removed == 0
    assert store.list() == items  # nothing changed


def test_missing_file_starts_empty(tmp_path):
    store = TodoStore(tmp_path / "nonexistent.json")
    items = store.list()
    assert items == []
    item = store.add("solo")
    assert item["id"] == 1


def test_env_override(tmp_path, monkeypatch):
    env_path = tmp_path / "env.json"
    monkeypatch.setenv("TODO_FILE", str(env_path))
    store = TodoStore()  # no path arg -> uses env
    item = store.add("env item")
    assert item["text"] == "env item"
    assert env_path.exists()
    # file arg should override env
    store2 = TodoStore(tmp_path / "arg.json")
    store2.add("arg item")
    assert json.loads(env_path.read_text())["items"][0]["text"] == "env item"


def test_id_stability_monotonic_counter(tmp_path):
    """G3: after add a, add b, remove 1, add c -> ids [2, 3]."""
    store = TodoStore(tmp_path / "ids.json")
    store.add("a")
    store.add("b")
    store.remove(1)
    store.add("c")
    ids = [item["id"] for item in store.list()]
    assert ids == [2, 3]


def test_unknown_id_mark_done(tmp_path):
    store = TodoStore(tmp_path / "unknown.json")
    with pytest.raises(UnknownIdError) as exc_info:
        store.mark_done(99)
    assert "no todo item with id 99" in str(exc_info.value)
    assert exc_info.value.item_id == 99


def test_unknown_id_remove(tmp_path):
    store = TodoStore(tmp_path / "unknown.json")
    with pytest.raises(UnknownIdError) as exc_info:
        store.remove(99)
    assert "no todo item with id 99" in str(exc_info.value)


def test_mark_done_sets_flag(tmp_path):
    store = TodoStore(tmp_path / "done.json")
    store.add("work")
    item = store.mark_done(1)
    assert item["done"] is True
    assert store.list()[0]["done"] is True


def test_remove_returns_item(tmp_path):
    store = TodoStore(tmp_path / "rm.json")
    store.add("gone")
    item = store.remove(1)
    assert item["text"] == "gone"
    assert store.list() == []


def test_clear_done_removes_only_done(tmp_path):
    store = TodoStore(tmp_path / "cd.json")
    store.add("keep")
    store.add("drop")
    store.mark_done(2)
    removed = store.clear_done()
    assert removed == 1
    texts = [i["text"] for i in store.list()]
    assert texts == ["keep"]
