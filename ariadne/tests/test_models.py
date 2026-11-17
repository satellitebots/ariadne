"""Model choice: the catalog, a model per step in the backbrief, sign-off locks it, nothing runs until every chosen
model and tool is there (no weights, no network, no Hermes)."""
import json

import pytest

from ariadne import flows as flowlib
from ariadne import models as modellib
from ariadne import orchestrator as orch
from ariadne import paths
from ariadne.memory import Memory

REPO_FLOWS = paths.ROOT / "flows"
PLAN = """MISSION: add a divide function with a hero image and release notes
FLOW: coding
STEPS:
1. add divide() to calc.py - tools: file - model: qwen3.8-27b
2. write release notes prose - tools: file, text - model: fimbulvetr-11b
3. add tests - tools: file, terminal - model: qwen3.8-27b
4. render a banner - tools: image - model: z-image-turbo
5. review the layout - tools: file - model: gemma-4-12b
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

    def __call__(self, flow, phase, prompt, ws, tid, model=None):
        self.calls.append((phase, model, prompt))
        return orch.RunResult(self.plan if phase == "plan" else (self.results.pop(0) if self.results else "ok"), 0, "log")


def worker(tmp, runner, installer, mcp_servers=None):
    flows = flowlib.load_flows(REPO_FLOWS)
    if mcp_servers is not None:
        flows["coding"].mcp_servers = mcp_servers
    flows["coding"].checks = []
    return orch.Worker(store=orch.Store(tmp / "t.db"), memory=Memory(tmp / "m.db"), flows=flows, runner=runner,
                       llm_chat=lambda m, msgs: "coding", installer=installer, on_installed=lambda: None)


# ---------- catalog ----------

def test_catalog_has_the_chosen_models_and_defaults():
    cat = modellib.load()
    assert cat.defaults["coding"] == "qwen3.8-27b" and cat.defaults["design"] == "gemma-4-12b"
    assert cat.defaults["writing"] == "fimbulvetr-11b" and cat.defaults["image"] == "z-image-turbo"
    assert cat.get("deepseek-v4.1-flash").roles == ["coding"]
    assert cat.get("fimbulvetr-11b").kind == "generate" and cat.get("z-image-turbo").kind == "image"
    for m in cat.models.values():
        assert m.ollama or all("repo" in p and ("file" in p or "dir" in p) for p in m.parts.values()), m.name
    with pytest.raises(modellib.ModelError):
        cat.get("nope")


def test_swap_entries_serve_text_models_only():
    e = modellib.swap_entries()
    assert "qwen3.8-27b" in e and "router" in e and "z-image-turbo" not in e
    assert "--fit on" in e["qwen3.8-27b"]["cmd"] and "-c 4096" in e["fimbulvetr-11b"]["cmd"]


def test_flow_model_must_be_an_agent(tmp_path):
    d = tmp_path / "flows" / "w"
    d.mkdir(parents=True)
    (d / "flow.yaml").write_text("name: w\ndescription: x\nwhen: y\nmodel: fimbulvetr-11b\n")
    with pytest.raises(flowlib.FlowError, match="agent"):
        flowlib.load_flows(tmp_path / "flows")


def test_fetch_pins_sha_on_first_fetch_and_refuses_a_changed_file(env, monkeypatch):
    tmp, _ = env
    sha = "a" * 64
    monkeypatch.setattr(modellib, "_hf_tree", lambda repo, path="": [{"path": "Fimbulvetr-11B-v2.Q4_K_M.gguf",
                                                                        "size": 10, "sha256": sha}])
    m = modellib.load().get("fimbulvetr-11b")
    (url, dest, got, size), = modellib.plan_fetch(m)
    assert got == sha and url.endswith("/resolve/main/Fimbulvetr-11B-v2.Q4_K_M.gguf")
    assert json.loads((tmp / "pins.json").read_text())["mradermacher/Fimbulvetr-11B-v2-GGUF/Fimbulvetr-11B-v2.Q4_K_M.gguf"] == sha
    monkeypatch.setattr(modellib, "_hf_tree", lambda repo, path="": [{"path": "Fimbulvetr-11B-v2.Q4_K_M.gguf",
                                                                        "size": 10, "sha256": "b" * 64}])
    with pytest.raises(modellib.ModelError, match="pinned"):
        modellib.plan_fetch(m)


# ---------- the model plan ----------

def test_backbrief_carries_a_model_per_step(env):
    cat, fl = modellib.load(), flowlib.load_flows(REPO_FLOWS)["coding"]
    mp = orch.parse_model_plan(PLAN.replace("model: gemma-4-12b", "model: gpt-9"), fl, cat)
    assert [s["model"] for s in mp["steps"]] == ["qwen3.8-27b", "fimbulvetr-11b", "qwen3.8-27b", "z-image-turbo",
                                                  "qwen3.8-27b"]
    assert "gpt-9" in mp["notes"][0]                       # unknown name -> the flow's model, and the backbrief says so
    assert orch.needed_servers(mp, cat) == ["image", "text"]
    groups = orch.step_groups(orch.parse_model_plan(PLAN, fl, cat), cat)
    assert [(a, [s["n"] for s in ss]) for a, ss in groups] == [("qwen3.8-27b", [1, 2, 3, 4]), ("gemma-4-12b", [5])]


def test_overrides(env):
    cat, fl = modellib.load(), flowlib.load_flows(REPO_FLOWS)["coding"]
    mp = orch.parse_model_plan(PLAN, fl, cat)
    mp2 = orch.apply_model_overrides(mp, "4=sd-turbo, 1=deepseek-v4.1-flash")
    assert mp2["steps"][3]["model"] == "sd-turbo" and mp2["steps"][0]["model"] == "deepseek-v4.1-flash"
    assert orch.apply_model_overrides(mp, {"all": "qwen3.5-9b"})["agent"] == "qwen3.5-9b"
    for bad in ("9=qwen3.5-9b", "1=nope", "1=embed"):
        with pytest.raises(orch.TaskError):
            orch.apply_model_overrides(mp, bad)


def test_drill_with_models_fetches_before_step_one_and_runs_each_group_on_its_model(env):
    tmp, installed = env
    installed.update({"qwen3.8-27b"})                       # the planner is there; the rest is fetched after sign-off
    fetched = []
    run = Runner()
    w = worker(tmp, run, lambda name, cat, log=print: (fetched.append(name), installed.add(name)),
               mcp_servers=["memory", "git", "image", "text"])
    tid = w.store.submit("divide", "test", str(tmp))
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "awaiting_signoff" and run.calls[0][1] == "qwen3.8-27b"
    assert "MODEL PLAN" in t["plan"] and "TO FETCH AFTER SIGN-OFF" in t["plan"] and "z-image-turbo" in t["plan"]
    assert "MODELS you may assign" in run.calls[0][2] and "fimbulvetr-11b" in run.calls[0][2]
    assert not fetched                                      # nothing is fetched before sign-off
    w.store.approve(tid, "5=qwen3.5-9b")
    assert json.loads(w.store.get(tid)["models"])["locked"]
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "done", t
    assert set(fetched) == {"fimbulvetr-11b", "z-image-turbo"}
    execs = [c for c in run.calls if c[0] == "execute"]
    assert [c[1] for c in execs] == ["qwen3.8-27b", "qwen3.5-9b"]
    assert "NOW DO STEPS 1, 2, 3, 4 ONLY" in execs[0][2] and "generate_text(model='fimbulvetr-11b'" in execs[0][2]
    assert "generate_image(model='z-image-turbo'" in execs[0][2] and "NOW DO STEP 5 ONLY" in execs[1][2]


def test_nothing_starts_until_tools_and_models_are_there(env):
    tmp, installed = env
    installed.update({"qwen3.8-27b"})
    run = Runner()

    def fail(name, cat, log=print):
        raise modellib.ModelError("disk full")
    w = worker(tmp, run, fail, mcp_servers=["memory", "git"])     # no image/text servers in the flow
    tid = w.store.submit("divide", "test", str(tmp))
    w.run_once()
    assert "MISSING TOOLS" in w.store.get(tid)["plan"]
    w.store.approve(tid)
    w.run_once()
    t = w.store.get(tid)
    assert t["status"] == "needs_attention" and "MCP server 'image'" in t["result"]
    w.flows["coding"].mcp_servers = ["memory", "git", "image", "text"]
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
