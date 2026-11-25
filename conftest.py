# Lets pytest import the ariadne package from the repo root (rootdir conftest puts the root on sys.path).
#
# Tests never touch the real state folder (.ariadne/: tasks, logs, KV caches, park flag, model pins). ARIADNE_STATE is
# set before any test module imports ariadne, so paths.STATE and everything derived from it (LOGS, TASKS_DB, HOMES,
# the per-module files) point at a throwaway folder for the whole session.
import os
import shutil
import tempfile

_STATE = tempfile.mkdtemp(prefix="ariadne-test-state-")
os.environ["ARIADNE_STATE"] = _STATE


def pytest_unconfigure(config):
    shutil.rmtree(_STATE, ignore_errors=True)
