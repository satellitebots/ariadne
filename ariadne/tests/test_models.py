"""Model choice, sessions and KV parking: the catalog, a model per step in the backbrief, sign-off locks it, nothing
runs until every chosen model and tool is there (no weights, no network, no Hermes)."""
import json

import pytest

from ariadne import flows as flowlib
from ariadne import models as modellib
from ariadne import orchestrator as orch
from ariadne import paths
from ariadne.kvcache import KVCache, NoKVCache
from ariadne.memory import Memory

REPO_FLOWS = paths.ROOT / "flows"
PLAN = """MISSION: add a divide function with a banner and release notes
FLOW: coding
STEPS:
1. add divide() to calc.py - tools: file - model: qwen3.8-27b
2. write the release notes - tools: file - model: gemma-4-26b-a4b
3. add tests - tools: file, terminal - model: qwen3.8-27b
4. render a banner - tools: image - model: z-image-turbo
5. draw the module diagram - tools: diagram - model: gemma-4-12b
CHECKS: pytest passes
RISKS: none
QUESTIONS: none"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    monkeypatch.setattr(paths, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(paths, "STATE", tmp_path)
    monkeypatch.setattr(modellib, "PINS", tmp_path / "pins.json")
    (tmp_path / "logs").mkdir()
    installed = set()
    monkeypatch.setattr(modellib.Model, "installed", lambda self: self.name in installed or bool(self.ollama))
    return tmp_path, installed


class Runner:
    def __init__(self, plan=PLAN, results=None):
        self.plan, self.results, self.calls = plan, list(results or []), []

    def __call__(self, flow, phase, prompt, ws, tid, model=None, session=None):
        self.calls.append((phase, model, prompt, session))
        sid = session or f"h{len(self.calls)}"          # Hermes prints the session id it used
        if phase.startswith("checkpoint"):
            return orch.RunResult(f"SITUATION: summary {len(self.calls)}", 0, "log", sid)
        if phase.startswith("learn"):
            return orch.RunResult(f"---\nname: {flow.name}-lessons\ndescription: x\n---\n- lesson", 0, "log", sid)
        return orch.RunResult(self.plan if phase == "plan" else (self.results.pop(0) if self.results else "ok"), 0,
                              "log", sid)


class FakeKV:
    def __init__(self):
        self.log = []

    def restore(self, session, model, scope="master"):
        self.log.append(("restore", session, model, scope))
        return ""

    def save(self, session, model, scope="master"):
        self.log.append(("save", session, model, scope))
        return "saved 10 tokens"

    def drop(self, session):
        self.log.append(("drop", session))


def worker(tmp, runner, installer, mcp_servers=None, kv=None):
    flows = flowlib.load_flows(REPO_FLOWS)
    if mcp_servers is not None:
        flows["coding"].mcp_servers = mcp_servers
    flows["coding"].checks = []
    flows["coding"].model = "qwen3.8-27b"       # the mechanics tests below: a dense planner, steps on the planner
    flows["coding"].execute_model = ""
    return orch.Worker(store=orch.Store(tmp / "t.db", require_gates=False), memory=Memory(tmp / "m.db"), flows=flows, runner=runner,
                       llm_chat=lambda m, msgs: "coding", installer=installer, on_installed=lambda: None,
                       kv=kv or NoKVCache())


# ---------- catalog ----------

def test_catalog_has_a_model_per_job_that_runs_here():
    cat = modellib.load()
    assert cat.defaults == {"coding": "qwen3.6-35b-a3b", "design": "gemma-4-12b",
                            "investigation": "gemma-4-12b", "content": "gemma-4-12b",
                            "quick": "qwen3.5-9b", "image": "z-image-turbo", "router": "router", "embed": "embed"}
    assert cat.policy["families"] == ["gemma", "qwen", "sd-turbo", "z-image-turbo"]
    assert cat.policy["image"] == "z-image-turbo"
    assert all(m.family in cat.policy["families"] for m in cat.models.values())
    assert "deepseek-v4.1-flash" not in cat.models and "fimbulvetr-11b" not in cat.models
    assert all(m.size_gb <= 23 for m in cat.models.values())        # 8 GB GPU + 32 GB RAM
    for m in cat.models.values():
        assert m.roles and m.about, m.name
        assert m.ollama or all("repo" in p and ("file" in p or "dir" in p) for p in m.parts.values()), m.name
    with pytest.raises(modellib.ModelError):
        cat.get("nope")
    menu = cat.text().splitlines()                                 # policy first, then the model menu
    assert menu[0].startswith("Approved model families: gemma, qwen, sd-turbo, z-image-turbo")
    rows = [l for l in menu if l.startswith("- ")]
    assert rows[0].startswith("- qwen3.6-35b-a3b") and "MoE, 3B active" in rows[0]
    assert [m.moe for m in cat.pickable()].count(True) == 2


def test_swap_entries_serve_text_models_and_can_park_slots():
    e = modellib.swap_entries()
    assert "qwen3.8-27b" in e and "router" in e and "z-image-turbo" not in e
    assert "--fit on" in e["qwen3.8-27b"]["cmd"] and "--slot-save-path" in e["qwen3.8-27b"]["cmd"]
    assert "-c 65536" in e["qwen3.8-27b"]["cmd"] and "-c 16384" in e["router"]["cmd"]
    assert "--fit-target" not in e["router"]["cmd"]                 # models that fit stay in VRAM
    from ariadne import resources
    for profile, want in (("max", "--fit-target 256 --prio 2 -lm mmap+mlock"), ("shared", "--fit-target 768 --prio 0"),
                          ("light", "--fit-target 1638 --prio -1")):
        b = resources.budget(profile, vram=8, ram=32)
        assert want in modellib.swap_entries(budget=b)["qwen3.8-27b"]["cmd"], profile
    light = resources.budget("light", vram=8, ram=32)
    assert light["max_model_gb"] == 22.4                            # 80% of 8 GB GPU + 50% of 32 GB RAM
    assert "--slot-save-path" not in e["embed"]["cmd"]


def test_light_profile_keeps_big_models_off_the_menu(monkeypatch):
    from ariadne import resources
    cat = modellib.load()
    cat.budget = resources.budget("light", vram=8, ram=16)          # 6.4 + 8 = 14.4 GB
    names = [m.name for m in cat.pickable()]
    assert "qwen3.5-9b" in names and "qwen3.8-27b" not in names and "qwen3.6-35b-a3b" not in names


def test_flow_model_must_be_an_agent(tmp_path):
    d = tmp_path / "flows" / "w"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("name: w\ndescription: x\nwhen: y\nmodel: router\n")
    with pytest.raises(flowlib.FlowError, match="agent"):
        flowlib.load_flows(tmp_path / "flows")


def test_fetch_pins_sha_on_first_fetch_and_refuses_a_changed_file(env, monkeypatch):
    tmp, _ = env
    fname = "gemma-4-12b-it-UD-Q4_K_XL.gguf"
    monkeypatch.setattr(modellib, "_hf_tree", lambda repo, path="": [{"path": fname, "size": 10, "sha256": "a" * 64}])
    m = modellib.load().get("gemma-4-12b")
    (url, dest, got, size), = modellib.plan_fetch(m)
    assert got == "a" * 64 and url.endswith("/resolve/main/" + fname)
    assert json.loads((tmp / "pins.json").read_text())[f"unsloth/gemma-4-12b-it-GGUF/{fname}"] == "a" * 64
    monkeypatch.setattr(modellib, "_hf_tree", lambda repo, path="": [{"path": fname, "size": 10, "sha256": "b" * 64}])
    with pytest.raises(modellib.ModelError, match="pinned"):
        modellib.plan_fetch(m)


# ---------- the model plan ----------

def test_backbrief_carries_a_model_per_step(env):
    cat, fl = modellib.load(), flowlib.load_flows(REPO_FLOWS)["coding"]
    mp = orch.parse_model_plan(PLAN.replace("model: gemma-4-12b", "model: gpt-9"), fl, cat)
    # the MoE plans and runs steps that name no model (or an unknown one); the dense 27B only where a step names it
    assert (fl.model, fl.step_model, fl.reasoning["execute"]) == ("qwen3.6-35b-a3b", "qwen3.6-35b-a3b", "low")
    assert [s["model"] for s in mp["steps"]] == ["qwen3.8-27b", "gemma-4-26b-a4b", "qwen3.8-27b", "z-image-turbo",
                                                  "qwen3.6-35b-a3b"]
    assert "gpt-9" in mp["notes"][0] and "qwen3.6-35b-a3b" in mp["notes"][0]
    assert orch.needed_servers(mp, cat) == ["image"]
    groups = orch.step_groups(orch.parse_model_plan(PLAN, fl, cat), cat)
    assert [(a, [s["n"] for s in ss]) for a, ss in groups] == [       # an image step is run by the execute model
        ("qwen3.8-27b", [1]), ("gemma-4-26b-a4b", [2]), ("qwen3.8-27b", [3]), ("qwen3.6-35b-a3b", [4]),
        ("gemma-4-12b", [5])]


def test_overrides(env):
    cat, fl = modellib.load(), flowlib.load_flows(REPO_FLOWS)["coding"]
    mp = orch.parse_model_plan(PLAN, fl, cat)
    mp2 = orch.apply_model_overrides(mp, "4=sd-turbo, 1=qwen3.6-35b-a3b")
    assert mp2["steps"][3]["model"] == "sd-turbo" and mp2["steps"][0]["model"] == "qwen3.6-35b-a3b"
    assert orch.apply_model_overrides(mp, {"all": "qwen3.5-9b"})["agent"] == "qwen3.5-9b"
    for bad in ("9=qwen3.5-9b", "1=nope", "1=embed"):
        with pytest.raises(orch.TaskError):
            orch.apply_model_overrides(mp, bad)


def test_drill_with_models_fetches_before_step_one_and_runs_each_group_on_its_model(env):
    tmp, installed = env
    installed.update({"qwen3.8-27b"})                       # the planner is there; the rest is fetched after sign-off
    fetched, kv = [], FakeKV()
    run = Runner()
    w = worker(tmp, run, lambda name, cat, log=print: (fetched.append(name), installed.add(name)),
               mcp_servers=["memory", "git", "image"], kv=kv)
    tid = w.store.submit("divide", "test", str(tmp))
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "awaiting_signoff" and run.calls[0][1] == "qwen3.8-27b"
    assert "MODEL PLAN" in t["plan"] and "TO FETCH AFTER SIGN-OFF" in t["plan"] and "z-image-turbo" in t["plan"]
    assert "MODELS you may assign" in run.calls[0][2] and "gemma-4-31b" in run.calls[0][2]
    assert not fetched                                      # nothing is fetched before sign-off
    w.store.approve(tid, "5=qwen3.5-9b")
    assert json.loads(w.store.get(tid)["models"])["locked"]
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done", t
    assert set(fetched) == {"gemma-4-26b-a4b", "z-image-turbo"}
    execs = [c for c in run.calls if c[0] == "execute"]
    assert [c[1] for c in execs] == ["qwen3.8-27b", "gemma-4-26b-a4b", "qwen3.8-27b", "qwen3.5-9b"]
    # pause and compress: after the plan, after each step group, after QA - each on the model that just worked
    cps = [(c[0], c[1]) for c in run.calls if c[0].startswith("checkpoint")]
    assert cps == [("checkpoint:plan", "qwen3.8-27b"), ("checkpoint:execute", "qwen3.8-27b"),
                   ("checkpoint:execute", "gemma-4-26b-a4b"), ("checkpoint:execute", "qwen3.8-27b"),
                   ("checkpoint:execute", "qwen3.5-9b")]
    assert all(c[2].startswith("SESSION HANDOFF") for c in execs)    # every step starts from a handoff brief
    assert [c[3] for c in execs] == [None, None, None, None]          # each step: a new Hermes session
    for i, c in enumerate(run.calls):                                  # each checkpoint resumes the run it closes
        if c[0].startswith("checkpoint"):
            assert c[3] == f"h{i}", (i, c[0], c[3])
    assert "NOW DO STEP 1 ONLY" in execs[0][2] and "NOW DO STEPS 3, 4 ONLY" in execs[2][2]
    assert "generate_image(model='z-image-turbo'" in execs[2][2]
    # caches are parked per segment, step and model (plan and execute runs only); woken only when a run resumes
    # its Hermes session (a new session has a new prefix); a segment's caches go when it is compressed
    assert ("save", f"{tid}~1", "qwen3.8-27b", "plan") in kv.log and ("save", f"{tid}~3", "gemma-4-26b-a4b", "step-2") in kv.log
    assert not [e for e in kv.log if e[0] == "save" and e[3] in ("checkpoint", "learn", "review")]
    assert {e[3] for e in kv.log if e[0] == "restore"} == {"checkpoint"}   # only checkpoints resume a session
    assert ("drop", f"{tid}~1") in kv.log
    assert kv.log[-1] == ("drop", f"{tid}~6")
    assert w.store.sessions()[0]["segment"] == 6 and w.store.sessions()[0]["tasks"] == 1
    assert any("kv: qwen3.8-27b: saved" in e for e in t["events"])


def test_callers_session_is_continued_and_kept(env):
    tmp, installed = env
    installed.update({"qwen3.8-27b"})
    kv, run = FakeKV(), Runner(plan="MISSION: x\nSTEPS:\n1. edit - model: qwen3.8-27b")
    w = worker(tmp, run, lambda *a, **k: None, kv=kv)
    tid = w.store.submit("x", "mcp", str(tmp), session="claude-conv-42")
    w.run_once(); w.store.approve(tid); w.run_once()
    assert w.store.get(tid)["status"] == "done"
    assert w.store.session("claude-conv-42")["segment"] > 1
    assert not [e for e in kv.log if e[0] == "drop" and e[1] == f"claude-conv-42~{w.store.session('claude-conv-42')['segment']}"]
    # the next task in the same session starts from the last handoff brief
    tid2 = w.store.submit("y", "mcp", str(tmp), session="claude-conv-42")
    w.run_once()
    assert run.calls[-1][0] == "plan" and run.calls[-1][2].startswith("SESSION HANDOFF")


def test_nothing_starts_until_tools_and_models_are_there(env):
    tmp, installed = env
    installed.update({"qwen3.8-27b"})
    run = Runner()

    def fail(name, cat, log=print):
        raise modellib.ModelError("disk full")
    w = worker(tmp, run, fail, mcp_servers=["memory", "git"])     # no image server in the flow
    tid = w.store.submit("divide", "test", str(tmp))
    w.run_once()
    assert "MISSING TOOLS" in w.store.get(tid)["plan"]
    w.store.approve(tid)
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "needs_attention" and "MCP server 'image'" in t["result"]
    w.flows["coding"].mcp_servers = ["memory", "git", "image"]
    w.store.approve(tid)                                     # tools fixed; approve again
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "needs_attention" and "could not install" in t["result"]
    assert not [c for c in run.calls if c[0] == "execute"]  # no step ran


def test_planning_model_missing_stops_before_planning(env):
    tmp, installed = env
    run = Runner()
    w = worker(tmp, run, lambda *a, **k: None)
    tid = w.store.submit("divide", "test", str(tmp))
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "needs_attention" and "models install qwen3.8-27b" in t["result"] and not run.calls


# ---------- KV parking ----------

def test_kv_cache_parks_per_session_step_and_model(tmp_path):
    posts = []

    def post(model, action, filename):
        posts.append((model, action, filename))
        if action == "save":
            (tmp_path / filename).write_bytes(b"x" * 600)
        return {"n_saved": 5, "n_restored": 5}
    kv = KVCache(tmp_path, max_gb=1500 / 2**30, post=post)
    assert kv.restore("s1", "m", "plan") == ""             # nothing parked yet: plain prefill
    assert kv.save("s1", "m", "plan").startswith("parked 5 tokens as plan")
    kv.save("s1", "m", "step-1")
    assert kv.lookup("s1", "m", "plan") == "s1--plan--m.bin"        # a step wakes its own cache
    assert kv.lookup("s1", "m", "step-2") == "s1--step-1--m.bin"    # a new step wakes the master (latest)
    assert kv.lookup("s1", "other-model", "plan") == ""             # caches belong to one model
    assert kv.restore("s1", "m", "step-2").startswith("woke 5 tokens from s1--step-1--m.bin")
    kv.save("s2", "m")                                       # over the cap: the least recently used goes
    assert sorted(f.name for f in tmp_path.glob("*.bin")) == ["s1--step-1--m.bin", "s2--master--m.bin"]
    assert kv.lookup("s1", "m", "plan") == "s1--step-1--m.bin"    # its step cache was pruned: the master wakes
    assert "s1" in "\n".join(kv.report())
    kv.drop("s1"); kv.drop("s2")
    assert not list(tmp_path.glob("*.bin")) and kv.report() == ["nothing parked"]

    def broken(*a):
        raise OSError("server down")
    assert "skipped" in KVCache(tmp_path, post=broken).save("s3", "m")   # never fails a task


def test_compiled_flow_compresses_at_30k(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "HOMES", tmp_path / "homes")
    home = flowlib.compile_flow(flowlib.load_flows(REPO_FLOWS)["coding"], REPO_FLOWS)
    from ariadne import yamlio
    cfg = yamlio.safe_load((home / "config.yaml").read_text())
    assert cfg["model"]["context_length"] == 65536
    assert cfg["compression"]["threshold_tokens"] == 30000 and cfg["auxiliary"]["compression"]["provider"] == "auto"
