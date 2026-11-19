# Design flow - the coordination a small planner cannot infer

## Shape of the work
1. Restate what is being designed and who it is for, in two sentences.
2. Decide the components: store, index, parser, model, protocol - **one choice each, with a one-line reason**.
   Never leave "X or Y" in a design.
3. Give numbers: sizes, limits, latency, cost, the version you pinned. A design without numbers cannot be built.
4. Write `DESIGN.md`, then draw the diagrams **from the same decisions** (one source per diagram).
5. Render every diagram and check it: the file exists, it is newer than its source, nothing is duplicated.

## Models
- Default `gemma-4-26b-a4b` (MoE). One model for the whole document: a design is one context.
- `gemma-4-31b` only when the prose itself is the deliverable and the task can afford the slower model.

## Tools
- `file` for DESIGN.md; the `diagram` server for Mermaid (`check_diagram`, then render SVG/PNG).
- `memory` for decisions already made in earlier tasks on this project.
- `web_fetch` for the docs of anything you name as a component, so the version is real.

## Diagrams
- Mermaid source lives in the workspace next to the document (`diagrams/*.mmd`), rendered next to it.
- **Absolute paths** for every render; relative paths land in the MCP server's folder, not the workspace.
- One diagram, one subject. If a diagram needs a legend to be read, split it.

## Gates
- "Renders" means a file exists and is newer than its source.
- "No duplicate sections" is a command gate (`grep -c '^## ' DESIGN.md` vs unique headings), not a review.
- A review gate must name the evidence the reviewer should look for.
