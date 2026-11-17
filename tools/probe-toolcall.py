"""Probe: does an OpenAI-compatible endpoint return structured tool_calls for a model?
Usage: .venv\\Scripts\\python.exe tools\\probe-toolcall.py <model> [base_url] [n]
Prints one line per try: tool_calls present?, tool name, args, seconds.
"""
import json, sys, time, urllib.request

model = sys.argv[1]
base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:11434/v1"
n = int(sys.argv[3]) if len(sys.argv) > 3 else 3
tools = [{"type": "function", "function": {
    "name": "read_file", "description": "Read a text file and return its contents.",
    "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}]
body = {"model": model, "tools": tools, "messages": [
    {"role": "user", "content": "Read C:\\temp\\notes.txt and tell me the code word in it."}]}
ok = 0
for i in range(n):
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    msg = json.load(urllib.request.urlopen(req, timeout=300))["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    ok += bool(calls)
    desc = f"{calls[0]['function']['name']} {calls[0]['function']['arguments']}" if calls else repr((msg.get("content") or "")[:80])
    print(f"{model} try{i+1}: tool_calls={bool(calls)} {desc} {time.time()-t:.1f}s")
print(f"{model}: {ok}/{n} structured tool calls")
