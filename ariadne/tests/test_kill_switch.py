"""The hard closeout: force-kill by port, whatever process started it."""
from ariadne import procs


def test_kill_on_ports_parses_netstat_and_kills_only_ours(monkeypatch):
    calls = []

    def fake_run(args, **kw):
        if args[0] == "netstat":
            out = ("  TCP    127.0.0.1:8917    0.0.0.0:0    LISTENING    4242\r\n"
                   "  TCP    127.0.0.1:8911    0.0.0.0:0    LISTENING    5151\r\n"
                   "  TCP    0.0.0.0:8080     0.0.0.0:0    LISTENING       99\r\n")
            return type("R", (), {"stdout": out})()
        calls.append(args)
        return type("R", (), {"stdout": ""})()

    monkeypatch.setattr(procs.subprocess, "run", fake_run)
    monkeypatch.setattr(procs.os, "name", "nt")
    killed = procs.kill_on_ports([8917, 8911])
    assert killed == ["4242", "5151"]
    tks = [c for c in calls if c[0] == "taskkill"]
    assert len(tks) == 2
    assert {t[3] for t in tks} == {"4242", "5151"}


def test_an_empty_netstat_kills_nothing(monkeypatch):
    monkeypatch.setattr(procs.subprocess, "run",
                        lambda args, **kw: type("R", (), {"stdout": ""})())
    monkeypatch.setattr(procs.os, "name", "nt")
    assert procs.kill_on_ports([8917]) == []