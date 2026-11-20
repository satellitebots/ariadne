"""Model servers: where inference happens, chosen by Ariadne and stored in the repo.

Three kinds (docs/MODELS.md): our own pinned `llama-server`, a local `ollama`, or a `remote` OpenAI-compatible /
Ollama endpoint on the LAN. One is active at a time. The choice is committed defaults (`serving/servers.yaml`) plus
a machine-local override (`.ariadne/servers.local.yaml`, gitignored) - never a Hermes config, never a cloud URL:
every address is checked by `local_only` before it is used or saved.

`endpoint()` is the one answer to "where is inference": llm, the KV cache, image generation, jobs and the compiled
flow homes all ask it, so a server chosen here really serves the run (B3) instead of only being reported.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from . import local_only, paths, yamlio

KINDS = ("llama-server", "ollama", "remote")
SERVERS_FILE = paths.ROOT / "serving" / "servers.yaml"
LOCAL_FILE = paths.STATE / "servers.local.yaml"
DEFAULT = {"kind": "llama-server", "url": "http://127.0.0.1:8090", "name": "this machine"}
OLLAMA_URL = "http://127.0.0.1:11434"


class ServingError(RuntimeError):
    pass


def _read(path):
    if not Path(path).exists():
        return {}
    try:
        return yamlio.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception as e:
        raise ServingError(f"{path} cannot be read: {e}")


def servers():
    """The registered servers: committed defaults, then this machine's."""
    cfg = _read(SERVERS_FILE)
    rows = {s["kind"]: s for s in cfg.get("servers", []) if isinstance(s, dict) and s.get("kind")}
    out = {k: dict(DEFAULT) for k in KINDS}
    out["ollama"].update({"url": OLLAMA_URL, "name": "ollama on this machine"})
    out["remote"].update({"url": "", "name": "a server on the network"})
    for k, v in rows.items():
        if k in out:
            out[k].update(v)
    return out


def active():
    """The server inference goes to. The machine-local override wins; otherwise the repo default."""
    local = _read(LOCAL_FILE)
    srv = dict(local.get("active") or DEFAULT)
    if srv.get("kind") not in KINDS:
        raise ServingError(f"unknown server kind '{srv.get('kind')}'; expected one of {', '.join(KINDS)}")
    if srv["kind"] == "remote" and not (srv.get("url") or "").strip():
        raise ServingError("the active server is 'remote' but no URL is registered; run `ariadne server remote <url>`")
    check_url(srv)
    return srv


def check_url(srv):
    """The local-only lock, applied to the server itself rather than only to a provider config."""
    url = (srv.get("url") or "").strip()
    if not url:
        return
    host = local_only.host_of(url)
    if not local_only.is_lan_host(host):
        raise ServingError(f"{url} is not this machine or the LAN; Ariadne does not use cloud inference "
                           f"(add the host to ARIADNE_ALLOW_HOSTS only if it really is on your network)")


def endpoint(srv=None):
    """The OpenAI-compatible base URL (…/v1) every model call goes to: the active server, or ARIADNE_LLM_URL.

    One function answers "where is inference", and it is checked by the same lock as the registry: a LAN GPU box
    serves a run only because this is what `llm`, the KV cache, image generation and the compiled flow homes read.
    """
    override = os.environ.get("ARIADNE_LLM_URL", "").strip()
    if override:
        check_url({"url": override})
        return override.rstrip("/")
    srv = srv or active()
    check_url(srv)   # a server passed in explicitly gets the same lock as the registered one
    url = (srv.get("url") or "").rstrip("/")
    if not url:
        raise ServingError("the active server has no URL; run `ariadne server remote <url>` or `ariadne server setup`")
    return url if url.endswith("/v1") else url + "/v1"


def base(srv=None):
    """The same server without /v1, for its own endpoints (/unload, /health, /api/*, /upstream/*)."""
    return endpoint(srv).removesuffix("/v1").rstrip("/")


def _get_json(url, timeout=5):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def probe(srv=None, timeout=5):
    """What the server is and which approved models it already has. Raises ServingError if nothing answers."""
    srv = srv or active()
    url = (srv.get("url") or "").rstrip("/")
    if not url:
        raise ServingError("this server has no URL")
    check_url(srv)
    try:
        data = _get_json(f"{url}/api/tags", timeout)
        return {"kind": "ollama", "url": url, "models": [m.get("name") for m in data.get("models", [])]}
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        pass
    try:
        data = _get_json(f"{url}/v1/models", timeout)
        return {"kind": "openai-compatible", "url": url, "models": [m.get("id") for m in data.get("data", [])]}
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as e:
        raise ServingError(f"nothing answered at {url} ({e}); is the server running and reachable?")


def use(kind, url="", name=""):
    """Make a server active, after the lock and a live probe have accepted it."""
    if kind not in KINDS:
        raise ServingError(f"unknown server kind '{kind}'; expected one of {', '.join(KINDS)}")
    srv = servers()[kind]
    if url:
        srv["url"] = url.strip()
    if name:
        srv["name"] = name.strip()
    check_url(srv)
    found = probe(srv) if kind != "llama-server" or srv.get("url") else None
    if found:
        srv["url"] = found["url"]
    paths.STATE.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(yamlio.safe_dump({"active": srv}), encoding="utf-8")
    return srv, found


def reconcile(srv=None):
    """The approved catalog against what the active server actually has: available, fetchable, unavailable."""
    from . import models as modellib
    srv = srv or active()
    try:
        have = set(probe(srv).get("models") or [])
    except ServingError:
        have = set()
    cat = modellib.load()
    out = {"available": [], "fetchable": [], "unavailable": []}
    for m in cat.models.values():
        names = {m.name, *(m.ollama.split("/") if getattr(m, "ollama", "") else [])}
        if names & have or m.installed():
            out["available"].append(m.name)
        elif getattr(m, "weights", None) or getattr(m, "ollama", None):
            out["fetchable"].append(m.name)
        else:
            out["unavailable"].append(m.name)
    return out


def main(argv):
    argv = list(argv or [])
    if not argv or argv[0] in ("show", "status"):
        try:
            srv = active()
        except ServingError as e:
            print(f"no usable model server: {e}")
            return 1
        print(f"active: {srv['kind']}  {srv.get('url') or '-'}  ({srv.get('name') or '-'})")
        try:
            found = probe(srv)
            print(f"answers as {found['kind']}; models: {', '.join(found['models'][:12]) or '(none)'}")
        except ServingError as e:
            print(f"probe: {e}")
        return 0
    if argv[0] == "list":
        for kind, s in servers().items():
            mark = "*" if kind == active().get("kind") else " "
            print(f"{mark} {kind:<13} {s.get('url') or '-':<34} {s.get('name') or ''}")
        return 0
    if argv[0] == "setup":
        return _setup(argv[1:])
    if argv[0] in KINDS:
        url = argv[1] if len(argv) > 1 else ""
        try:
            srv, found = use(argv[0], url)
        except ServingError as e:
            print(str(e))
            return 1
        print(f"active server: {srv['kind']} {srv.get('url') or '-'}")
        if found:
            print(f"it answers as {found['kind']}; {len(found['models'])} model(s) already there")
        return 0
    print(__doc__)
    return 1


def _setup(rest):
    """Probe, then ask. Non-interactive callers pass --local llama-server|ollama or --remote URL."""
    flags = dict((a.lstrip("-"), rest[i + 1]) for i, a in enumerate(rest)
                 if a.startswith("--") and i + 1 < len(rest))
    if flags.get("remote"):
        return main(["remote", flags["remote"]])
    if flags.get("local"):
        return main([flags["local"]])
    print("Looking for a model server on this machine...")
    for kind, url in (("ollama", OLLAMA_URL), ("llama-server", DEFAULT["url"])):
        try:
            found = probe({"kind": kind, "url": url})
            print(f"  found {found['kind']} at {url} with {len(found['models'])} model(s)")
            srv, _ = use(kind, url)
            print(f"  using it. Change any time with `ariadne server <{'|'.join(KINDS)}> [url]`.")
            print(f"  active: {srv['kind']} {srv['url']}")
            return 0
        except ServingError:
            print(f"  no {kind} at {url}")
    print("\nNothing is serving models here yet. Choose one:")
    print("  1. use the runtime in this repo (our pinned llama-server; weights download on sign-off)")
    print("  2. install Ollama here            (ariadne install --system)")
    print("  3. point at a server on my network (ariadne server remote http://<lan-host>:11434)")
    try:
        choice = input("1/2/3 [1]: ").strip() or "1"
    except EOFError:
        choice = "1"
    if choice == "2":
        from . import deps
        return deps.install(system=True)
    if choice == "3":
        try:
            url = input("URL: ").strip()
        except EOFError:
            url = ""
        return main(["remote", url]) if url else 1
    paths.STATE.mkdir(parents=True, exist_ok=True)
    LOCAL_FILE.write_text(yamlio.safe_dump({"active": dict(DEFAULT)}), encoding="utf-8")
    print(f"active: {DEFAULT['kind']} {DEFAULT['url']} - weights are fetched when a signed-off plan needs them.")
    return 0
