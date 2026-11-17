"""Direct calls to the local OpenAI-compatible endpoint (llama-swap). Used for routing, which is one short call
and does not need a full Hermes run."""
import json
import re
import urllib.request

from . import paths


def chat(model, messages, max_tokens=64, timeout=180, base_url=None):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request((base_url or paths.LLM_BASE_URL).rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    text = data["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def is_up(base_url=None, timeout=3):
    try:
        with urllib.request.urlopen((base_url or paths.LLM_BASE_URL).rstrip("/") + "/models", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False
