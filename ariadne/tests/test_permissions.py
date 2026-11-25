"""permissions.yaml: default allow, ask holds a run for a yes or no, deny refuses; the overlay lifts Hermes's guards."""
import json
import os
import subprocess
import sys
import textwrap

import pytest

from ariadne import durable, engine, flows as flowlib, park, paths, permissions
from ariadne.broker import Broker
from ariadne.tests.test_broker import FakeServer
from ariadne.tests.test_engine import FLOWS, Script, make_spec, start, write


@pytest.fixture
def rules_file(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "ASKS", tmp_path / "asks")
    f = tmp_path / "permissions.yaml"
    monkeypatch.setattr(permissions, "FILE", f)

    def set_rules(ask=None, deny=None):
        f.write_text(json.dumps({"default": "allow", "ask": ask or {}, "deny": deny or {}}), encoding="utf-8")
    set_rules()
    return set_rules


def test_the_shipped_file_allows_everything():
    rules = permissions.load(paths.ROOT / "permissions.yaml")
    assert all(not v for mode in rules.values() for v in mode.values())
    for kind, value in (("commands", "rm -rf /"), ("paths", "~/.ssh/id_rsa"), ("tools", "browser")):
        assert permissions.match(rules, kind, value) is None


def test_rules_match_commands_paths_and_tools_deny_first(rules_file):
    rules_file(ask={"commands": [r"\bgit\s+push\b"], "paths": ["~/.ssh/*"], "tools": ["browser"]},
               deny={"commands": [r"git push --force"]})
    rules = permissions.load()
    assert permissions.match(rules, "commands", "git push origin main") == ("ask", r"\bgit\s+push\b")
    assert permissions.match(rules, "commands", "git push --force")[0] == "deny"
    assert permissions.match(rules, "paths", os.path.expanduser("~/.ssh/config"))[0] == "ask"
    assert permissions.match(rules, "paths", "C:/repos/x.txt") is None
    assert permissions.match(rules, "tools", "browser")[0] == "ask"


def test_default_must_be_allow(rules_file, tmp_path):
    (tmp_path / "permissions.yaml").write_text("default: ask\n", encoding="utf-8")
    with pytest.raises(ValueError):
        permissions.load()


def test_a_yes_lasts_the_run_and_a_no_is_not_remembered(rules_file):
    permissions.ask("r1", "commands", "git push", r"git push")
    assert permissions.pending("r1")["what"] == "git push"
    permissions.answer("r1", yes=True)
    assert permissions.pending("r1") is None and permissions.is_approved("r1", "commands", "git push")
    permissions.ask("r1", "paths", "~/.ssh/config", "~/.ssh/*")
    permissions.answer("r1", yes=False)
    assert not permissions.is_approved("r1", "paths", "~/.ssh/*")
    assert not permissions.is_approved("r2", "commands", "git push")      # per run


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(park, "FLAG", tmp_path / "park.json")
    store = durable.Store(tmp_path / "a.db")
    broker = Broker(tmp_path / "m.db", server=FakeServer(), poll=0.01)
    return store, broker, tmp_path


def test_a_step_with_an_ask_tool_waits_for_a_yes(env, rules_file):
    store, broker, tmp = env
    rules_file(ask={"tools": ["terminal"]})
    rid = start(store, make_spec(tmp / "ws", [{"title": "A", "instruction": "a", "outputs": ["a.txt"]}]))
    seen = []

    def person(r):
        seen.append((store.run(r)["status"], broker.holder()))
        permissions.answer(r, yes=True)
    e = engine.Engine(store, FLOWS, broker, step_runner=Script({1: [write("a.txt")]}), wait_answered=person)
    e.run_once()
    assert seen == [("asking", None)]                 # asking, and the machine is free while it waits
    assert store.run(rid)["status"] == "done"


def test_no_to_a_tool_ends_the_run_and_deny_never_asks(env, rules_file):
    store, broker, tmp = env
    rules_file(ask={"tools": ["terminal"]})
    rid = start(store, make_spec(tmp / "ws", [{"title": "A", "instruction": "a", "outputs": ["a.txt"]}]))
    e = engine.Engine(store, FLOWS, broker, step_runner=Script({}),
                      wait_answered=lambda r: permissions.answer(r, yes=False))
    e.run_once()
    assert store.run(rid)["status"] == "needs_you" and "said no" in store.run(rid)["error"]

    rules_file(deny={"tools": ["terminal"]})
    rid = start(store, make_spec(tmp / "ws2", [{"title": "A", "instruction": "a", "outputs": ["a.txt"]}]))
    e = engine.Engine(store, FLOWS, broker, step_runner=Script({}), wait_answered=lambda r: pytest.fail("asked"))
    e.run_once()
    assert "denies" in store.run(rid)["error"]


def test_an_ask_inside_a_step_holds_the_run_then_resumes_the_session(env, rules_file):
    store, broker, tmp = env
    rid = start(store, make_spec(tmp / "ws", [{"title": "A", "instruction": "a", "outputs": ["a.txt"]}]))

    def hits_an_ask(ws, prompt):          # what the overlay does when a command matches an ask rule
        permissions.ask(rid, "commands", "git push origin main", r"git push")
        return "WAITING FOR THE PERSON", engine.PARKED

    def person(r):
        assert store.run(r)["status"] == "asking"
        permissions.answer(r, yes=True)
        store.steer(r, "The person approved: git push origin main. Go ahead and do it now.")
    script = Script({1: [hits_an_ask, write("a.txt")]})
    e = engine.Engine(store, FLOWS, broker, step_runner=script, wait_answered=person)
    e.run_once()
    assert store.run(rid)["status"] == "done"
    kind, n, prompt, session, _ = script.calls[-1]
    assert session == "sess-1" and "The person approved" in prompt       # same session, told the answer


HERMES_CHECK = textwrap.dedent(r"""
    import json, os, sys
    sys.path.append(sys.argv[1])
    import permissions_hook
    from tools import approval, file_tools, terminal_tool
    out = {
        "hardline": approval.check_dangerous_command("rm -rf /", "local")["approved"],
        "deny": approval.check_dangerous_command("git push --force", "local").get("message", ""),
        "ask": approval.check_dangerous_command("git push origin main", "local").get("message", ""),
        "sensitive": file_tools._check_sensitive_path(os.path.expanduser("~/.ssh/config")),
        "stale": file_tools._stale_overwrite_blocker(sys.argv[2], sys.argv[2], "t"),
        "applied": len(permissions_hook.APPLIED),
    }
    print("RESULT " + json.dumps(out))
""")


@pytest.mark.skipif(not paths.VENV_PY.exists(), reason="needs the project venv with Hermes installed")
def test_the_overlay_lifts_hermes_guards_inside_hermes(tmp_path):
    rules = tmp_path / "permissions.yaml"
    rules.write_text(json.dumps({"default": "allow", "ask": {"commands": [r"git push origin"]},
                                 "deny": {"commands": [r"git push --force"]}}), encoding="utf-8")
    existing = tmp_path / "old.txt"
    existing.write_text("never read by the agent", encoding="utf-8")
    env = dict(os.environ, HERMES_HOME=str(tmp_path / "home"), PYTHONIOENCODING="utf-8",
               **{**permissions.HERMES_ENV, "ARIADNE_PERMISSIONS_RUN": "r-hook", "ARIADNE_PERMISSIONS": str(rules),
                  "ARIADNE_STATE": str(tmp_path / "state")})
    script = tmp_path / "check.py"
    script.write_text(HERMES_CHECK, encoding="utf-8")
    p = subprocess.run([str(paths.VENV_PY), "-I", str(script), str(permissions.HOOK.parent), str(existing)],
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=300, cwd=tmp_path)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT ")), None)
    assert line, p.stdout[-2000:] + p.stderr[-3000:]
    out = json.loads(line[7:])
    assert out["hardline"] is True                       # Hermes's unconditional blocklist is gone
    assert "forbids" in out["deny"]                      # only the person's own rules stay
    assert "WAITING FOR THE PERSON" in out["ask"]
    assert out["sensitive"] is None and out["stale"] is None
    assert out["applied"] >= 10
    asked = json.loads((tmp_path / "state" / "asks" / "r-hook.json").read_text(encoding="utf-8"))
    assert asked["what"] == "git push origin main"
