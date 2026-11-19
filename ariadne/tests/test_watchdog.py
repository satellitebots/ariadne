"""The watchdog escalates on fixed thresholds and never on a single blip."""
import json

from ariadne import watchdog


def _sampler(script):
    """A fake sampler: each call returns the next scripted sample."""
    calls = {"i": 0}

    def fake(url, th):
        bad = script[min(calls["i"], len(script) - 1)]
        calls["i"] += 1
        return {"ts": 0.0, "total_ram_mb": 32000, "free_ram_mb": 100 if bad else 8000,
                "total_vram_mb": 8000, "free_vram_mb": 100 if bad else 4000, "health_s": None if bad else 0.2,
                "reasons": ["free RAM 100 MB < 1500 MB"] if bad else [], "bad": bad}
    return fake


def _wd(script, tmp_path, **kw):
    calls = []
    return watchdog.Watchdog(server_url="http://127.0.0.1:1", thresholds={"consecutive": 3},
                             unload=lambda: calls.append("unload") or "unloaded",
                             kill=lambda: calls.append("kill") or "killed",
                             flag=lambda tid, why: calls.append(("flag", tid, why)) or "flagged",
                             log_path=tmp_path / "watchdog.jsonl", sampler=_sampler(script), **kw), calls


def test_a_blip_is_not_an_incident(tmp_path):
    wd, calls = _wd([False, True, False], tmp_path)
    assert [wd.check() for _ in range(3)] == ["ok", "ok", "ok"]
    assert calls == []


def test_escalation_is_warn_unload_kill_flag(tmp_path):
    wd, calls = _wd([True] * 8, tmp_path)
    levels = [wd.check("t1") for _ in range(6)]
    assert levels == ["ok", "ok", "warn", "unload", "kill", "flag"]
    assert [c for c in calls if isinstance(c, str)] == ["unload", "kill"]
    assert calls[-1][0] == "flag" and calls[-1][1] == "t1" and "free RAM" in calls[-1][2]


def test_recovery_forgets_the_streak(tmp_path):
    wd, calls = _wd([True, True, False, True, True], tmp_path)
    levels = [wd.check() for _ in range(5)]
    assert levels == ["ok", "ok", "ok", "ok", "ok"]
    assert calls == []


def test_every_sample_is_logged_with_its_reasons(tmp_path):
    wd, _ = _wd([True] * 4, tmp_path)
    for _ in range(4):
        wd.check("t9")
    rows = [json.loads(line) for line in (tmp_path / "watchdog.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 4
    assert rows[3]["level"] == "unload" and rows[3]["task"] == "t9"
    assert rows[0]["reasons"] == ["free RAM 100 MB < 1500 MB"]


def test_run_stops_on_the_stop_flag(tmp_path):
    wd, _ = _wd([False] * 5, tmp_path, interval=0)
    assert wd.run(max_samples=3) == 3


# ---------- the wiring `serve` starts (B2) ----------

def test_the_flag_rung_acts_once_not_on_every_sample(tmp_path):
    """A sustained incident must not re-flag, re-kill or re-unload every interval."""
    wd, calls = _wd([True] * 10, tmp_path)
    levels = [wd.check("t1") for _ in range(9)]
    assert levels[2:] == ["warn", "unload", "kill", "flag", "flag", "flag", "flag"]
    assert [c[0] for c in calls if isinstance(c, tuple)] == ["flag"]          # one flag, not four
    rows = [json.loads(l) for l in (tmp_path / "watchdog.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r.get("repeat") for r in rows[-4:]] == [None, True, True, True]


def test_flag_tasks_hands_the_running_task_back_to_the_person(tmp_path):
    from ariadne import orchestrator as orch
    st = orch.Store(tmp_path / "t.db", require_gates=False)
    running = st.submit("build it", "test", str(tmp_path))
    done = st.submit("already finished", "test", str(tmp_path))
    st.update(running, status="executing")
    st.update(done, status="done")
    msg = watchdog.flag_tasks(st, "free RAM 100 MB < 1500 MB")
    assert running in msg
    t = st.get(running)
    assert t["status"] == "needs_attention" and "free RAM" in t["result"]
    assert any("watchdog: free RAM" in e for e in t["events"])
    assert st.get(done)["status"] == "done"                                  # finished work is not disturbed


def test_start_runs_the_watchdog_in_a_thread_and_stops_it(tmp_path):
    import time
    from ariadne import orchestrator as orch
    st = orch.Store(tmp_path / "t.db", require_gates=False)
    tid = st.submit("build it", "test", str(tmp_path))
    st.update(tid, status="executing")
    calls = []
    stop = watchdog.start(st, url="http://127.0.0.1:1", interval=0.01, thresholds={"consecutive": 1},
                          sampler=_sampler([True] * 50), log_path=tmp_path / "watchdog.jsonl",
                          unload=lambda: calls.append("unload"), kill=lambda: calls.append("kill"),
                          flag=lambda tid, why: calls.append(("flag", tid, why)))
    time.sleep(0.3)
    stop()
    assert "unload" in calls and "kill" in calls and any(isinstance(c, tuple) for c in calls)
    assert (tmp_path / "watchdog.jsonl").read_text(encoding="utf-8").count("\n") >= 4
    rows = [json.loads(l) for l in (tmp_path / "watchdog.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [r["level"] for r in rows][:5] == ["warn", "unload", "kill", "flag", "flag"]


def test_the_worker_serve_loop_starts_the_watchdog(monkeypatch):
    from ariadne import orchestrator as orch
    started = {}

    def fake_start(store, **kw):
        started["store"] = store
        return lambda: started.setdefault("stopped", True)

    monkeypatch.setattr(watchdog, "start", fake_start)
    stop = orch._watchdog("a-store")
    assert started["store"] == "a-store"
    stop()
    assert started["stopped"] is True


def test_unload_names_the_server_it_asked(tmp_path):
    assert "nothing answered" in watchdog.unload_model("http://127.0.0.1:1")
