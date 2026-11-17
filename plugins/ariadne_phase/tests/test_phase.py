import json

from ariadne_phase import phase

ALLOW = ["read_file", "search_files", "memory_recall", "git_status"]


def test_execute_phase_allows_everything():
    assert phase.decide("terminal", "execute", ALLOW) is None
    assert phase.decide("write_file", "execute", ALLOW) is None


def test_plan_phase_allows_read_only_tools():
    assert phase.decide("read_file", "plan", ALLOW) is None
    assert phase.decide("mcp_memory_memory_recall", "plan", ALLOW) is None
    assert phase.decide("git:git_status", "plan", ALLOW) is None


def test_plan_phase_blocks_writes_and_commands():
    for tool in ("write_file", "patch", "terminal", "mcp_git_git_commit", "execute_code"):
        reason = phase.decide(tool, "plan", ALLOW)
        assert reason and "plan phase" in reason


def test_phase_and_allowlist_come_from_the_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "ariadne_flow.json").write_text(json.dumps({"plan_tools": ["read_file"]}))
    assert phase.current_phase() == "execute"            # no file -> execute
    (tmp_path / "ariadne_phase").write_text("plan")
    assert phase.pre_tool_call("terminal", {"command": "ls"})["action"] == "block"
    assert phase.pre_tool_call("read_file", {"path": "x"}) is None
    log = (tmp_path / "logs" / "ariadne_tools.jsonl").read_text().splitlines()
    assert [json.loads(l)["blocked"] for l in log] == [True, False]


def test_blocklist_matches_urls_commands_and_subdomains():
    bl = ["example.com", "evil.org"]
    assert phase.blocked_host({"url": "https://www.example.com/a"}, bl) == "example.com"
    assert phase.blocked_host({"command": "curl evil.org/x"}, bl) == "evil.org"
    assert phase.blocked_host({"url": "https://notexample.com"}, bl) is None
    assert phase.blocked_host({"url": "https://example.community"}, bl) is None
    assert phase.blocked_host({"path": "C:/repos/x.py"}, bl) is None


def test_blocklist_applies_in_every_phase(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "ariadne_flow.json").write_text(json.dumps({"plan_tools": [], "blocklist": ["example.com"]}))
    (tmp_path / "ariadne_phase").write_text("execute")
    assert phase.pre_tool_call("navigate_page", {"url": "https://example.com"})["action"] == "block"
    assert phase.pre_tool_call("navigate_page", {"url": "https://python.org"}) is None
