import json
import sys

from ariadne import jobs
from ariadne import orchestrator as orch
from ariadne.tests.test_core import FakeRunner, make_worker, env  # noqa: F401 -- env is a fixture

PY = f'"{sys.executable}"'


def test_a_job_runs_with_its_outputs_and_report(env):  # noqa: F811
    db = env / "t.db"
    (env / "ws").mkdir()
    cmd = PY + ' -c "import json; open(\'out.txt\',\'w\').write(\'x\'); json.dump({\'n\': 3}, open(\'r.json\',\'w\')); print(\'hi\')"'
    jid = jobs.submit("t1", cmd, env / "ws", why="make out", after="check n", expects=["out.txt", "gone.txt"],
                      report="r.json", db_path=db)
    unloaded = []
    j = jobs.run(jobs.get(jid, db), db, unload=lambda: unloaded.append(1), poll=0.05)
    assert unloaded and j["status"] == "done" and j["exit_code"] == 0
    text = jobs.result_text(j)
    assert "out.txt present" in text and "gone.txt MISSING" in text and '"n": 3' in text and "hi" in text
    assert "YOUR NOTE FOR WHEN IT FINISHED: check n" in text


def test_a_failing_and_a_too_long_job(env):  # noqa: F811
    db = env / "t.db"
    bad = jobs.run(jobs.get(jobs.submit("t1", PY + ' -c "raise SystemExit(3)"', env, db_path=db), db), db,
                   unload=lambda: True, poll=0.05)
    assert bad["status"] == "failed" and bad["exit_code"] == 3
    jid = jobs.submit("t1", PY + ' -c "import time; time.sleep(30)"', env, db_path=db)
    j = jobs.get(jid, db)
    j["max_minutes"] = 0.01   # under a second
    assert jobs.run(j, db, unload=lambda: True, poll=0.05)["status"] == "timeout"


def test_the_worker_runs_submitted_jobs_and_wakes_the_same_session(env):  # noqa: F811
    class Submits(FakeRunner):
        def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
            self.calls.append((flow.name, phase, prompt, model, session))
            if phase == "execute" and sum(c[1] == "execute" for c in self.calls) == 1:
                jobs.submit(tid, PY + ' -c "print(42)"', ws, why="answer", after="report it", db_path=env / "t.db")
                return orch.RunResult("JOB SUBMITTED", 0, "log", "hermes-7")
            return orch.RunResult(self.plan if phase == "plan" else "done; tests pass", 0, "log", "h")

    run = Submits()
    w = make_worker(env, run)
    tid = w.store.submit("fix x", "test", str(env))
    w.run_once(); w.store.approve(tid); w.run_once()
    execs = [c for c in run.calls if c[1] == "execute"]
    assert len(execs) == 2
    assert execs[1][4] == "hermes-7" and "42" in execs[1][2] and "report it" in execs[1][2]
    t = w.store.get(tid)
    assert t["status"] == "done" and any("job" in e and "done: exit 0" in e for e in t["events"])
    assert [j["status"] for j in jobs.for_task(tid, db_path=env / "t.db")] == ["done"]
    assert json.loads(jobs.for_task(tid, db_path=env / "t.db")[0]["result"])["exit_code"] == 0


def test_the_coding_flow_gets_the_jobs_server_with_its_home(env):  # noqa: F811
    from ariadne import flows as flowlib
    from ariadne.tests.test_core import REPO_FLOWS
    fl = flowlib.load_flows(REPO_FLOWS)["coding"]
    home = flowlib.compile_flow(fl, REPO_FLOWS)
    cfg = (home / "config.yaml").read_text()
    assert "ariadne.jobs_mcp" in cfg and fl.home.as_posix() in cfg
    assert orch.jobs_rule(fl) == orch.JOBS_RULE
