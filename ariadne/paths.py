"""Where Ariadne keeps things. Code lives in the repo; runtime state under .ariadne/ (gitignored)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get("ARIADNE_STATE") or ROOT / ".ariadne")
FLOWS_DIR = Path(os.environ.get("ARIADNE_FLOWS") or ROOT / "flows")
PLUGINS_DIR = ROOT / "plugins"
HOMES = STATE / "homes"          # one generated Hermes home per flow (the worker)
LOGS = STATE / "logs"
TASKS_DB = STATE / "tasks.db"
MEMORY_DB = STATE / "memory.db"  # the durable shared memory
PYTHON = Path(sys.executable)
HERMES_EXE = ROOT / ".venv" / "Scripts" / "hermes.exe"
LLM_BASE_URL = os.environ.get("ARIADNE_LLM_URL", "http://127.0.0.1:8090/v1")


def ensure():
    for d in (STATE, HOMES, LOGS):
        d.mkdir(parents=True, exist_ok=True)
