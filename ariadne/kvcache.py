"""Park and resume a session's KV cache on a model (llama-server slot save/restore, reached through llama-swap).

Swapping models throws the KV cache away, so the next run on a model pays prefill again. That is accepted. What we
avoid is paying it twice for the same session: after a run the worker saves the model's slot to disk under the
session's name ("sleep"); before the next run of that session on that model it restores it, and llama-server's
prefix match skips prefill for everything the conversation already had. A different session restores its own file,
or starts clean. Best effort: any failure means an ordinary prefill, never a failed task.
"""
import json
import os
import re
import urllib.request

from . import paths

KV_DIR = paths.STATE / "kv"
MAX_GB = float(os.environ.get("ARIADNE_KV_MAX_GB", "20"))


def _name(session, model):
    return f"{re.sub(r'[^A-Za-z0-9._-]+', '_', session)[:80]}--{model}.bin"


def _post(model, action, filename, timeout=300):
    base = paths.LLM_BASE_URL.removesuffix("/v1").rstrip("/")
    req = urllib.request.Request(f"{base}/upstream/{model}/slots/0?action={action}",
                                 data=json.dumps({"filename": filename}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


class KVCache:
    def __init__(self, kv_dir=None, max_gb=MAX_GB, post=_post):
        self.dir, self.max_bytes, self.post = kv_dir or KV_DIR, max_gb * 2**30, post

    def restore(self, session, model):
        """Load the session's saved cache into the model's slot. Returns a note for the event log, or ''."""
        f = self.dir / _name(session, model)
        if not session or not f.exists():
            return ""
        try:
            r = self.post(model, "restore", f.name)
            os.utime(f)
            return f"restored {r.get('n_restored', '?')} tokens"
        except Exception as e:  # different build, model changed, server down: plain prefill
            return f"restore skipped ({type(e).__name__})"

    def save(self, session, model):
        if not session:
            return ""
        self.dir.mkdir(parents=True, exist_ok=True)
        try:
            r = self.post(model, "save", _name(session, model))
        except Exception as e:
            return f"save skipped ({type(e).__name__})"
        self.prune()
        return f"saved {r.get('n_saved', '?')} tokens"

    def drop(self, session):
        """Forget a finished session's caches."""
        for f in self.dir.glob(_name(session, "*")) if self.dir.exists() else []:
            f.unlink(missing_ok=True)

    def prune(self):
        """Keep the newest caches under the size cap (least recently used go first)."""
        files = sorted(self.dir.glob("*.bin"), key=lambda f: f.stat().st_mtime, reverse=True)
        total = 0
        for f in files:
            total += f.stat().st_size
            if total > self.max_bytes:
                f.unlink(missing_ok=True)


class NoKVCache:
    def restore(self, session, model):
        return ""

    def save(self, session, model):
        return ""

    def drop(self, session):
        pass
