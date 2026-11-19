"""The task plan: data, not prose.

The planner returns a fenced JSON block; this module owns its shape. Rendering lives in `render.py`, so the
terminal, the desktop page and MCP all show the same document because they all read the same fields.
"""
import json
import re

KEYS = {"mission", "steps", "gates", "risks", "questions"}
STEP_KEYS = {"n", "text", "model"}


class PlanError(ValueError):
    pass


def _raw(text):
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text or "", re.S)
    if not m:
        m = re.search(r"(\{\s*\"mission\".*?\})\s*$", text or "", re.S)
    return m.group(1) if m else ""


def parse(text, default_model=""):
    """A Plan from the planner's reply. Raises PlanError so the caller can fall back and say why."""
    raw = _raw(text)
    if not raw:
        raise PlanError("no JSON plan block in the reply")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise PlanError(f"the plan JSON is invalid: {e.msg} at char {e.pos}")
    if not isinstance(data, dict):
        raise PlanError("the plan must be a JSON object")
    unknown = set(data) - KEYS
    if unknown:
        raise PlanError(f"unknown plan keys: {', '.join(sorted(unknown))}")
    steps, seen = [], set()
    for i, s in enumerate(data.get("steps") or [], 1):
        if isinstance(s, str):
            s = {"text": s}
        if not isinstance(s, dict):
            raise PlanError(f"step {i} is not an object")
        extra = set(s) - STEP_KEYS
        if extra:
            raise PlanError(f"step {i} has unknown keys: {', '.join(sorted(extra))}")
        body = str(s.get("text") or "").strip()
        if not body:
            continue
        n = int(s.get("n") or i)
        if n in seen:
            raise PlanError(f"step {n} appears twice")
        seen.add(n)
        steps.append({"n": n, "text": body, "model": str(s.get("model") or default_model).strip()})
    if not steps:
        raise PlanError("the plan has no steps")

    def lines(key):
        v = data.get(key) or []
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in v if str(x).strip()]

    return {"mission": str(data.get("mission") or "").strip(), "steps": steps, "gates": lines("gates"),
            "risks": lines("risks"), "questions": lines("questions")}


def to_json(plan):
    return json.dumps(plan, ensure_ascii=False, sort_keys=True)


def from_json(text):
    try:
        plan = json.loads(text or "{}")
    except json.JSONDecodeError:
        return None
    return plan if plan.get("steps") else None


def missing_models(plan):
    return [s["n"] for s in plan["steps"] if not s.get("model")]
