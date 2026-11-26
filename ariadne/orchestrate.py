"""The orchestrator: a local model that talks with the person and defines durable tasks - and never works.

(docs/DESIGN.md, "The orchestrator".) Its tools are the verbs (verbs.py, minus the conversation verbs themselves),
read-only web search, and read-only file tools. It has no write, patch or terminal tool, so it cannot do the work
even if it tries. Every turn holds the broker's lease: when a run holds the machine, the turn waits for that run's
next step boundary (the person parks the run to take it now). It uses the flow's worker model when it can, so the
handoff is a cache switch, not a reload.

One conversation shape serves every front: a draft's conversation (`say`) and the general chat (`chat`) are the same
turn with different context.
"""
import json
import time
from pathlib import Path

from . import paths, spec as speclib, verbs

CONVERSATION_VERBS = ("say", "chat", "chat_activity")

SYSTEM = """You are Ariadne's orchestrator, on the person's own machine. Today is {today}. You help the person define
durable tasks and manage them. You never do the work yourself: workers do it, one step at a time, after the person signs.

What you can do (tools): look at flows (task templates), drafts, tasks, runs and the machine; update a draft's
definition with draft_update; start, park, steer, resume or cancel runs when the person asks; search the web and read
files to plan well. You cannot write files or run commands. A run that is "asking" waits for the person's yes or no
(permissions.yaml): tell them what it asks, and call approve or reject only on their explicit answer, never on your own.
Act on a run (run, park, steer, resume, cancel, approve, reject) only when the person's message tells you to do that.
When they ask what to do or what to tell a run, answer with your proposal (the exact note you would send) and ask
whether to send it; do nothing to the run in that turn. A steering note holds for the rest of the run.
To say how a run is doing, call progress: its last tool call, model call or job output and how long ago. Nothing stops a
run on its own; cancel only when the person asks. "waiting" means queued for the machine; only "parked" is parked.

How to define a task:
1. Pick the flow that fits (flows). Its template already has steps and gates; you fill it in.
2. Ask only for what is missing: the template's parameters, a name, the workspace folder (never inside Ariadne's own
   repository; a folder under {sandbox} is fine), and when it should run (manual, once now, at a time, or a
   schedule like "weekdays at 7"). Ask at most two questions at a time.
3. Adjust steps only where the request needs it. Keep each step small (one deliverable, about thirty tool calls),
   with the files it must leave and how it is checked. Heavy work in a step is a job (the worker submits it).
   What the local workers get wrong, and the rule for each (docs/WORKER-RECIPE.md):
   - Numbers: a script writes every number to data/facts.json; prose copies; gate the deliverable with
     `python {{checks}}/facts_in_report.py <deliverable> data/facts.json`.
   - Ambiguous measures: write each formula, unit and window into the step that computes it.
   - Sources: one ledger line each, "- <url> | <publisher> | <what> | <YYYY-MM-DD>"; gate with
     `python {{checks}}/sources_ledger.py SOURCES.md --min 3 --within-days N`.
   - Verify steps check locally: never research again, never edit data/ or the ledger.
   - Scripts check first (run gates), a review gate last; gate commands print what is wrong.
   `{{checks}}` is a placeholder Ariadne fills in; keep it as written.
4. Call draft_update with the COMPLETE definition as YAML (every field, not a patch). Then tell the person in two or
   three lines what will run and what is still missing, if anything. Signing is the person's act: say "sign it when
   it looks right"; never claim a task is signed or has run unless a tool told you so.
Be brief. Plain sentences, no headings."""

DRAFT_CONTEXT = """CURRENT DRAFT {id} (flow {flow}):
```yaml
{yaml}```
Template questions (params): {asks}
Still missing or wrong: {problems}
"""


class VerbTools:
    """The verbs as runtime tools; `draft` is pre-bound when the conversation is about one draft."""

    def __init__(self, draft_id=""):
        self.draft_id = draft_id
        self.names = [n for n, v in verbs.VERBS.items() if not v.mcp_only and n not in CONVERSATION_VERBS]

    def offered(self):
        out = []
        for n in self.names:
            v = verbs.VERBS[n]
            sch = verbs.schema(v)
            if self.draft_id and "draft" in sch["properties"]:
                sch = {**sch, "properties": {k: p for k, p in sch["properties"].items() if k != "draft"},
                       "required": [r for r in sch["required"] if r != "draft"]}
            out.append({"type": "function", "function": {"name": n, "description": v.doc[:900], "parameters": sch}})
        return out

    def call(self, name, arguments):
        args = dict(arguments or {})
        if self.draft_id and "draft" in verbs.VERBS[name].params:
            args.setdefault("draft", self.draft_id)
        try:
            return verbs.dumps(verbs.call(name, **args))[:8000]
        except verbs.VerbError as e:
            return f"ERROR: {e}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"


class Orchestrator:
    def __init__(self, transport=None, model=None, max_turns=0, budget=0):   # 0, 0: no cap, no clock
        self.transport, self.model, self.max_turns, self.budget = transport, model, max_turns, budget

    def _model(self, flows, catalog, flow_name="", broker=None):
        if self.model:
            return self.model
        fl = flows.get(flow_name)
        if fl:
            return fl.step_model
        # Outside a draft: the agent model the machine has now (a live run's), so talking about a run costs no swap.
        from . import park
        st = broker.status() if broker else {}
        parked = park.requested() or {}
        for h in [st.get("holder")] + list(st.get("waiting") or []) + [{"model": parked.get("model")}]:
            m = catalog.models.get((h or {}).get("model") or "")
            if m and m.kind == "agent" and m.installed():
                return m.name
        for m in catalog.models.values():       # outside a flow: the first installed agent model
            if m.kind == "agent" and m.installed():
                return m.name
        raise verbs.VerbError("no agent model is installed; `ariadne models install <name>` first")

    def turn(self, ref, message, store, flows, catalog, broker, draft=None):
        """One turn. `ref` is the draft id (draft conversation) or a conversation name (general chat)."""
        from . import runtime
        from .runtime import web as web_mod
        d = draft or (store.draft(ref) if ref.startswith("d") else None)
        context = ""
        ws = paths.ROOT / "sandbox"
        if d:
            view = verbs._draft_view(d)
            context = DRAFT_CONTEXT.format(id=d["id"], flow=d["flow"], yaml=view["yaml"],
                                           asks=json.dumps(d["asks"]) or "none",
                                           problems="; ".join(view["problems"]) or "nothing - ready to sign")
            if d["spec"].get("workspace") and Path(d["spec"]["workspace"]).exists():
                ws = Path(d["spec"]["workspace"])
        ws.mkdir(parents=True, exist_ok=True)
        model = self._model(flows, catalog, d["flow"] if d else "", broker=broker)
        home = paths.STATE / "orchestrator"
        home.mkdir(parents=True, exist_ok=True)
        lease = broker.acquire("orchestrator", ref, model,
                               on_wait=lambda s: store.event(ref, "waiting", broker.describe()))
        try:
            a = runtime.run((context + "\nThe person says:\n" + message) if context else message,
                            home=home, workspace=ws, phase="plan", model=model, session=f"orch-{ref}",
                            max_turns=self.max_turns, budget=self.budget, transport=self.transport,
                            web=web_mod.Search(), extra=VerbTools(d["id"] if d else ""),
                            system=SYSTEM.format(sandbox=(paths.ROOT / "sandbox").as_posix(),
                                                 today=time.strftime("%A %d %B %Y")),
                            on_event=lambda kind, detail: store.event(
                                ref, "orchestrator", detail if kind == "model" else "called " + detail))
        finally:
            lease.release()
        return a.text or "(the orchestrator gave no answer; try again or say it differently)"


@verbs.verb("define")
def chat(message: str, conversation: str = "") -> dict:
    """Talk with the orchestrator outside a draft: ask about tasks and runs, start, park, steer or resume a run, or
    start defining a new task (it opens a draft). `conversation` continues an earlier one."""
    c = verbs.ctx
    ref = conversation or f"c{time.strftime('%m%d-%H%M%S')}"
    if c.orchestrator is None:
        c.orchestrator = Orchestrator()
    c.store.message(ref, "person", message)
    reply = c.orchestrator.turn(ref, message, store=c.store, flows=c.flows, catalog=c.catalog, broker=c.broker)
    c.store.message(ref, "orchestrator", reply)
    return {"conversation": ref, "reply": reply, "messages": c.store.messages(ref)}


@verbs.verb("define")
def chat_activity(conversation: str, since: float = 0.0) -> list:
    """What the orchestrator did in a conversation (or a draft's conversation) after `since`: its waits for the
    machine, its model calls and its tool calls, as they happen. A front shows these while a turn is working."""
    return [{"ts": e["ts"], "kind": e["kind"], "detail": e["detail"]}
            for e in verbs.ctx.store.events(conversation, since=since, limit=200)
            if e["kind"] in ("orchestrator", "waiting")]
