"""Direct calls to the model endpoint Ariadne is serving from (llama-swap, Ollama, or a box on the LAN).

Used for routing, which is one short call and does not need a full Hermes run. The address is never assumed: it
comes from `serving.endpoint()`, so switching the active server changes what these calls reach (B3).
"""
import json
import re
import urllib.request

from . import serving


def _base(base_url=None):
    return (base_url or serving.endpoint()).rstrip("/")


def chat(model, messages, max_tokens=64, timeout=180, base_url=None, temperature=0):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(_base(base_url) + "/chat/completions",
                                 data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read())
    text = data["choices"][0]["message"].get("content") or ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def is_up(base_url=None, timeout=3):
    try:
        with urllib.request.urlopen(_base(base_url) + "/models", timeout=timeout) as r:
            return r.status == 200
    except (OSError, serving.ServingError):
        return False
