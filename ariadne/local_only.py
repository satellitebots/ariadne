"""Local-only inference: the model may use the internet, but never someone else's tokens.

The rule is not "no network". A local model may search the web, fetch pages, download weights. The rule is that
**inference** must be served by this machine or this network, and no API key may be configured, so a run cannot
spend money. That is a property of the provider configuration, enforced before any model starts - a socket guard
that blocks all egress would only break the tools the model is allowed to use.

Raises LocalOnlyError with every violation found, so `ariadne doctor` can explain rather than guess.
"""
import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from . import yamlio
from .paths import GATEWAY_HOME

# A provider name with no base_url would use the vendor's cloud endpoint. With a local base_url, the name is just a
# label, so presence of base_url is what decides.
CLOUD_PROVIDERS = {"openai", "anthropic", "openrouter", "google", "gemini", "deepseek", "groq", "mistral",
                   "together", "xai", "cohere", "fireworks", "perplexity", "azure", "bedrock", "vertex",
                   "moonshot", "zhipu", "qwen-cloud", "dashscope"}
LOCAL_PROVIDERS = {"ollama", "llamacpp", "llama.cpp", "vllm", "lmstudio", "local", "custom", "openai-compatible",
                   "tabbyapi", "text-generation-webui", "koboldcpp"}
SECTIONS = ("model", "providers", "custom_providers", "fallback_providers")
ALLOW_ENV = "ARIADNE_ALLOW_HOSTS"
LOCAL_SUFFIXES = (".localhost", ".lan", ".local", ".home.arpa", ".internal")


class LocalOnlyError(RuntimeError):
    pass


def allow_hosts():
    return {h.strip().lower() for h in os.environ.get(ALLOW_ENV, "").split(",") if h.strip()}


def host_of(value):
    value = str(value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "http://" + value
    try:
        return (urlsplit(value).hostname or "").strip("[]").rstrip(".").lower()
    except ValueError:
        return ""


def is_lan_host(host):
    """Loopback, RFC1918/ULA, link-local, single-label LAN names, local suffixes, ARIADNE_ALLOW_HOSTS."""
    h = (host or "").strip("[]").rstrip(".").lower()
    if not h or h == "localhost" or h in allow_hosts():
        return True
    try:
        ip = ipaddress.ip_address(h.split("%")[0])
        return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified
    except ValueError:
        pass
    if "." not in h:
        return True
    return h.endswith(LOCAL_SUFFIXES)


def _entries(node, path=""):
    """Yield (path, value) for every provider-ish dict."""
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _entries(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _entries(v, f"{path}[{i}]")


def violations(cfg, environ=None):
    """Every way this configuration could spend tokens, as human sentences."""
    environ = os.environ if environ is None else environ
    out = []
    for section in SECTIONS:
        if section not in (cfg or {}):
            continue
        for path, node in _entries(cfg[section], section):
            if not isinstance(node, dict):
                continue
            base = node.get("base_url") or node.get("endpoint") or node.get("url")
            provider = str(node.get("provider") or node.get("name") or "").strip().lower()
            if base:
                h = host_of(base)
                if not is_lan_host(h):
                    out.append(f"{path}: base_url points at {h or base!r}, which is not this machine or the LAN")
            elif provider in CLOUD_PROVIDERS:
                out.append(f"{path}: provider '{provider}' has no base_url, so it would use the cloud endpoint")
            for key in ("api_key", "api-key", "apikey"):
                v = node.get(key)
                if isinstance(v, str) and v.strip():
                    out.append(f"{path}: {key} is set; Ariadne does not spend tokens on an API key")
            env_name = node.get("key_env") or node.get("api_key_env")
            if isinstance(env_name, str) and env_name.strip() and (environ.get(env_name.strip()) or "").strip():
                out.append(f"{path}: ${env_name.strip()} is set; Ariadne does not spend tokens on an API key")
    return out


def check_home(home=None):
    """Violations for the Hermes home's config.yaml; [] when it does not exist yet."""
    # Never inherit HERMES_HOME from the shell: when Ariadne is run from inside another Hermes, that variable points
    # at the assistant's home (which may have a cloud provider). Ariadne checks the home it will actually launch.
    home = Path(home or os.environ.get("ARIADNE_HOME") or GATEWAY_HOME)
    path = home / "config.yaml"
    if not path.exists():
        return []
    try:
        cfg = yamlio.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:  # a broken config is not silently treated as local
        return [f"{path}: cannot be read ({e})"]
    return violations(cfg)


def guard_home(home=None):
    bad = check_home(home)
    if bad:
        raise LocalOnlyError("local-only inference is not satisfied:\n  - " + "\n  - ".join(bad))
