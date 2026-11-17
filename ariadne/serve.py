"""Local model server: llama-swap with serving/llama-swap.yaml rendered for this machine. One model on the GPU."""
import json
import os
import signal
import subprocess
import sys
import time

from . import deps, llm, paths

PID_FILE = paths.STATE / "llama-swap.pid"
CONFIG = paths.STATE / "llama-swap.yaml"


def render_config():
    server = deps.find_bin("llama.cpp", "llama-server")
    if not server:
        sys.exit("llama-server is missing: run  python -m ariadne install")
    wrapper = paths.ROOT / "serving" / "llama_server_exclusive.py"
    q = lambda p: f'"{p}"'
    text = (paths.ROOT / "serving" / "llama-swap.yaml").read_text(encoding="utf-8")
    text = text.replace("{{SERVER}}", f"{q(paths.VENV_PY)} {q(wrapper)} {q(server)}").replace(
        "{{BLOBS}}", paths.ollama_blobs().as_posix())
    paths.ensure()
    CONFIG.write_text(text, encoding="utf-8")
    return CONFIG


def _pid():
    try:
        return json.loads(PID_FILE.read_text())["pid"]
    except (OSError, ValueError, KeyError):
        return None


def _kill_strays():
    """llama-swap / llama-server processes started from serving/bin that outlived their parent."""
    if paths.WINDOWS:
        ps = (f"Get-Process llama-swap,llama-server -ErrorAction SilentlyContinue | "
              f"Where-Object {{ $_.Path -like '{paths.BIN}*' }} | Stop-Process -Force")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True)
    else:
        subprocess.run(["pkill", "-f", str(paths.BIN)], capture_output=True)


def stop():
    pid = _pid()
    if pid:
        try:
            if paths.WINDOWS:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            else:
                os.killpg(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            pass
        PID_FILE.unlink(missing_ok=True)
    _kill_strays()
    print("models stopped")
    return 0


def start(listen="127.0.0.1:8090", wait=60):
    """Start llama-swap detached (own process group; log in .ariadne/logs/llama-swap.log)."""
    if llm.is_up():
        print(f"models already up on {paths.LLM_BASE_URL}")
        return 0
    swap = deps.find_bin("llama-swap", "llama-swap")
    if not swap:
        sys.exit("llama-swap is missing: run  python -m ariadne install")
    cfg = render_config()
    paths.ensure()
    log = open(paths.LOGS / "llama-swap.log", "a", encoding="utf-8")
    kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if paths.WINDOWS \
        else {"start_new_session": True}
    p = subprocess.Popen([str(swap), "-config", str(cfg), "-listen", listen], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, cwd=str(paths.ROOT), close_fds=True, **kw)
    PID_FILE.write_text(json.dumps({"pid": p.pid}))
    for _ in range(wait):
        time.sleep(1)
        if llm.is_up(f"http://{listen}/v1"):
            print(f"models up on http://{listen}/v1 (log {paths.LOGS / 'llama-swap.log'})")
            return 0
    sys.exit(f"llama-swap did not come up; see {paths.LOGS / 'llama-swap.log'}")
