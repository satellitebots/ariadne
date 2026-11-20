"""The `ariadne` shim can run under system Python; the app must not."""
import pytest

from ariadne import __main__ as cli


def test_the_project_venv_is_found():
    venv = cli._project_venv()
    assert venv is not None and venv.exists()


def test_an_interpreter_already_in_the_venv_is_not_reexecuted(monkeypatch):
    monkeypatch.setattr(cli.sys, "executable", str(cli._project_venv()))
    monkeypatch.setattr(cli.os, "execv", lambda *a: pytest.fail("should not re-exec from the venv"))
    cli._ensure_project_interpreter(["inbox"])


def test_a_foreign_interpreter_reexecs_into_the_venv(monkeypatch):
    calls = {}
    monkeypatch.setattr(cli.sys, "executable", "C:/Python313/python.exe")
    monkeypatch.setattr(cli.os, "execv", lambda exe, argv: calls.update(exe=exe, argv=argv))
    monkeypatch.delenv("ARIADNE_REEXEC", raising=False)
    cli._ensure_project_interpreter(["up", "--lan"])
    assert calls["exe"] == str(cli._project_venv())
    assert calls["argv"][1:] == ["-m", "ariadne", "up", "--lan"]


def test_reexec_never_loops(monkeypatch):
    monkeypatch.setattr(cli.sys, "executable", "C:/Python313/python.exe")
    monkeypatch.setenv("ARIADNE_REEXEC", "1")
    monkeypatch.setattr(cli.os, "execv", lambda *a: pytest.fail("ARIADNE_REEXEC must stop the loop"))
    cli._ensure_project_interpreter(["up"])
