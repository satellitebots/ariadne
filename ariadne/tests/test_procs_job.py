"""The kill switch: a named Windows job object holds every process Ariadne starts, so `stop` can end the group even
when a parent has already gone and left a child behind."""
import os
import subprocess
import sys

import pytest

from ariadne import procs


@pytest.mark.skipif(os.name != "nt", reason="Windows job objects")
def test_a_process_in_the_job_dies_even_if_its_parent_is_gone():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assert procs.adopt(child.pid)
        assert procs.terminate_job()
        assert child.wait(timeout=10) != 0
    finally:
        if child.poll() is None:
            child.kill()


@pytest.mark.skipif(os.name != "nt", reason="Windows job objects")
def test_adopting_nothing_is_harmless():
    assert procs.adopt(0) is False
