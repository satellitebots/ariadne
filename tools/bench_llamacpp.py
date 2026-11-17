"""Benchmark a running llama-server (or llama-swap) with the same synthetic prompt as bench_ollama.py.

Usage: .venv\\Scripts\\python.exe tools\\bench_llamacpp.py <base_url> [--model alias] [--prompt-tokens 15000] [--gen 128]
Uses the OpenAI-compatible /v1/chat/completions; llama-server adds a 'timings' object with server-side
prompt and generation rates. Reports wall time too (includes any model load / swap by llama-swap).
"""
import argparse, json, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("base"); ap.add_argument("--model", default="x")
ap.add_argument("--prompt-tokens", type=int, default=15000); ap.add_argument("--gen", type=int, default=128)
a = ap.parse_args()
filler = " ".join(f"line {i}: the quick brown fox jumps over the lazy dog." for i in range(a.prompt_tokens // 12))
body = {"model": a.model, "temperature": 0, "max_tokens": a.gen, "cache_prompt": False,
        "messages": [{"role": "user", "content": filler + "\n\nIn one sentence, what animal jumps in the text above?"}]}
req = urllib.request.Request(a.base.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                             headers={"Content-Type": "application/json"})
t = time.time()
r = json.load(urllib.request.urlopen(req, timeout=1800))
wall = time.time() - t
tm = r.get("timings", {})
print(json.dumps({"model": a.model, "wall_s": round(wall, 1), "prompt_tokens": tm.get("prompt_n"),
                  "prompt_tok_s": round(tm.get("prompt_per_second", 0), 1), "gen_tokens": tm.get("predicted_n"),
                  "gen_tok_s": round(tm.get("predicted_per_second", 0), 1),
                  "answer": (r["choices"][0]["message"].get("content") or "")[:80]}))
