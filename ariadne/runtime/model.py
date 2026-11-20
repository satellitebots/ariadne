"""The model call: one OpenAI-compatible /chat/completions request, tools included.

Ariadne talks to whatever `serving.endpoint()` says - llama-swap, Ollama, or a box on the LAN - so this is a plain
HTTP client, not a provider abstraction. `transport(url, body)` is injectable: tests script the model instead of
starting one.
"""
import json
import urllib.request

from .. import serving


class ModelError(RuntimeError):
    pass


def chat(messages, *, model, tools=None, base_url=None, timeout=600, temperature=0.0, transport=None):
    """{content, tool_calls: [{id, name, arguments}], raw}. Raises ModelError, never returns a half-parsed reply."""
    url = (base_url or serving.endpoint()).rstrip("/") + "/chat/completions"
    body = {"model": model, "messages": messages, "temperature": temperature, "stream": False}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if transport is not None:
        reply = transport(url, body)
    else:
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                reply = json.loads(r.read())
        except Exception as e:  # connection, timeout, non-200, bad JSON: one error, with the address
            raise ModelError(f"{url} did not answer: {e}")
    try:
        msg = reply["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ModelError(f"the model server returned no message: {str(reply)[:300]}")
    calls = []
    for c in msg.get("tool_calls") or []:
        fn = c.get("function") or {}
        args = fn.get("arguments")
        try:
            parsed = json.loads(args) if isinstance(args, str) else (args or {})
        except json.JSONDecodeError:
            parsed = {"__bad_arguments__": str(args)[:500]}          # the loop reports it; the model can retry
        calls.append({"id": c.get("id") or f"call_{len(calls) + 1}", "name": fn.get("name") or "",
                      "arguments": parsed})
    return {"content": (msg.get("content") or "").strip(), "tool_calls": calls, "raw": msg}
