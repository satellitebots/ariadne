"""The cosmetic layer: one document per task, rendered once, shown the same everywhere.

MCP, the chat, the terminal and the desktop all ask this module for the task; `text()` is Markdown for a model or a
terminal, `view()` is the same content as data for the page. Nothing outside this file formats a task, so the
surfaces cannot drift - and the formatting lives in this repo, never in the Hermes submodule.
"""
import json

from . import protocol, render

STATUS = {"new": "queued", "awaiting_gates": "waiting for check gates", "awaiting_signoff": "backbrief ready",
          "approved": "approved", "planning": "planning", "executing": "executing", "needs_attention": "needs you",
          "done": "done", "failed": "failed", "cancelled": "cancelled", "rejected": "rejected"}
MARK = {"done": "✓", "failed": "✗", "cancelled": "–", "rejected": "⊘", "needs_attention": "!",
        "awaiting_signoff": "?", "awaiting_gates": "?", "planning": "…", "executing": "…", "vram": "⏻"}


def _plan(t):
    """The plan as data when we have it, so no surface has to parse prose."""
    return protocol.from_json(t.get("plan_json") or "")


def _actions(t):
    """The verbs the person may use right now: the same set in every surface."""
    s = t["status"]
    if s in ("awaiting_signoff", "needs_attention"):
        return ["approve", "revise", "cancel"]
    if s == "awaiting_gates":
        return ["set_gates", "cancel"]
    if s in ("new", "approved", "planning", "executing"):
        return ["cancel"]
    return []


def view(t, next_action=""):
    """The task as data: what the desktop page renders, and what any surface may inspect."""
    plan = _plan(t)
    doc = t.get("plan") or ""
    body = doc.split("MODEL PLAN")[0].strip() if doc else ""
    return {
        "id": t["id"], "status": t["status"], "label": STATUS.get(t["status"], t["status"]),
        "brief": t.get("text") or "", "flow": t.get("flow") or "", "model": t.get("model") or "",
        "session": t.get("session") or "", "workspace": t.get("workspace") or "",
        "gates": json.loads(t.get("gates") or "[]"),
        "document": body,
        "sections": {
            "mission": (plan or {}).get("mission", ""),
            "steps": render.steps(plan) if plan else [],
            "checks": (plan or {}).get("gates", []),
            "risks": (plan or {}).get("risks", []),
            "questions": (plan or {}).get("questions", []),
        },
        "models": t.get("models") or "", "report": t.get("result") or "", "error": t.get("error") or "",
        "events": t.get("events") or [], "actions": _actions(t), "next": next_action,
    }


def text(t, next_action=""):
    """The task as Markdown: one card, identical wording whichever surface shows it."""
    v = view(t, next_action)
    out = [f"## Task {v['id']} - {v['label']}", ""]
    meta = [f"flow: {v['flow'] or '-'}", f"model: {v['model'] or '-'}", f"session: {v['session'] or '-'}"]
    if v["workspace"]:
        meta.append(f"workspace: {v['workspace']}")
    out += ["- " + "  ·  ".join(meta), "", f"**Brief:** {v['brief']}"]
    if v["gates"]:
        out += ["", "**Check gates:**"] + [f"- {g}" for g in v["gates"]]
    if v["document"]:
        out += ["", "**Backbrief:**", "", "```", v["document"], "```"]
    if v["report"]:
        out += ["", "**Report:**", "", v["report"]]
    if v["error"]:
        out += ["", f"**Stopped:** {v['error']}"]
    if v["events"]:
        out += ["", "**Activity:**"] + [f"- {e}" for e in v["events"][-6:]]
    if v["actions"]:
        out += ["", "**You may:** " + ", ".join(v["actions"])]
    if v["next"]:
        out += ["", v["next"]]
    return "\n".join(out)


def inbox_text(state):
    out = [f"worker: {'running' if state['worker'] else 'not running'}"]
    for key, title in (("waiting", "NEEDS YOU"), ("running", "RUNNING"), ("stale", "STOPPED, NO WORKER"),
                       ("recent", "RECENT")):
        rows = state.get(key) or []
        out += ["", f"{title} ({len(rows)})"]
        out += [f"  {MARK.get(t['status'], '·')} {t['id']}  {t['status']:<17} {(t.get('text') or '')[:60]}"
                for t in rows] or ["  (none)"]
    return "\n".join(out)
