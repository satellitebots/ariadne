import json
import threading

from ariadne import browser, park
from ariadne import flows as flowlib
from ariadne import orchestrator as orch
from ariadne.tests.test_core import REPO_FLOWS, FakeRunner, make_worker, env  # noqa: F401 -- env is a fixture


def _browser_args(home):
    from ruamel.yaml import YAML
    cfg = YAML(typ="safe").load((home / "config.yaml").read_text(encoding="utf-8"))
    return cfg["mcp_servers"]["browser"]["args"]


def test_flows_browse_isolated_until_debug_mode(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(browser, "STATE", env / "browser.json")
    fl = flowlib.load_flows(REPO_FLOWS)["coding"]
    assert "--isolated" in _browser_args(flowlib.compile_flow(fl, REPO_FLOWS))
    assert browser.main(["debug", "on"]) == 0 and browser.debug_on()
    assert "--autoConnect" in _browser_args(flowlib.compile_flow(fl, REPO_FLOWS))
    browser.main(["debug", "off"])
    assert "--isolated" in _browser_args(flowlib.compile_flow(fl, REPO_FLOWS))


def test_every_flow_can_search_and_hand_off_logins():
    for name, fl in flowlib.load_flows(REPO_FLOWS).items():
        assert "search" in fl.execute_toolsets and "web" in fl.mcp_servers and "jobs" in fl.mcp_servers, name
        assert "browser" in fl.mcp_servers and not fl.real_logins, name


def test_need_login_parks_the_task_and_says_what_to_do(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(park, "FLAG", env / "park.json")
    monkeypatch.setattr(browser, "STATE", env / "browser.json")
    monkeypatch.setattr(park, "wait_resumed", lambda poll=0.05: _wait())

    class Login(FakeRunner):
        def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
            self.calls.append((flow.name, phase, prompt, model, session))
            if phase == "execute" and sum(c[1] == "execute" for c in self.calls) == 1:
                park.request(by=browser.login_note("github.com", "read settings"))   # what need_login does
                threading.Timer(0.3, park.resume).start()
                return orch.RunResult("LOGIN NEEDED: github.com", orch.PARKED, "log", "hermes-9")
            return orch.RunResult(self.plan if phase == "plan" else "done; tests pass", 0, "log", "h")

    run = Login()
    w = make_worker(env, run)
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done"
    assert any("login needed: github.com" in e and "debug on" in e for e in t["events"])
    execs = [c for c in run.calls if c[1] == "execute"]
    assert execs[1][4] == "hermes-9" and execs[1][2] == orch.RESUME_PROMPT


def _wait():
    import time
    deadline = time.time() + 5
    while park.requested() and time.time() < deadline:
        time.sleep(0.05)
    assert json.dumps(park.requested()) == "null"
