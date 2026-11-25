"""Model choice, sessions and KV parking: the catalog, a model per step in the backbrief, sign-off locks it, nothing
runs until every chosen model and tool is there (no weights, no network, no Hermes)."""
import json

import pytest

from ariadne import flows as flowlib
from ariadne import models as modellib
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


