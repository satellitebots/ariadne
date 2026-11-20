"""Machine-local settings, in the repo's own state, not in a Hermes home.

`.ariadne/config.yaml` (or `ARIADNE_CONFIG`) holds the switches a person sets for this machine. Everything has a
safe default; a key not present means the default, and a broken file means the defaults rather than a crash.

`orchestrator_resident` (default False): keep the defining model loaded after sign-off so it can plan and hold
multiple sessions at once. Default is the memory-efficient path - the planner sleeps and the worker takes the card.
Turning it on trades VRAM for concurrency, which we may be able to prove correct but not to load-test on this
hardware.
"""
import os
from pathlib import Path

from . import yamlio
from .paths import STATE

DEFAULTS = {"orchestrator_resident": False}


def path() -> Path:
    return Path(os.environ.get("ARIADNE_CONFIG") or STATE / "config.yaml")


def _read() -> dict:
    p = path()
    if not p.exists():
        return dict(DEFAULTS)
    try:
        raw = yamlio.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return dict(DEFAULTS)
    return {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}


def get(key: str):
    return _read().get(key, DEFAULTS.get(key))


def set(key: str, value) -> None:
    """Write one switch; unknown keys are never persisted, so a typo cannot invent a setting."""
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting {key!r}; known: {', '.join(sorted(DEFAULTS))}")
    data = dict(DEFAULTS, **{k: v for k, v in _read().items() if k in DEFAULTS})
    data[key] = value
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yamlio.safe_dump(data), encoding="utf-8")