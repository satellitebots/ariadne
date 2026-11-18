"""KV cache parking: a session's cache sleeps on disk while other work uses the GPU, and wakes when it comes back.

Local models on one GPU swap all the time (planner, coder, writer; task A, task B). Every swap throws the KV
cache away, and the next turn pays prefill for the whole conversation again - minutes for 70K tokens on a 27B
partly on the CPU. Ariadne parks instead:

  after a run   the model's slot is saved to disk (llama-server slot save) under the session, the step
                (plan, step-1-3, ...) and the model, and becomes the session's "master" cache for that model
  before a run  the step's own cache is restored if it exists (re-running or retrying that step), else the
                session's master for that model; llama-server then skips prefill for the shared prefix

So switching tasks, swapping models between steps, or coming back to a conversation tomorrow costs a disk read,
not a prefill. A cache belongs to one model (K and V are computed by that model's weights; another model cannot
use them); the conversation itself is shared across models through the Hermes session. Best effort: a failed
save or restore means an ordinary prefill, never a failed task. ARIADNE_KV=off turns it off.
"""
import json
import os
import re
import time
import urllib.request

from . import paths

KV_DIR = paths.STATE / "kv"
MAX_GB = float(os.environ.get("ARIADNE_KV_MAX_GB", "40"))
MASTER = "master"


def _slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(s))[:80]


def _post(model, action, filename, timeout=600):
    base = paths.LLM_BASE_URL.removesuffix("/v1").rstrip("/")
    req = urllib.request.Request(f"{base}/upstream/{model}/slots/0?action={action}",
                                 data=json.dumps({"filename": filename}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


class KVCache:
    """Index (kv/index.json): {session: {model: {"master": file, "steps": {scope: file}}}}."""

    def __init__(self, kv_dir=None, max_gb=MAX_GB, post=_post):
        self.dir, self.max_bytes, self.post = kv_dir or KV_DIR, max_gb * 2**30, post

    # ---------- index ----------
    def _index(self):
        try:
            return json.loads((self.dir / "index.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self, idx):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "index.json").write_text(json.dumps(idx, indent=1, sort_keys=True), encoding="utf-8")

    def lookup(self, session, model, scope=MASTER):
        """The file to wake for (session, step, model): the step's own cache, else the session's master."""
        entry = self._index().get(session, {}).get(model, {})
        for name in ([entry.get("steps", {}).get(scope)] if scope != MASTER else []) + [entry.get(MASTER)]:
            if name and (self.dir / name).exists():
                return name
        return ""

    # ---------- wake / sleep ----------
    def restore(self, session, model, scope=MASTER):
        """Wake the cache into the model's slot. Returns a note for the task's event log, or ''."""
        name = self.lookup(session, model, scope) if session else ""
        if not name:
            return ""
        t = time.time()
        try:
            r = self.post(model, "restore", name)
        except Exception as e:  # different llama.cpp build, model file changed, server down: plain prefill
            return f"wake skipped ({type(e).__name__})"
        self._touch(self.dir / name)
        return f"woke {r.get('n_restored', '?')} tokens from {name} in {time.time() - t:.1f}s"

    def save(self, session, model, scope=MASTER):
        """Park the model's slot under (session, step); it becomes the session's master for this model."""
        if not session:
            return ""
        self.dir.mkdir(parents=True, exist_ok=True)
        name = f"{_slug(session)}--{_slug(scope)}--{_slug(model)}.bin"
        t = time.time()
        try:
            r = self.post(model, "save", name)
        except Exception as e:
            return f"park skipped ({type(e).__name__})"
        if (self.dir / name).exists():
            self._touch(self.dir / name)
        idx = self._index()
        entry = idx.setdefault(session, {}).setdefault(model, {"steps": {}})
        entry.setdefault("steps", {})[scope] = name
        entry[MASTER] = name
        self._write(idx)
        self.prune()
        return f"parked {r.get('n_saved', '?')} tokens as {scope} in {time.time() - t:.1f}s"

    def _touch(self, path):
        """Mark a cache most recently used: strictly newer than every other one, so ties from a coarse or lazily
        updated file clock cannot reorder the LRU."""
        newest = max((f.stat().st_mtime_ns for f in self.dir.glob("*.bin") if f != path), default=0)
        t = max(time.time_ns(), newest + 1_000_000)
        os.utime(path, ns=(t, t))

    # ---------- housekeeping ----------
    def drop(self, session):
        """Forget a session's caches (all steps, all models)."""
        idx = self._index()
        for model in idx.pop(session, {}).values():
            for name in set((model.get("steps") or {}).values()) | {model.get(MASTER)}:
                if name:
                    (self.dir / name).unlink(missing_ok=True)
        if self.dir.exists():
            self._write(idx)

    def prune(self):
        """Keep the newest caches under the size cap; the least recently woken go first."""
        files = sorted(self.dir.glob("*.bin"), key=lambda f: f.stat().st_mtime, reverse=True)
        total, gone = 0, set()
        for f in files:
            total += f.stat().st_size
            if total > self.max_bytes:
                f.unlink(missing_ok=True)
                gone.add(f.name)
        if gone:
            idx = self._index()
            for models in idx.values():
                for e in models.values():
                    e["steps"] = {k: v for k, v in (e.get("steps") or {}).items() if v not in gone}
                    if e.get(MASTER) in gone:
                        e[MASTER] = next(iter(e["steps"].values()), "")
            self._write(idx)

    def report(self):
        """Lines for `python -m ariadne kv`: what is parked, per session and model."""
        lines = []
        for session, models in sorted(self._index().items()):
            for model, e in sorted(models.items()):
                files = set((e.get("steps") or {}).values()) | {e.get(MASTER)}
                size = sum((self.dir / n).stat().st_size for n in files if n and (self.dir / n).exists())
                lines.append(f"{session}  {model}  steps: {', '.join(e.get('steps') or {}) or '-'}  "
                             f"{size / 2**30:.2f} GB")
        return lines or ["nothing parked"]


class NoKVCache:
    def restore(self, session, model, scope=MASTER):
        return ""

    def save(self, session, model, scope=MASTER):
        return ""

    def drop(self, session):
        pass


def default():
    return NoKVCache() if os.environ.get("ARIADNE_KV", "").lower() in ("off", "0", "false") else KVCache()


def main(argv):
    """python -m ariadne kv [list | drop SESSION]"""
    kv = KVCache()
    if not argv or argv[0] == "list":
        print("\n".join(kv.report()))
        return 0
    if argv[0] == "drop" and len(argv) == 2:
        kv.drop(argv[1])
        print(f"dropped {argv[1]}")
        return 0
    print(main.__doc__)
    return 2
