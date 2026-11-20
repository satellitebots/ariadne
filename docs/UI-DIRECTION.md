# UI direction

The console works, but it reads as a form with three columns rather than a place where work happens. This is the
design I would build instead. It is written as decisions, not mood, so it can be argued with and implemented.

## What is wrong now

1. **Three columns of equal weight.** Sessions, timeline and the task all compete; nothing says where to look. The
   task - the thing the product is about - is a card in the middle column, below a row of pills.
2. **The first interaction is a form.** `+ Session` opens six fields (brief, flow, model, workspace, session, gates).
   The flow is chosen from a `<select>` whose options are paragraphs. That is a configuration dialog wearing the
   clothes of a home screen.
3. **State is text.** "needs you", "running", "done" are words in a pill. The one thing a person needs - where this
   task is between plan, sign-off, execution, QA and report - has no shape.
4. **Chat is an afterthought.** It lives in a `<details>` under the task, so the surface that should be the easiest
   way in is the hardest to find.
5. **The decision is buried.** Approve / revise / cancel are buttons at the bottom of a long card, mixed with gates
   and metadata. The next legal action should be the most prominent thing on the screen.
6. **No keyboard, no command palette, no flow.** Every action is a mouse trip to a different column.

## The thesis

**A session is the home. A task is a document. The composer is the only action.**

Everything else is navigation to those three things. A person should be able to open Ariadne, see what needs them,
type a sentence, and sign off a plan without ever seeing a settings field unless they ask for one.

## Principles

1. **One primary action per screen.** The button that moves the work forward is the only filled button; everything
   else is quiet. When a task is `awaiting_signoff`, that button is Approve. When it is `executing`, it is Steer.
   When it is `needs_attention`, it is Fix.
2. **State is spatial, not textual.** A phase rail (Brief → Plan → Sign-off → Execute → QA → Report) shows where the
   task is. The current phase is the only one with weight; completed phases are checkmarks; future phases are faint.
3. **The brief is a document.** Render the backbrief with real typography: mission, steps, gates, risks. Not a JSON
   dump, not a `<pre>`.
4. **Progressive disclosure.** Workspace defaults to the session's; model defaults to the flow's; gates are proposed.
   All three live behind "Details" in the composer. The composer asks for one thing: what should be true when it is
   done?
5. **Chat is a mode, not a panel.** The composer has two modes: **Task** and **Chat**. Same place, same width, same
   send key. Chat can submit a task; task mode is the fast path.
6. **The next action is always visible.** A sticky decision bar at the bottom of a task shows the legal verbs for its
   status, with the primary one filled. No hunting.
7. **Keyboard first.** `⌘K` / `Ctrl+K` opens a command palette (new task, go to session, approve, steer, stop).
   `j`/`k` move through the inbox, `Enter` opens, `Esc` closes, `⌘Enter` sends. The mouse is optional.
8. **Motion only explains change.** A phase advancing, a task arriving in the inbox, a model unloading. No spinners
   without a sentence; no bounce.

## Information architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Ariadne        [Inbox 3]   [Sessions]   [Models ●]            ⌘K   [Stop]     │
├───────────────┬──────────────────────────────────────────────────────────────┤
│ SESSIONS      │  Session: ariadne                     coding · qwen3.6-35b-a3b │
│               │                                                              │
│ ● ariadne     │  ┌ phase rail ─────────────────────────────────────────────┐  │
│   api         │  │ Brief ✓  Plan ✓  Sign-off ●  Execute ○  QA ○  Report ○ │  │
│   docs        │  └─────────────────────────────────────────────────────────┘  │
│               │                                                              │
│ + New session │  Backbrief                                                   │
│               │  Mission …                                                   │
│               │  Steps …                                                     │
│               │  Gates …                                                     │
│               │                                                              │
│               │  ┌ decision bar (sticky) ──────────────────────────────────┐  │
│               │  │  Approve        Revise…        Cancel                   │  │
│               │  └─────────────────────────────────────────────────────────┘  │
├───────────────┴──────────────────────────────────────────────────────────────┤
│  [ Task | Chat ]   What should be true when it is done?              ⌘Enter  │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Left rail (280 px):** sessions, newest activity first, with a one-line last event and an unread dot. Not a
  filter - a list of places.
- **Center:** the open session's stream, newest task first as a card; opening a card makes it the document. The
  phase rail sits at the top of the document, not on the card.
- **Composer:** fixed at the bottom, full center width. Task/Chat toggle. One textarea that grows. `⌘Enter` sends.
  "Details" expands flow, model, workspace, gates, session.
- **Inbox:** a separate view (top-left count) that is one decision per card: the task, the one question it asks, the
  primary button, and a "why" line. `j`/`k` + `Enter` gets through it in seconds.

## Components

| Component | Rule |
|---|---|
| `SessionRow` | name, flow, last event, unread dot; active row has a 2 px accent left edge, not a filled background |
| `TaskCard` | one line of intent, phase, elapsed, gate count; never more than two lines of text |
| `PhaseRail` | six steps, current one weighted; clicking a completed step scrolls to its section |
| `DecisionBar` | sticky, bottom of the document; exactly one filled button; secondary verbs are text buttons |
| `Composer` | Task/Chat tabs, auto-growing textarea, `⌘Enter`; Details is a disclosure, closed by default |
| `GateList` | `run:` gates in mono with a pass/fail dot; review gates as plain sentences |
| `ActivityStream` | one line per event, timestamp on hover, auto-follow with a "jump to latest" chip when scrolled up |
| `EmptyState` | one sentence, one button; never a paragraph of instructions |

## Visual system

- **Type:** 13 px UI, 15 px body, 20 px section, 28 px document title; line-height 1.5; system font; mono only for
  commands, paths and ids.
- **Space:** 8 px base; 16 px gutters; 24 px between sections. No arbitrary 10/14 px paddings.
- **Color:** one accent (`#7cc7ff`), one surface ramp (bg / panel / raised), semantic colors only for state
  (ok / warn / bad). Status is never color alone - it always has a word or a shape.
- **Borders:** 1 px `--line`; 10 px radius on cards, 8 px on controls, 999 px on pills. No shadows except the
  composer, which lifts 1 px when focused.
- **Theme:** dark default, light via `prefers-color-scheme`; both defined as tokens, no hard-coded colors in
  components.
- **Focus:** 2 px accent ring, never removed; every interactive element reachable by Tab.

## Copy

Verbs, not nouns: **Give the task**, **Approve**, **Send back**, **Steer**, **Cancel**, **Fix**. Statuses in plain
words: "waiting for you", "working", "checking", "done", "needs a decision". No "submit", no "revise", no
"awaiting_signoff" in the interface.

## States

- **Empty:** one sentence + one button ("Nothing needs you. Start a session.").
- **Loading:** skeleton rows shaped like the content, never a centered spinner.
- **Models down:** a persistent strip under the header with the reason and a Retry; the console stays usable
  (inbox, reading, steering).
- **Long running:** elapsed time + the current step ("step 3 of 5 · running pytest"), not a spinner.
- **Error:** the failing gate and its output in a collapsible block, with "Send back with this" as the action.

## Build order

1. **Shell:** header, session rail, center stream, composer; replace the three-column grid and the `<details>` chat.
2. **Task document:** phase rail, document typography, sticky decision bar, gate list.
3. **Inbox:** decision cards, `j`/`k`/`Enter`, command palette.
4. **Polish:** light theme, empty/loading/error states, motion, accessibility pass.

Each step is shippable on its own; nothing in step 2 depends on step 3.
