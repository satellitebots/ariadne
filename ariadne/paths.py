"""Where Ariadne keeps things, on Windows, Linux and macOS. Code lives in the repo; runtime state in .ariadne/."""
import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = Path(os.environ.get("ARIADNE_STATE") or ROOT / ".ariadne")
FLOWS_DIR = Path(os.environ.get("ARIADNE_FLOWS") or ROOT / "flows")
PLUGINS_DIR = ROOT / "plugins"
HOMES = STATE / "homes"                      # one generated Hermes home per flow (the worker)
GATEWAY_HOME = ROOT / ".hermes-home"         # Hermes home for the terminal (CLI) entry point
LOGS = STATE / "logs"
TASKS_DB = STATE / "tasks.db"
MEMORY_DB = STATE / "memory.db"              # the durable shared memory
BIN = ROOT / "serving" / "bin"               # pinned binaries (serving/bin.lock)
UPSTREAM = ROOT / "vendor" / "hermes"          # Hermes at the pin: the workers' backend (a submodule)
MODELS = ROOT / "models"                     # catalog model weights (serving/models.yaml)
def _port(name, default):
    """Ariadne's own port block: Hermes may be running on 8787/8791/8080 on the same machine, so never reuse them."""
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


PORT_MCP = _port("ARIADNE_PORT_MCP", 8911)          # the MCP endpoint (ariadne up, ariadne connect)
PORT_MODELS = _port("ARIADNE_PORT_MODELS", 8912)    # llama-swap / llama-server
PORT_UI = _port("ARIADNE_PORT_UI", 8917)            # the console and its SSE stream
PORT_BROWSER = _port("ARIADNE_PORT_BROWSER", 9317)  # the browser's debug port (not Chrome's 9222)

LLM_BASE_URL = os.environ.get("ARIADNE_LLM_URL", f"http://127.0.0.1:{PORT_MODELS}/v1")

WINDOWS = os.name == "nt"
EXE = ".exe" if WINDOWS else ""
VENV = ROOT / ".venv"
VENV_BIN = VENV / ("Scripts" if WINDOWS else "bin")
VENV_PY = VENV_BIN / ("python.exe" if WINDOWS else "python")
PYTHON = Path(sys.executable)
HERMES_EXE = VENV_BIN / ("hermes.exe" if WINDOWS else "hermes")   # sentinel: nothing may use it (the drill asserts)


def platform_key():
    """windows-x64, linux-x64, linux-arm64, darwin-arm64 or darwin-x64: picks entries in the lock files."""
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "darwin"}.get(platform.system(), platform.system().lower())
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    return f"{system}-{arch}"


def npx():
    return shutil.which("npx.cmd" if WINDOWS else "npx") or ("npx.cmd" if WINDOWS else "npx")


def ollama_blobs():
    """Ollama's model store (llama-swap serves its GGUF blobs read-only)."""
    if os.environ.get("OLLAMA_MODELS"):
        return Path(os.environ["OLLAMA_MODELS"]) / "blobs"
    for d in (Path.home() / ".ollama" / "models", Path("/usr/share/ollama/.ollama/models")):
        if (d / "blobs").exists():
            return d / "blobs"
    return Path.home() / ".ollama" / "models" / "blobs"


def ensure():
    for d in (STATE, HOMES, LOGS):
        d.mkdir(parents=True, exist_ok=True)
