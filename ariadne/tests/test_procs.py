import sys
import time
from pathlib import Path

from ariadne import procs

PKG = Path(__file__).resolve().parents[1]


def test_spawn_detached_runs_and_logs(tmp_path):
    log, done = tmp_path / "out.log", tmp_path / "done.txt"
    script = tmp_path / "job.py"
    script.write_text(f"import os, pathlib\nprint('hello', os.environ.get('ARIADNE_T'))\n"
                      f"pathlib.Path(r'{done}').write_text('ok')\n")
    pid = procs.spawn_detached([sys.executable, script], log, tmp_path, {"ARIADNE_T": "42"})
    assert pid > 0
    for _ in range(60):
        if done.exists():
            break
        time.sleep(0.5)
    assert done.read_text() == "ok"
    time.sleep(0.5)
    assert "hello 42" in log.read_text()


def test_long_running_processes_start_outside_the_session():
    """The worker and the model server go through procs.spawn_detached; nothing else spawns them on its own."""
    for mod in ("daemon.py", "serve.py"):
        src = (PKG / mod).read_text(encoding="utf-8")
        assert "spawn_detached(" in src, mod
        assert "DETACHED_PROCESS" not in src, f"{mod} starts a background process without procs.spawn_detached"
