---
name: ariadne-tasks
description: Hand real work (code changes, documents, content) to Ariadne's task orchestrator and run the brief, backbrief, sign-off, execute drill with the person in this chat.
---
# Ariadne tasks

Use this when the person asks for work to be done (change code, write a document, make content) rather than
a quick answer. Ariadne plans first, the person signs off, then it executes.

The tools come from the `ariadne_tasks` MCP server. Their exact names (call them through `tool_call` if they
are deferred): `mcp__ariadne_tasks__submit_task`, `mcp__ariadne_tasks__wait_task`,
`mcp__ariadne_tasks__get_task`, `mcp__ariadne_tasks__approve_task`, `mcp__ariadne_tasks__revise_task`,
`mcp__ariadne_tasks__cancel_task`, `mcp__ariadne_tasks__list_tasks`. Task ids are strings like `t1117-140722-c914`.

1. **Brief.** Call `submit_task` with the person's request in their words as `text`, the folder it applies to
   as `workspace` (ask if they did not say), `source` set to where you are talking to them (e.g. `slack`, `cli`),
   and `session`: the session name the person gave ("continue auth-work"), else your own session id (it is in
   your system prompt). Every task from this conversation then shares one Ariadne session, so the worker
   carries what earlier tasks did. Tell them the task id. `list_sessions` shows the sessions they can continue.
2. **Backbrief.** Call `wait_task(id)` until the status is `awaiting_signoff` (it returns every ~50 s while the
   worker plans; keep calling). Show the person the backbrief (`plan`) exactly as written, including its
   MODEL PLAN (the model for each step, and any model that will be downloaded after sign-off).
3. **Sign-off.** Ask: approve, change, or cancel? Then call `approve_task` (with `models`, e.g. `"2=gemma-4-12b"`,
   if they want a different model for a step), `revise_task` (with their feedback, which produces a new
   backbrief - go back to step 2) or `cancel_task`. Never approve on their behalf.
4. **Execute and report.** After approval call `wait_task` until `done`, `failed` or `needs_attention`, and
   give them the result. `needs_attention` means the worker stopped (off-plan, a model would not install, or a
   tool is missing): show why and ask whether to fix and approve again, revise, or cancel.

Use `list_tasks` / `get_task` when they ask about earlier tasks.
