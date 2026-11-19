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
