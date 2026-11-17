"""Baseline benchmark of models served by Ollama (native API, so timings come from the server).

Usage: .venv\\Scripts\\python.exe tools\\bench_ollama.py <model> [--prompt-tokens 15000] [--gen 128] [--embed]
Per model: cold load seconds, prompt-eval tok/s on a Hermes-sized prompt, generation tok/s, and the
resident size + CPU/GPU split reported by /api/ps. Unloads the model first so load time is cold.
Prompt text is synthetic filler (deterministic), sized from the server's own prompt_eval_count.
"""
import argparse, json, time, urllib.request

BASE = "http://localhost:11434"


def call(path, body=None, timeout=900):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def ps(model):
    for m in call("/api/ps").get("models", []):
        if m["name"].split(":")[0] == model.split(":")[0] or m["name"] == model:
            size, vram = m.get("size", 0), m.get("size_vram", 0)
            return {"resident_gb": round(size / 1e9, 2), "vram_gb": round(vram / 1e9, 2),
                    "gpu_pct": round(100 * vram / size) if size else None, "ctx": m.get("context_length")}
    return {}


ap = argparse.ArgumentParser()
ap.add_argument("model"); ap.add_argument("--prompt-tokens", type=int, default=15000)
ap.add_argument("--gen", type=int, default=128); ap.add_argument("--embed", action="store_true")
a = ap.parse_args()

call("/api/generate", {"model": a.model, "keep_alive": 0}) if not a.embed else None  # unload -> cold start
time.sleep(2)
if a.embed:
    t = time.time()
    r = call("/api/embed", {"model": a.model, "input": ["warm up"], "keep_alive": "5m"})
    load = r.get("load_duration", 0) / 1e9
    texts = [f"def function_{i}(x): return x * {i}  # sample code line {i}" for i in range(256)]
    t = time.time(); call("/api/embed", {"model": a.model, "input": texts, "keep_alive": "5m"})
    dt = time.time() - t
    print(json.dumps({"model": a.model, "kind": "embed", "load_s": round(load, 2),
                      "embeds_per_s": round(len(texts) / dt, 1), **ps(a.model)}))
else:
    filler = " ".join(f"line {i}: the quick brown fox jumps over the lazy dog." for i in range(a.prompt_tokens // 12))
    prompt = filler + "\n\nIn one sentence, what animal jumps in the text above?"
    r = call("/api/generate", {"model": a.model, "prompt": prompt, "stream": False, "keep_alive": "5m",
                                "options": {"num_predict": a.gen, "temperature": 0}})
    out = {"model": a.model, "kind": "chat", "load_s": round(r["load_duration"] / 1e9, 2),
           "prompt_tokens": r["prompt_eval_count"],
           "prompt_tok_s": round(r["prompt_eval_count"] / (r["prompt_eval_duration"] / 1e9), 1),
           "gen_tokens": r["eval_count"], "gen_tok_s": round(r["eval_count"] / (r["eval_duration"] / 1e9), 1),
           **ps(a.model)}
    print(json.dumps(out))
