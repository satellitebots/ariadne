"""The loop: prompt -> model -> the tools it calls -> model ... until it answers, out of turns, or out of time.

This is the whole agent runtime Ariadne needs, and it is ~100 lines because nothing else belongs in it: no provider
abstraction (the endpoint is `serving.endpoint()`), no tool framework (six functions), no UI, no plugins. Sessions are
message lists (`session.py`), so a failed gate resumes the same conversation.

Model-free to test: `transport` scripts the model, so a test drives tool calls, refusals, budgets and resume without a
GPU.
"""
import json
import re
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
    stopped: str = ""          # "" answered, "max_turns", "budget", "empty", "parked"
    session: str = ""
    dropped: int = 0           # messages trimmed out of the context in this run


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


def _size(messages):
    """Rough token count: content + tool calls + a per-message envelope, over four."""
    return sum(len(str(m.get("content") or "")) + len(json.dumps(m.get("tool_calls") or "")) + 40
               for m in messages) // 4


def _valid_start(rest, cut) -> bool:
    """Is rest[cut] a lawful first message of a list: not an orphaned tool result, and not a call whose results
    were all cut away?"""
    if cut >= len(rest):
        return True
    m = rest[cut]
    if m.get("role") == "tool":
        return False
    if m.get("role") == "assistant" and (m.get("tool_calls") or []):
        ids = {c.get("id") for c in m["tool_calls"] if isinstance(c, dict) and c.get("id")}
        return any(t.get("role") == "tool" and t.get("tool_call_id") in ids for t in rest[cut + 1:])
    return True


def _trim_messages(messages, context_tokens, trim_at):
    """Fit `messages` in the window: keep the system message and a contiguous tail of the rest, taken from the
    end, that fits roughly half the window. Returns (kept, dropped).

    The tail's start is repaired - an orphaned tool result, or a call with no result left in the slice, is
    dropped - so every kept `tool` message still follows the assistant whose `tool_calls` it answers, and the
    result never holds fewer than the system message plus the last two messages.
    """
    if _size(messages) <= context_tokens * trim_at:
        return messages, 0
    system, rest = messages[0], messages[1:]
    target = context_tokens * 0.5
    cut, used = len(rest), 0
    while cut > 0 and used + _size([rest[cut - 1]]) <= target:
        cut -= 1
        used += _size([rest[cut]])
    cut = min(cut, max(0, len(rest) - 2))          # never fewer than the system + the last two
    while cut < len(rest) and not _valid_start(rest, cut):
        cut += 1
    kept = [system] + rest[cut:]
    if len(kept) < 3:                               # the repair ate under the floor: re-keep from the last two
        cut2 = max(0, len(rest) - 2)
        while cut2 > 0 and not _valid_start(rest, cut2):
            cut2 -= 1
        kept = [system] + rest[cut2:]
    return kept, len(messages) - len(kept)


OMIT_RE = re.compile(r"\n+\[Earlier turns omitted to stay inside the context window:[^\]]*\]")


def _omitted_note(n):
    return (f"\n\n[Earlier turns omitted to stay inside the context window: {n} messages, including tool "
            "results. The workspace holds the work so far; re-read a file if you need its content.]")


def _mark_omitted(content, n):
    """The system message says what was dropped: append the note, or replace one already there."""
    return OMIT_RE.sub("", content or "").rstrip() + _omitted_note(n)


def run(prompt, *, home, workspace, phase="execute", model, session="", max_turns=40, budget=1800,
        transport=None, base_url=None, clock=time.time, on_event=None, mcp=None, skills=None, web=None,
        context_tokens=65536, trim_at=0.75, checkpoint=None, native_tools=True, system=None):
    """One conversation turn-run. Returns an Answer; never leaves a half-written session behind.

    `session`: a name to resume (the task id, or the caller's session). `on_event(kind, detail)` is how the worker
    records tool calls in the task's event log without the loop knowing what a store is. `mcp` is the flow's
    `runtime.mcp.Pool`: its tools join the schemas, and `mcp__`-named calls are handed to it, filtered the same way
    the loop filters its own tools by phase. `skills` is the flow's `runtime.skills.Box`: `skills_list`/`skill_view`
    join the schemas, and calls to them read the flow's shared skills. `web` is the flow's `runtime.web.Search`:
    `web_search` joins the schemas (in every phase - the plan is where it is needed most), and a call by that name
    is handed to it before the native tools.

    `context_tokens`/`trim_at`: before every model call, a message list estimated above `context_tokens * trim_at`
    is trimmed to the system message plus a recent tail, the system message says how much was omitted, and the
    trimmed list is what the session saves (the next run resumes what fits). `Answer.dropped` counts the messages
    removed this run.

    `native_tools=False` removes the file, patch, search-in-files and terminal tools entirely (the chat's rule: it
    composes and submits, it never works). `system` overrides the generated system prompt.

    `checkpoint`: an optional callable, asked at the top of every loop iteration after the first turn. When it
    returns true the run has finished a full turn (model call and its tool calls, the session saved) and stops at
    that step boundary with `stopped == "parked"`; the caller (the worker) then holds the model for the person and
    resumes the same session. It is never asked on the first turn - the worker checks before starting a run.
    """
    if not (model or "").strip():
        raise RunError("a run needs an explicitly chosen model")
    messages = session_mod.load(home, session) or [{"role": "system", "content": system or system_prompt(phase, str(workspace))}]
    messages.append({"role": "user", "content": prompt})
    started, answer = clock(), Answer(session=session)
    read = read_only(phase)
    schemas = ((tools_mod.offered(phase) if native_tools else [])
               + (mcp.offered(read) if mcp else [])
               + (skills.offered() if skills else [])
               + (web.offered() if web else []))
    while answer.turns < max(1, int(max_turns)):
        if answer.turns and checkpoint and checkpoint():
            # A park request mid-run: the in-flight turn (model call and tool calls) has finished and the session
            # is saved, so stop at this step boundary; the worker holds and resumes the same session.
            answer.stopped, answer.text = "parked", _last_assistant(messages)
            session_mod.save(home, session, messages)
            return answer
        if clock() - started > budget:
            answer.stopped, answer.text = "budget", _last_assistant(messages)
            session_mod.save(home, session, messages)
            return answer
        answer.turns += 1
        messages, dropped = _trim_messages(messages, context_tokens, trim_at)
        if dropped:
            answer.dropped += dropped
            messages[0] = {**messages[0], "content": _mark_omitted(messages[0].get("content") or "", dropped)}
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
            elif web is not None and call["name"] == "web_search":
                result = web.call(call["name"], call["arguments"])
            elif native_tools:
                result = tools_mod.call(call["name"], call["arguments"], workspace, phase)
            else:
                result = (f"ERROR: there is no {call['name']} tool in this conversation; it has only the tools it "
                          "was offered")
            messages.append({"role": "tool", "tool_call_id": call["id"], "name": call["name"], "content": result})
        session_mod.save(home, session, messages)
        if not reply["tool_calls"]:
            answer.text, answer.stopped = reply["content"], ("" if reply["content"] else "empty")
            return answer
    answer.stopped, answer.text = "max_turns", _last_assistant(messages)
    return answer
