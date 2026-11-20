"""Ariadne's own runtime: the agent loop, the tools, and the model call - no submodule, no `hermes` CLI.

`loop.run()` is what `worker.py` will call instead of spawning `hermes chat`: prompt the model, run the tools it asks
for, feed the results back, until it answers or runs out of turns or time. Sessions are message lists on disk, so a
run can be resumed. The tools are ours (files, search, a terminal); MCP servers attach the same way later.

Model-free to test: `run(..., transport=fake)` scripts the model, so the loop, the tool dispatch, the phase filter,
the budgets and the resume are all exercised without a GPU or a model.
"""
from .loop import Answer, run, system_prompt   # noqa: F401
from .model import ModelError, chat            # noqa: F401
from .tools import ToolError                    # noqa: F401
