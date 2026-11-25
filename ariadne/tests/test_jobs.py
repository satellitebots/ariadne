import json
import sys

from ariadne import jobs
from ariadne import engine
from ariadne.tests.test_core import env  # noqa: F401 -- env is a fixture

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
    # max_minutes is an estimate, never a kill: a job past it still finishes
    jid = jobs.submit("t1", PY + ' -c "import time; time.sleep(1.5); print(1)"', env, db_path=db)
    j = jobs.get(jid, db)
    j["max_minutes"] = 0.01
    assert jobs.run(j, db, unload=lambda: True, poll=0.05)["status"] == "done"
    # the only kill is deliberate: the run was cancelled
    jid = jobs.submit("t1", PY + ' -c "import time; time.sleep(30)"', env, db_path=db)
    calls = iter([False, False, True])
    got = jobs.run(jobs.get(jid, db), db, unload=lambda: True, poll=0.05, stop=lambda: next(calls, True))
    assert got["status"] == "cancelled" and got["result"]


def test_the_coding_flow_gets_the_jobs_server_with_its_home(env):  # noqa: F811
    from ariadne import flows as flowlib
    from ariadne.tests.test_core import REPO_FLOWS
    fl = flowlib.load_flows(REPO_FLOWS)["coding"]
    cfg = flowlib.mcp_server_config(fl, REPO_FLOWS)
    assert "ariadne.jobs_mcp" in " ".join(cfg["jobs"]["args"])
    assert cfg["jobs"]["env"]["ARIADNE_FLOW_HOME"] == fl.home.as_posix()
    assert "submit_job" in engine.STEP_PROMPT
