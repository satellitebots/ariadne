"""The model index: deterministic verdicts from a described device, and the pulse's filter and cache with no network.

No GPU, no Hugging Face, no model: the device is a datum, the fetch is a function.
"""
import json

from ariadne import modelindex as mi
from ariadne.models import Catalog, Model


def device(vram=8.0, ram=32.0):
    return mi.Device(os="win32", arch="AMD64", cpu="Ryzen 7", cores=16, ram_gb=ram, vram_gb=vram,
                     gpu="RTX 3070", backend="cuda" if vram else "cpu", disk_free_gb=100.0)


def model(name, size, kind="agent", active_b=0):
    return Model(name=name, kind=kind, roles=["coding"], size_gb=size, active_b=active_b)


def catalog(*models):
    return Catalog(models={m.name: m for m in models}, defaults={"coding": models[0].name}, resources="shared")


def test_a_model_lands_in_one_of_three_tiers():
    rows = {v.name: v for v in mi.shortlist(catalog(model("small", 4), model("big", 20), model("huge", 40)),
                                            device())}
    assert rows["small"].tier == "gpu" and "fits in 8 GB VRAM" in rows["small"].reason
    assert rows["big"].tier == "hybrid" and "CPU" in rows["big"].reason
    assert rows["huge"].tier == "no" and "allows" in rows["huge"].reason


def test_the_overhead_is_counted():
    v = mi.verdict(model("small", 4), device())
    assert v.need_gb == 5.5 and v.size_gb == 4


def test_a_moe_model_says_why_offload_hurts_less():
    v = mi.verdict(model("moe", 20, active_b=3), device())
    assert v.tier == "hybrid" and "MoE" in v.reason


def test_available_is_the_shortlist_without_the_impossible_and_fast_first():
    cat = catalog(model("slow", 20), model("fast", 4), model("never", 40))
    names = [v.name for v in mi.available(cat, device())]
    assert names == ["fast", "slow"]


def test_a_cpu_only_machine_has_no_gpu_tier():
    rows = [mi.verdict(model("small", 4), device(vram=0))]
    assert rows[0].tier == "hybrid" and "CPU" in rows[0].reason


def test_the_report_names_the_device_and_every_tier():
    text = mi.report(catalog(model("small", 4), model("big", 20), model("huge", 40)), device())
    assert "RTX 3070" in text and "fits in VRAM" in text and "cannot run here" in text
    assert "3 in the catalog, 2 can run" in text


def test_the_pulse_filters_by_fit_sorts_by_downloads_and_limits(tmp_path):
    rows = [
        {"id": "tiny", "pipeline_tag": "text-generation", "downloads": 10, "likes": 1,
         "safetensors": {"total": 6_700_000_000}},
        {"id": "big", "pipeline_tag": "text-generation", "downloads": 999, "likes": 9,
         "safetensors": {"total": 70_000_000_000}},
        {"id": "mid", "pipeline_tag": "text-generation", "downloads": 500, "likes": 5,
         "safetensors": {"total": 20_000_000_000}},
        {"id": "unknown-size", "pipeline_tag": "text-generation", "downloads": 800},
    ]
    got, note = mi.pulse("agent", device(), fetch=lambda task: rows, cache=tmp_path / "pulse.json")
    assert note == "" and [r["id"] for r in got] == ["mid", "tiny"]       # big never fits, unknown skipped
    assert got[0]["tier"] == "hybrid" and got[1]["tier"] == "gpu"
    assert mi.pulse("agent", device(), fetch=lambda task: rows, cache=tmp_path / "pulse.json", limit=1)[0][0]["id"] == "mid"


def test_the_pulse_cache_holds_until_refreshed(tmp_path):
    calls = []

    def fetch(task):
        calls.append(task)
        return [{"id": "a", "pipeline_tag": task, "downloads": 1, "safetensors": {"total": 1_000_000_000}}]

    cache = tmp_path / "pulse.json"
    assert mi.pulse("agent", device(), fetch=fetch, cache=cache)[0][0]["id"] == "a"
    assert mi.pulse("agent", device(), fetch=fetch, cache=cache)[0][0]["id"] == "a"
    assert len(calls) == 1                                                   # second call read the cache
    assert json.loads(cache.read_text(encoding="utf-8"))["task"] == "text-generation"
    mi.pulse("agent", device(), fetch=fetch, cache=cache, refresh=True)
    assert len(calls) == 2                                                   # --refresh polls again


def test_a_network_failure_is_a_note_not_a_crash(tmp_path):
    def boom(task):
        raise OSError("no route to host")

    got, note = mi.pulse("agent", device(), fetch=boom, cache=tmp_path / "pulse.json", refresh=True)
    assert got == [] and "did not answer" in note and "no route to host" in note


def test_the_catalog_and_the_index_agree_on_whether_a_model_fits():
    cat = catalog(model("edge", 30.5))
    cat.budget = {"max_model_gb": 31.9}                 # the figure resources.budget reports for 8 GB + 31.9 GB RAM
    assert cat.fits(cat.models["edge"]) is False        # 32.0 GB once the overhead is counted
    assert mi.verdict(cat.models["edge"], device(ram=31.9)).tier == "no"
