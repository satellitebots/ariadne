"""The loop: prompt -> model -> the tools it calls -> model ... until it answers, out of turns, or out of time.

This is the whole agent runtime Ariadne needs, and it is ~100 lines because nothing else belongs in it: no provider
abstraction (the endpoint is `serving.endpoint()`), no tool framework (six functions), no UI, no plugins. Sessions are
message lists (`session.py`), so a failed gate resumes the same conversation.

Model-free to test: `transport` scripts the model, so a test drives tool calls, refusals, budgets and resume without a
GPU.
"""
import json
import time
from dataclasses import dataclass

from . import model as model_mod
from . import session as session_mod
from . import tools as tools_mod

SYSTEM = """You are the {phase} worker of Ariadne, a local agent harness running on the person's own machine.
WORKSPACE: {workspace}

{phase_rules}

- Use the tools you have. Do not describe work you did not do.
- Keep results small: read the lines you need, search instead of dumping a file.
- Finish with a short report: what you changed and how you verified it.
"""

PLAN_RULES = ("This is a READ-ONLY phase (plan, review or checkpoint): you may read files, search and list, and the "
              "loop gives you no tool that writes. Nothing changes before the person signs off.")
WORK_RULES = ("This is the EXECUTE phase: the person approved the plan. Carry it out step by step and stay on it. If a "
              "step cannot be done as planned, or the plan is wrong, stop and reply starting with 'OFF-PLAN:' and "
              "the reason - do not improvise a different plan.")


class RunError(RuntimeError):
    pass


@dataclass
class Answer:
    text: str = ""
    turns: int = 0
    stopped: str = ""          # "" answered, "max_turns", "budget", "empty"
    session: str = ""


def read_only(phase: str) -> bool:
    return (phase or "").split(":")[0] in ("plan", "review", "checkpoint", "learn")


def system_prompt(phase, workspace):
    return SYSTEM.format(phase=phase, workspace=workspace,
                         phase_rules=PLAN_RULES if read_only(phase) else WORK_RULES)


def _last_assistant(messages) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            return m["content"].strip()
    return ""


def run(prompt, *, home, workspace, phase="execute", model, session="", max_turns=40, budget=1800,
        transport=None, base_url=None, clock=time.time, on_event=None, mcp=None, skills=None):
    """One conversation turn-run. Returns an Answer; never leaves a half-written session behind.

    `session`: a name to resume (the task id, or the caller's session). `on_event(kind, detail)` is how the worker
    records tool calls in the task's event log without the loop knowing what a store is. `mcp` is the flow's
    `runtime.mcp.Pool`: its tools join the schemas, and `mcp__`-named calls are handed to it, filtered the same way
    the loop filters its own tools by phase. `skills` is the flow's `runtime.skills.Box`: `skills_list`/`skill_view`
    join the schemas, and calls to them read the flow's shared skills.
    """
    if not (model or "").strip():
        raise RunError("a run needs an explicitly chosen model")
    messages = session_mod.load(home, session) or [{"role": "system", "content": system_prompt(phase, str(workspace))}]
    messages.append({"role": "user", "content": prompt})
    started, answer = clock(), Answer(session=session)
    read = read_only(phase)
    schemas = (tools_mod.offered(phase)
               + (mcp.offered(read) if mcp else [])
               + (skills.offered() if skills else []))
    while answer.turns < max(1, int(max_turns)):
        if clock() - started > budget:
            answer.stopped, answer.text = "budget", _last_assistant(messages)
            session_mod.save(home, session, messages)
            return answer
        answer.turns += 1
        left = max(30, int(budget - (clock() - started))) if budget else 600
        reply = model_mod.chat(messages, model=model, tools=schemas, transport=transport, base_url=base_url,
                               timeout=min(600, left))
        messages.append(reply["raw"])
        for call in reply["tool_calls"]:
            if on_event:
                on_event("tool", f"{call['name']} {json.dumps(call['arguments'], ensure_ascii=False)[:200]}")
            if skills is not None and call["name"] in ("skills_list", "skill_view"):
                result = skills.call(call["name"], call["arguments"])
            elif call["name"].startswith("mcp__") and mcp is not None:
                result = mcp.call(call["name"], call["arguments"], read_only=read)
            else:
                result = tools_mod.call(call["name"], call["arguments"], workspace, phase)
            messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result})
        session_mod.save(home, session, messages)
        if not reply["tool_calls"]:
            answer.text, answer.stopped = reply["content"], ("" if reply["content"] else "empty")
            return answer
    answer.stopped, answer.text = "max_turns", _last_assistant(messages)
    return answer
