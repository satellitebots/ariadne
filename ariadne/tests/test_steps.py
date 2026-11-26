"""Steps are the backbone: a planned list becomes one step per item (each:), checks are facts, a reviewer's FAIL is
not retried, a cancel stops at once, and the scheduler starts each trigger exactly as often as it should."""
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from ariadne import engine, paths, spec as speclib
from ariadne.tests.test_engine import FLOWS, Script, env, make_spec, start, write  # noqa: F401  (env is a fixture)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "checks"))
import piece_check  # noqa: E402
import plan_steps  # noqa: E402

PLAN = """# Plan
## Done when
- `python -c "print(1)"` prints 1
## Steps
1. Write the intro: who it is for
   details on an indented line are not a step
2. Write the DP section
- [ ] Write the max-flow section
## Notes
- not a step
"""


def plan_and_each(gate=None):
    return [{"title": "Plan", "instruction": "plan it", "outputs": ["PLAN.md"],
             "gate": {"type": "run", "text": "python {checks}/plan_steps.py PLAN.md --min 2 --max 8"}},
            {"title": "Write", "each": "PLAN.md", "instruction": "do {i} of {count}: {item}", "gate": gate},
            {"title": "Check", "instruction": "check it", "outputs": ["CHECK.md"]}]


def test_plan_items_are_the_top_level_list_under_steps_and_the_check_agrees():
    items = speclib.plan_items(PLAN)
    assert items == ["Write the intro: who it is for", "Write the DP section", "Write the max-flow section"]
    assert plan_steps.plan_items(PLAN) == items
    assert speclib.plan_items("## Steps\n\nno list here\n") == []


def test_an_each_step_becomes_one_step_per_planned_item(env):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", plan_and_each())
    rid = start(store, sp)
    w = Script({1: [write("PLAN.md", PLAN)], 5: [write("CHECK.md", "RESULT: PASS")]})
    engine.Engine(store, FLOWS, broker, step_runner=w).run_once()
    r = store.run(rid)
    assert r["status"] == "done", r["error"]
    plan = store.run_plan(rid)
    assert [s["n"] for s in plan] == [1, 2, 3, 4, 5]
    assert plan[2]["title"] == "Write 2/3: Write the DP section" and plan[2]["item"] == "Write the DP section"
    prompts = {n: p for kind, n, p, *_ in w.calls if kind == "step"}
    assert "do 3 of 3: Write the max-flow section" in prompts[4]       # each item its own step and session
    assert "STEP 5 OF 5" in prompts[5].upper() or "5 of 5" in prompts[5]
    assert any(e["kind"] == "plan" and "became 3 steps" in e["detail"] for e in store.events(rid, limit=100))


def test_a_plan_without_a_steps_list_fails_its_gate_and_retries_the_plan(env):
    store, broker, server, tmp = env
    rid = start(store, make_spec(tmp / "ws", plan_and_each()))
    w = Script({1: [write("PLAN.md", "# Plan\nno list"), write("PLAN.md", PLAN)], 5: [write("CHECK.md", "x")]})
    engine.Engine(store, FLOWS, broker, step_runner=w).run_once()
    assert store.run(rid)["status"] == "done"
    assert [n for kind, n, *_ in w.calls].count(1) == 2              # the plan step was retried, once


def test_a_reviewer_fail_goes_to_you_and_is_not_retried(env):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", [{"title": "A", "instruction": "a", "gate": {"type": "review", "text": "it is good"}}],
                   retries=2)
    rid = start(store, sp)
    w = Script({"review": [lambda ws, p: ("FAIL: not good", 0)] * 3})
    engine.Engine(store, FLOWS, broker, step_runner=w).run_once()
    r = store.run(rid)
    assert r["status"] == "needs_you" and "not retried" in r["error"]
    assert [n for kind, n, *_ in w.calls if kind == "step"] == [1]     # one attempt, no rework loop


def test_retries_are_capped():
    with pytest.raises(speclib.SpecError) as e:
        make_spec("C:/x/ws", [{"title": "A", "instruction": "a"}], retries=4)
    assert "retries" in str(e.value)


def test_every_flow_starts_with_planned_steps_not_one_big_step():
    from ariadne.tests.test_durable import FakeCatalog
    for name, fl in FLOWS.items():
        sp, asks = speclib.from_template(fl, name="t-" + name, workspace="C:/elsewhere/ws")
        sp["params"] = {k: "x" for k in asks}
        sp = speclib.validate(sp, FLOWS, FakeCatalog())           # every template is a valid task as it stands
        titles = [s["title"] for s in sp["steps"]]
        assert len(titles) >= 3, (name, titles)
        assert any(s.get("each") for s in sp["steps"]) or name == "investigation", (name, titles)
        assert sum(1 for g in sp.get("gates") or [] if (g.get("type") if isinstance(g, dict) else "review") == "review") <= 1


def test_a_cancel_stops_the_worker_at_once_not_after_the_model_call(tmp_path, monkeypatch):
    killed = []

    class Endless:
        pid, returncode = 1, None

        def communicate(self, timeout=None):
            if killed:
                return "", ""
            raise subprocess.TimeoutExpired("hermes", timeout)

    monkeypatch.setattr(engine.subprocess, "Popen", lambda *a, **k: Endless())
    monkeypatch.setattr(engine, "_kill_tree", lambda p: killed.append(p))
    monkeypatch.setattr(engine, "stop_gateway", lambda home: None)
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")
    fl = SimpleNamespace(home=tmp_path / "home", mcp_servers=[], skills=[], shared_skills=[], reasoning={})
    t0 = time.time()
    r = engine.hermes_step(fl, "step", "do it", tmp_path, "r1", "m", ["file"], stop=lambda: True)
    assert r.exit_code == engine.CANCELLED and killed and time.time() - t0 < 10


@pytest.mark.parametrize("trigger,runs", [({"kind": "now"}, 1), ({"kind": "manual"}, 0),
                                          ({"kind": "at", "at": "2020-01-01T07:00"}, 0)])
def test_each_trigger_starts_as_often_as_it_should(env, trigger, runs):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", [{"title": "A", "instruction": "a"}])
    sp["trigger"] = trigger
    tid, _ = store.sign(sp)
    if trigger["kind"] == "now":
        store.run_new(tid, "signed: run now")                       # what signing does
    for _ in range(3):                                              # runs, sweeps, and a worker restart
        e = engine.Engine(store, FLOWS, broker, step_runner=Script({}))
        e.run_once()
        e.sweep()
    assert len(store.runs(tid)) == runs


def test_a_cron_task_runs_once_per_due_time(env):
    store, broker, server, tmp = env
    sp = make_spec(tmp / "ws", [{"title": "A", "instruction": "a"}])
    sp["trigger"] = {"kind": "cron", "cron": "0 7 * * *"}
    tid, _ = store.sign(sp)
    clock = [store.task(tid)["next_due"] + 1]
    for _ in range(3):
        engine.Engine(store, FLOWS, broker, step_runner=Script({}), clock=lambda: clock[0]).run_once()
    assert len(store.runs(tid)) == 1
    clock[0] += 86400
    engine.Engine(store, FLOWS, broker, step_runner=Script({}), clock=lambda: clock[0]).run_once()
    assert len(store.runs(tid)) == 2


def test_piece_check_catches_a_missing_section_and_a_page_too_wide_for_a_phone(tmp_path):
    (tmp_path / "OUTLINE.md").write_text("## Steps\n1. Dynamic programming: LIS\n2. Max flow: Ford-Fulkerson\n")
    body = " ".join(["word"] * 40)
    page = (f'<html><head><meta name="viewport" content="width=device-width"></head><body>'
            f"<h1>Guide</h1><h2>Dynamic programming</h2><p>{body}</p><table><tr><td>x</td></tr></table></body></html>")
    (tmp_path / "g.html").write_text(page)
    out = subprocess.run([sys.executable, str(ROOT / "checks" / "piece_check.py"), "OUTLINE.md", "g.html"],
                         cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 1 and "item 2" in out.stdout and "overflow-x" in out.stdout
    page = page.replace("</body>", f"<h2>Max flow</h2><p>{body}</p></body>").replace(
        "<head>", "<head><style>table{display:block;overflow-x:auto}</style>")
    (tmp_path / "g.html").write_text(page)
    out = subprocess.run([sys.executable, str(ROOT / "checks" / "piece_check.py"), "OUTLINE.md", "g.html"],
                         cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout
