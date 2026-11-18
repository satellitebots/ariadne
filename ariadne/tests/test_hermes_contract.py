"""The Hermes surfaces Ariadne depends on. Ariadne never patches Hermes; it only uses its public CLI flags, config
keys, plugin hooks and output. Run these after bumping the upstream/ pin: a failure names exactly what changed."""
import re
import subprocess

import pytest

from ariadne import paths

pytestmark = pytest.mark.skipif(not paths.HERMES_EXE.exists(), reason="Hermes is not installed")


def _help(*args):
    p = subprocess.run([str(paths.HERMES_EXE), *args, "--help"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    return p.stdout + p.stderr


def test_chat_flags():
    h = _help("chat")
    for flag in ("--query-file", "-Q", "--source", "--run-budget", "--max-turns", "-t", "-s", "-m", "--resume",
                 "--no-restore-cwd", "--reasoning", "--pass-session-id", "--continue", "--create-if-missing"):
        assert re.search(rf"(^|[\s\[,]){re.escape(flag)}([\s\],=]|$)", h, re.M), f"hermes chat lost {flag}"


def test_gateway_stop_and_desktop_flags():
    assert "--yes" in _help("gateway", "stop")
    d = _help("desktop")
    for flag in ("--hermes-root", "--cwd", "--local", "--force-build", "--build-only"):
        assert flag in d, f"hermes desktop lost {flag}"


def test_config_keys_we_set():
    src = (paths.UPSTREAM / "hermes_cli" / "config_defaults.py").read_text(encoding="utf-8")
    for key in ('"compression"', '"threshold_tokens"', '"tail_mode"', '"max_attempts"', '"title_generation"',
                '"model_upgrade_enabled"', '"model_catalog"', '"fallback_providers"'):
        assert key in src, f"config key {key} is gone from Hermes defaults"


def test_quiet_mode_prints_the_session_id():
    src = "\n".join(f.read_text(encoding="utf-8", errors="replace")
                    for f in (paths.UPSTREAM / "hermes_cli").glob("*single_query*.py"))
    assert "session_id:" in src, "hermes chat -Q no longer prints 'session_id:' (Ariadne resumes sessions by it)"


def test_agent_log_lines_we_parse():
    src = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in (paths.UPSTREAM / "agent").glob("*.py"))
    assert re.search(r"tool %s (completed|failed)|tool \{.*\} completed|completed \(", src), "tool_executor log line changed"
    assert "API call #" in src, "the per-call log line changed (python -m ariadne watch parses it)"
