import threading
import time

from ariadne import park


def test_step_boundary_waits_for_a_finished_call(tmp_path):
    log = tmp_path / "logs" / "agent.log"
    log.parent.mkdir()
    log.write_text("old agent.conversation_loop: API call #1: model=x\n")
    b = park.StepBoundary(tmp_path)
    assert not b.reached()                       # starts watching from now; the old call does not count
    with open(log, "a") as f:
        f.write("12:00 INFO something else\n")
    assert not b.reached()
    with open(log, "a") as f:
        f.write("12:01 INFO agent.tool_executor: tool read_file completed (0.1s)\n")
    assert b.reached()


