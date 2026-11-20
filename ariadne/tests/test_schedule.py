"""B11: schedules are standing briefs - cron arithmetic, inheritance from the session, one task per due run."""
import time
from datetime import datetime

import pytest

from ariadne import schedule as sched
from ariadne import models as modellib, paths, service, store as storelib

REPO_FLOWS = paths.ROOT / "flows"


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setattr(modellib.Model, "installed", lambda self: True)
    s = storelib.Store(tmp_path / "t.db", require_gates=False)
    monkeypatch.setattr(service, "_store", s)
    return s


def test_cron_is_five_fields_with_ranges_steps_and_lists():
    assert sched.parse("*/15 9-17 * * 1-5")[0] == (0, 15, 30, 45)
    assert sched.parse("0,30 0 * * 7")[4] == (0,)                  # 7 is Sunday, kept as 0
    assert sched.parse("@daily") == ((0,), (0,), tuple(range(1, 32)), tuple(range(1, 13)), tuple(range(7)))
    for bad in ("* * *", "60 * * * *", "* 24 * * *", "*/0 * * * *", "x * * * *", "* * 0 * *"):
        with pytest.raises(sched.ScheduleError):
            sched.parse(bad)


def test_next_after_finds_the_next_boundary():
    base = time.mktime((2026, 11, 19, 22, 7, 0, 2, 323, 0))      # a Thursday, 22:07 local
    nxt = sched.next_after("0 2 * * *", base)
    assert datetime.fromtimestamp(nxt).strftime("%Y-%m-%d %H:%M") == "2026-11-20 02:00"
    five = sched.next_after("*/5 * * * *", base)
    assert datetime.fromtimestamp(five).strftime("%H:%M") == "22:10"
    monday = sched.next_after("30 9 * * 1", base)                 # next Monday 09:30
    assert datetime.fromtimestamp(monday).strftime("%Y-%m-%d %H:%M") == "2026-11-23 09:30"


def test_the_first_run_is_the_next_boundary_not_now(st):
    service.submit("run the suite", source="cli", flow="coding", model="qwen3.6-35b-a3b",
                   workspace="C:/repos/proj", session="proj", gates=["run: exit 0"])
    row = service.schedule_create("proj", "0 2 * * *", store=st)
    assert row["flow"] == "coding" and row["model"] == "qwen3.6-35b-a3b" and row["workspace"] == "C:/repos/proj"
    assert row["gates"] == '[{"type": "run", "text": "exit 0"}]'
    assert sched.due(row, now=time.time()) is False               # created now: 02:00 is still ahead


def test_a_schedule_inherits_from_a_session_and_refuses_an_empty_one(st):
    with pytest.raises(Exception, match="no task yet"):
        service.schedule_create("ghost", "0 2 * * *", store=st)
    service.submit("brief", source="cli", flow="coding", model="qwen3.6-35b-a3b", workspace="C:/w", session="s1",
                   gates=["run: exit 0"])
    with pytest.raises(Exception):
        service.schedule_create("s1", "not a cron", store=st)
    row = service.schedule_create("s1", "@daily", brief="custom standing brief", store=st)
    assert row["brief"] == "custom standing brief" and row["cron"] == "@daily"


def test_sweep_submits_one_normal_task_per_due_occurrence(st):
    service.submit("nightly", source="cli", flow="coding", model="qwen3.6-35b-a3b", workspace="C:/w",
                   session="nightly", gates=["run: exit 0"])
    past = time.mktime((2026, 11, 1, 1, 59, 0, 5, 305, 0))         # created a minute before its first run
    service.schedule_create("nightly", "0 2 * * *", store=st, now=past)
    now = time.mktime((2026, 11, 1, 2, 0, 5, 5, 305, 0))           # just after 02:00
    done = sched.sweep(st, now=now)
    assert len(done) == 1 and done[0][0] == "nightly"
    task = st.get(done[0][1], events=False)
    assert task["source"] == "schedule" and task["session"] == "nightly" and task["status"] == "new"
    assert task["flow"] == "coding" and task["model"] == "qwen3.6-35b-a3b"
    assert sched.sweep(st, now=now) == []                          # same minute: not twice
    assert sched.sweep(st, now=now + 3600) == []                   # 03:00: not yet the next 02:00
    assert sched.sweep(st, now=now + 24 * 3600)                     # tomorrow 02:00


def test_a_disabled_schedule_does_not_run(st):
    service.submit("x", source="cli", flow="coding", model="qwen3.6-35b-a3b", workspace="C:/w", session="s",
                   gates=["run: exit 0"])
    past = time.mktime((2026, 11, 1, 1, 59, 0, 5, 305, 0))
    service.schedule_create("s", "0 2 * * *", store=st, now=past)
    assert sched.due(st.schedule("s"), now=past + 60) is True        # it would run...
    service.schedule_set("s", False, store=st)
    assert sched.sweep(st, now=past + 400 * 86400) == []             # ...but it is off


def test_a_refused_submission_disables_the_schedule_instead_of_retrying(st, monkeypatch):
    service.submit("x", source="cli", flow="coding", model="qwen3.6-35b-a3b", workspace="C:/w", session="s",
                   gates=["run: exit 0"])
    past = time.mktime((2026, 11, 1, 1, 59, 0, 5, 305, 0))
    service.schedule_create("s", "0 2 * * *", store=st, now=past)
    calls = []

    def refuse(schedule_row, store):
        calls.append(schedule_row["name"])
        raise service.TaskError("the flow no longer exists")
    assert sched.sweep(st, now=past + 60, submit=refuse) == []
    assert calls == ["s"] and st.schedule("s")["enabled"] == 0
    assert sched.sweep(st, now=past + 3 * 86400) == []


def test_the_cli_lists_and_switches(st, capsys):
    service.submit("x", source="cli", flow="coding", model="qwen3.6-35b-a3b", workspace="C:/w", session="s",
                   gates=["run: exit 0"])
    assert sched.main(["create", "s", "--cron", "0 2 * * *", "--brief", "nightly tests"]) == 0
    out = capsys.readouterr().out
    assert "schedule s: 0 2 * * *" in out
    assert sched.main(["off", "s"]) == 0 and st.schedule("s")["enabled"] == 0
    assert sched.main([]) == 0 and "off  s" in capsys.readouterr().out
    assert sched.main(["rm", "s"]) == 0 and st.schedules() == []
