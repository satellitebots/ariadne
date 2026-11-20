# Frontend: our own (decision, 2026-11-19)

Ariadne gets its own UI and its own chat. The Hermes desktop shell is no longer our frontend: it is a chat product
with connectors, bots, capabilities and a composer, and hiding those rows does not change what the window is. We keep
the parts of Hermes that are genuinely valuable and decouple from the rest.

`docs/DESIGN-RESET.md` remains the authority on the drill; this file is the authority on the frontend.

## What we keep from Hermes

- **The worker runtime.** One Hermes session per task: tools (terminal, files, browser, VS Code), the MCP client,
  skills, session resume. This is the expensive, well-built part and we do not reimplement it.
- **The MCP tasks server**, so another agent (Hermes, Claude) can drive Ariadne as a backend.
- **Model serving through a local endpoint** (Ollama, or an OpenAI-compatible server on this machine or the LAN),
  guarded by `ariadne/local_only.py`.

## What we drop

- `desktop/plugin/**` (the Hermes plugin page and its HTTP routes), `ariadne desktop`, the branding overlay, the
  nav-hiding prefs, and the stub-render harness that existed only to test a plugin.
- `plugins/ariadne_gate`: our chat is ours, so it simply is not given doing-tools. A hook that refuses tools after
  the model chose them was a patch for a container we no longer use.
- `plugins/offline_guard`: it blocks all egress, which contradicts "a local model may use the internet".

## Architecture

```
 browser (our SPA)  ─┐
 terminal (ariadne)  ─┼─►  server (FastAPI, loopback)  ─►  service  ─►  store
 MCP (Hermes/Claude) ─┘            │                        │
                                   │  SSE /api/events       │  one rulebook, one document (present)
                                   ▼                        ▼
                                chat  ◄──────────────  worker ─► Hermes session (tools, MCP, skills)
```

- **`ariadne/server/`** - FastAPI app owning every verb (`submit`, `approve`, `revise`, `set_gates`, `cancel`,
  `status`, `sessions`, `choices`) and every view (`present.view`). SSE for live activity; no polling.
- **`ariadne/ui/`** - static ES modules and CSS served by the same process. **No Node, no bundler, no Electron**:
  the repo stops needing a JS toolchain once the plugin is gone.
- **Chat** - a conversation bound to one session. Its tools are the service verbs plus read-only lookups; it never
  gets files, terminal, code or a browser. It composes briefs, answers questions about the session, and submits.
- **Binding** - `127.0.0.1` by default; `ARIADNE_BIND` for a LAN interface (the same rule as models: this machine or
  this network, never the internet). `local_only` checks the bind and the provider before anything starts.

## The screen

One console, no navigation beyond sessions:

- **Needs you** strip across all sessions - the mouth of the funnel.
- **Sessions** (left): the repo/workstream, its flow, model, waiting count, next scheduled run. `+ Session` picks a
  folder.
- **Timeline + backbrief** (center): the session's tasks in order; the selected task rendered from `present.view()`
  (mission, steps with model, checks, risks, questions), then report and changed files.
- **Decision** (right): only the verbs legal for that status, the gates editor, and what will be fetched on approval.
- **Schedules** live inside a session and can only be created there, inheriting its flow, model, workspace and gates.

## Migration

1. ~~`ariadne/server/` - move the plugin's routes onto `service`/`present`; verbs and views only.~~ **Built**: every
   verb is a route, errors are the rulebook's own sentence (400), SSE at `/api/events?since=<ts>`, bind checked by
   `local_only` (loopback or LAN, never the internet).
2. ~~`ariadne/ui/` - sessions list, task detail, the decision panel. Reads `present.view()`; no parsing anywhere.~~
   **Built**: one static ES module and a stylesheet, no bundler, no Node. Sessions are the only navigation, the
   needs-you strip is the funnel, the centre renders the document from `view()` (never parses prose), and the right
   column offers only the verbs the task legalises. Nothing is auto-selected: the pane stays empty until a row is
   clicked. `+ Session` reveals the submit form with empty flow/model selects and the button disabled until both are
   chosen.
3. ~~Chat v1 - session-bound conversation, service verbs, no doing-tools.~~ **Built** (`ariadne/chat.py`): the home
   is launched with `-t mcp-ariadne_tasks,skills,clarify,search`, so it cannot read files, run a terminal, write code
   or drive a browser - enforcement by construction, not by a hook. It comes from the console's chat panel
   (`POST /api/chat`) and from `ariadne chat`; the gate stays in the home as a backstop until B14.
4. Retire `desktop/`, the gate, the branding overlay; delete the nav-hiding code.
5. `worker.py` - one Hermes session per task, gates at the edge, resume on failure. Do this before the first real
   GPU run so the run tests the target design.

## Open decisions

- Packaging: a browser tab (simplest, zero dependencies) or a thin webview window later. Start with the browser.
- Chat's read-only web lookup: in or out. In makes "what's the stock price" answerable; out makes the chat purely
  about the work.
- Whether the terminal keeps its own rendering or prints `present.text()` verbatim. Recommendation: verbatim.
