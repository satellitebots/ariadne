"""QA gate: one experience across four surfaces. Every verb a person can use in the terminal exists in the console,
over MCP and in chat - otherwise a surface quietly becomes second-class."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_the_terminal_exposes_the_verbs():
    doc = _src("ariadne/__main__.py")
    for verb in ("submit", "steer", "gates", "ok", "fix", "no", "stop", "up", "down", "sessions", "chat"):
        assert verb in doc, f"terminal is missing `{verb}`"


def test_mcp_exposes_the_same_task_verbs():
    src = _src("ariadne/tasks_mcp.py")
    for tool in ("submit_task", "steer_task", "set_gates", "approve_task", "revise_task", "cancel_task",
                 "list_sessions"):
        assert f"def {tool}(" in src, f"MCP is missing `{tool}`"


def test_the_console_exposes_the_same_routes():
    src = _src("ariadne/server/app.py")
    for route in ("/api/tasks/{tid}/steer", "/api/tasks/{tid}/gates", "/api/tasks/{tid}/approve",
                  "/api/tasks/{tid}/revise", "/api/tasks/{tid}/cancel", "/api/sessions"):
        assert route in src, f"console is missing `{route}`"


def test_chat_can_submit_and_steer():
    src = _src("ariadne/chat.py")
    assert "submit_task" in src and "steer_task" in src
