"""Seed a throwaway state folder with a signed task, a run part-way through and an open draft, for looking at the UI
without a model. Usage (any shell):

    set ARIADNE_STATE=%TEMP%\\ariadne-demo   (PowerShell: $env:ARIADNE_STATE="$env:TEMP\\ariadne-demo")
    python tools/demo_state.py && python -m ariadne ui --port 8918
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
assert os.environ.get("ARIADNE_STATE"), "set ARIADNE_STATE to a throwaway folder first"

from ariadne import durable, flows as flowlib, paths, spec as speclib, verbs  # noqa: E402

FLOWS = flowlib.load_flows()
store = durable.Store()
verbs.ctx = verbs.Ctx(store=store, flows=FLOWS)

ws = paths.ROOT / "sandbox" / "googl"
sp, _ = speclib.from_template(FLOWS["investigation"], name="googl-daily", workspace=str(ws))
sp["params"] = {"question": "How did GOOGL move in the last month, and what do the main indicators say?",
                "must_contain": "price change, 20/50-day moving averages, RSI, a bull or bear verdict with reasons"}
sp["goal"] = "REPORT.md answers how GOOGL moved and what the indicators say, with sources"
sp["trigger"] = {"kind": "cron", "cron": "0 7 * * 1-5"}
tid, _ = store.sign(speclib.validate(sp, FLOWS))

old = store.run_new(tid, "schedule (weekdays at 7)")
store.run_set(old, status="done", started=time.time() - 86400, ended=time.time() - 86400 + 1500, step=4)
for n in range(1, 5):
    store.step_set(old, n, 1, status="passed", ended=time.time() - 86000, model="qwen3.6-35b-a3b", report="ok", gate="passed")

rid = store.run_new(tid, "manual")
store.run_set(rid, status="running", started=time.time() - 640, step=3)
store.step_set(rid, 1, 1, status="passed", ended=time.time() - 560, model="qwen3.6-35b-a3b", gate="passed",
               report="NOTES.md: question bounded; sources to look for: Alphabet IR, Nasdaq, SEC 10-Q.")
store.step_set(rid, 2, 1, status="failed", ended=time.time() - 420, model="qwen3.6-35b-a3b",
               gate="$ python -c ... SOURCES.md\n(exit 1)\nonly 2 distinct sources", report="Collected prices via job j1125.")
store.step_set(rid, 2, 2, status="passed", ended=time.time() - 300, model="qwen3.6-35b-a3b", gate="passed",
               report="SOURCES.md lists 5 sources; data/prices.csv has 22 rows (job j1125-0912, 41 s).")
store.step_set(rid, 3, 1, status="running", model="qwen3.6-35b-a3b")
for kind, detail in [("queued", "googl-daily v1 (manual)"), ("step", "1/4 Bound the question on qwen3.6-35b-a3b, attempt 1"),
                     ("step", "1/4 passed"), ("job", "j1125-0912 started: pull 3 months of daily prices (models unloaded)"),
                     ("job", "j1125-0912 done: exit 0 in 41 s"), ("step", "2/4 failed its check: only 2 distinct sources"),
                     ("step", "2/4 passed"), ("step", "3/4 Write the report on qwen3.6-35b-a3b, attempt 1")]:
    store.event(rid, kind, detail)

d = verbs.call("draft", text="Each Monday, summarize what changed in the Kubernetes release notes", flow="investigation")
store.message(d["id"], "orchestrator", "Which Kubernetes versions should it compare, and where should the report go?")
print(f"seeded {paths.STATE}: task {tid}, run {rid}, draft {d['id']}")
