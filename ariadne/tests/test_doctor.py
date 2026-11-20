"""B13: doctor reports the dependency set Ariadne actually has now - Python, the server, and each flow's needs."""
import pytest

from ariadne import deps, serving


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    """doctor shells out to git, nvidia-smi and the venv python; the lines under test need none of that."""
    class Done:
        returncode = 0
        stdout = ""
        stderr = ""
    monkeypatch.setattr(deps, "_run", lambda *a, **k: Done())
    monkeypatch.setattr(deps, "gpu", lambda: (True, "NVIDIA driver (nvidia-smi)"))
    monkeypatch.setattr(deps, "bin_entries", lambda *a, **k: [])
    monkeypatch.setattr(deps, "submodule_pin", lambda: "0" * 40)
    monkeypatch.setattr(deps.paths, "VENV_PY", __import__("pathlib").Path(__file__))   # exists and is a file


def test_doctor_names_python_the_server_and_every_flow(monkeypatch):
    monkeypatch.setattr(serving, "probe", lambda srv=None, timeout=2: {"kind": "ollama", "models": ["qwen3.5:9b"]})
    r = deps.check(full=False)
    names = [c.name for c in r.checks]
    assert any(n.startswith("Python ") for n in names)
    assert any(n.startswith("model server: ") for n in names)
    for flow in ("coding", "content", "design", "investigation"):
        assert any(n.startswith(f"flow {flow} (") for n in names), flow
    server = next(c for c in r.checks if c.name.startswith("model server"))
    assert server.ok is True and server.required is False and "answers as ollama" in server.why
    assert all(c.required is False for c in r.checks if c.name.startswith("flow "))


def test_a_server_that_does_not_answer_is_optional_not_a_failure(monkeypatch):
    def down(srv=None, timeout=2):
        raise serving.ServingError("nothing answered at http://127.0.0.1:8090")
    monkeypatch.setattr(serving, "probe", down)
    r = deps.check(full=False)
    server = next(c for c in r.checks if c.name.startswith("model server"))
    assert server.ok is False and server.required is False
    assert "not answering" in server.why and "server setup" in server.fix
    assert "not answering" in r.text()


def test_a_flow_that_cannot_get_its_tools_says_which(monkeypatch):
    from ariadne import flows as flowlib
    real = flowlib.load_flows

    class Fake:
        name, model, requires, mcp_servers = "coding", "qwen3.6-35b-a3b", ["helm"], ["git"]

    def fake_load(*a, **k):
        return {"coding": Fake()}
    monkeypatch.setattr(flowlib, "load_flows", fake_load)
    monkeypatch.setattr(flowlib, "missing_requirements", lambda fl: ["helm"] if fl is not None else [])
    r = deps.check(full=False)
    line = next(c for c in r.checks if c.name.startswith("flow coding"))
    assert line.ok is False and "missing: helm" in line.why
    monkeypatch.setattr(flowlib, "load_flows", real)
