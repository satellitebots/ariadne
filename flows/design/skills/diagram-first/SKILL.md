---
name: diagram-first
description: Plan and design with Mermaid diagrams - pick the right diagram, keep it readable, check it, render it, and keep the source next to the picture.
---
# Diagram first

Use a diagram whenever the answer has structure: parts and how they connect, steps in order, who calls whom,
states and transitions, data and its relations, a layout.

## Pick the diagram

| Question | Mermaid |
|---|---|
| What are the parts and how do they connect? | `flowchart LR` (architecture), `architecture-beta` |
| What happens, in what order, with decisions? | `flowchart TD` |
| Who calls whom, when? | `sequenceDiagram` |
| What states can it be in? | `stateDiagram-v2` |
| What data, and how is it related? | `erDiagram`, `classDiagram` |
| When does what happen? | `gantt`, `timeline` |
| How is a screen laid out? | `block-beta` (boxes in rows/columns) |
| What are the options or the scope? | `mindmap` |

## Make it readable

- One question per diagram. Over ~15 nodes, split it into an overview and detail diagrams.
- Nodes are nouns (`api[Task API]`), edges are verbs (`api -->|stores| db`). Label every edge unless it is obvious.
- Show flow with arrows, not with repeated nodes. One edge per relationship.
- Group with `subgraph` by owner or boundary (process, machine, team). Keep one direction (LR or TD).
- Use plain ids (`task_api`), readable labels in brackets, and quotes for labels with punctuation.

## Check, render, keep the source

1. `check_diagram(source)` until it returns `ok`. Fix the line the error names; do not guess around it.
2. `render_diagram(source, "docs/diagrams/<name>.svg")` - it saves `<name>.mmd` next to the picture.
3. In Markdown documents, also embed the source in a ```mermaid block so it renders on GitHub.
4. Record in shared memory (`memory_record`) where the diagrams live and what each one answers.
