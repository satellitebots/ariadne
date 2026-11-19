---
name: ariadne-tasks
description: Hand real work (code changes, documents, content) to Ariadne's task orchestrator and run the brief, backbrief, sign-off, execute drill with the person in this chat.
---
# Ariadne tasks

**You cannot do the work yourself.** This home has no terminal, no file tools, no editor and no code execution:
the only way work happens is `submit_task`, the backbrief, sign-off, and the worker executing. Do not try to
work around that, and do not answer a work request by writing the result into the chat.

- A request to change, build, write or investigate something → submit a task.
- A question, a conversation, a decision → answer it normally.
- Never say "here is the change" or paste a diff instead of submitting; the person asked for the drill.

Use this when the person asks for work to be done (change code, write a document, make content) rather than
a quick answer. Ariadne plans first, the person signs off, then it executes.

The tools come from the `ariadne_tasks` MCP server. Their exact names (call them through `tool_call` if they
are deferred): `mcp__ariadne_tasks__submit_task`, `mcp__ariadne_tasks__wait_task`,
`mcp__ariadne_tasks__get_task`, `mcp__ariadne_tasks__approve_task`, `mcp__ariadne_tasks__revise_task`,
`mcp__ariadne_tasks__cancel_task`, `mcp__ariadne_tasks__list_tasks`. Task ids are strings like `t1117-140722-c914`.

0. **Gates first.** Before submitting, make sure you know the check gates: how we will know the task is done,
   end to end - commands that must pass (`run: pytest -q`) and outcomes a reviewer can verify. If the person did
   not say, ask them explicitly; suggest gates if helpful, but let them decide. No task starts without gates.
1. **Brief.** Call `submit_task` with the person's request in their words as `text`, the gates as `gates`, the folder it applies to
   as `workspace` (ask if they did not say), `source` set to where you are talking to them (e.g. `slack`, `cli`),
   and `session`: the session name the person gave ("continue auth-work"), else your own session id (it is in
   your system prompt). Every task from this conversation then shares one Ariadne session, so the worker
   carries what earlier tasks did. Tell them the task id. `list_sessions` shows the sessions they can continue.
Every task tool returns a Markdown card (status, gates, backbrief or report, recent activity, **Next**)
followed by a small JSON block. Show the card to the person as-is - it is written for them - and follow **Next**.

2. **Backbrief.** Call `wait_task(id)` until the status is `awaiting_signoff` (it returns every ~50 s while the
   worker plans; keep calling). Show the person the backbrief (`plan`) exactly as written, including its
   MODEL PLAN (the model for each step, and any model that will be downloaded after sign-off).
3. **Sign-off.** Ask in one line: "Reply **approve**, **revise:** <what to change>, or **cancel**." (They may
   also say "approve with step 2 on gemma-4-12b".) Then call `approve_task` (with `models`, e.g. `"2=gemma-4-12b"`,
   if they want a different model for a step), `revise_task` (with their feedback, which produces a new
   backbrief - go back to step 2) or `cancel_task`. Never approve on their behalf.
4. **Execute and report.** After approval call `wait_task` until `done`, `failed` or `needs_attention`, and
   give them the result. `needs_attention` means the worker stopped (off-plan, a model would not install, or a
   tool is missing): show why and ask whether to fix and approve again, revise, or cancel.

5. **Feedback into skills.** After the report, ask what they thought, and call `feedback_task(id, ...)` with
   their words plus your own review of the work. If you are a capable model, fold it into the flow's shared skills:
   `list_skills(flow)` (shows open feedback), `get_skill`, then `save_skill(flow, name, content, note, resolves)`
   with a complete, specific SKILL.md. Skills are committed and pushed, and every later run of the flow loads them.
   Local models never write skills; the larger model talking to Ariadne does.

Use `list_tasks` / `get_task` when they ask about earlier tasks.

Ariadne's worker and models run in the background, outside this chat: ending the chat does not stop a task. Never
kill its processes yourself. If the person wants to stop, tell them: the watch window (`python -m ariadne watch
--open`) has P park, R resume, S stop; or `python -m ariadne stop`. A stopped task comes back as
`needs_attention` with its work kept.
