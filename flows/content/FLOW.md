# Content flow - the coordination a small planner cannot infer

Covers written pieces **and** images: documents, posts, newsletters, blog articles, marketing copy, scripts, and
the image that goes with them.

## Shape of the work
1. Fix the reader and the promise in one sentence. If the brief does not say who it is for, that is a question for
   the person, not a guess.
2. Outline before prose: the sections and the one point each makes.
3. Draft whole sections; do not append fragments to a file you have not read.
4. Edit pass against the brief: cut what does not serve the promise, keep the voice.
5. Images: one image per idea, with the model and the prompt recorded next to the file.
6. Export when a document is asked for (Pandoc); keep the Markdown as the source.

## Reference pack (whenever the piece makes claims about the world)
1. Build the pack **before** drafting: `sources/SOURCES.md` plus the fetched text under `sources/`. Each entry is
   one line, `- [S1] <url or citation> - what it supports`. Ids are stable for the whole piece.
2. Extract the claims the piece will make and attach an id to each one while outlining, not after drafting.
3. Draft with the markers in place: "the market grew 12% [S2]". A claim with no source is written as the writer's
   own judgement ("in our experience ..."), never dressed as a citation.
4. Fact-check pass before the report: for every marker, re-read the source, then confirm the claim or narrow it.
   Record the verdict on the source's line in `SOURCES.md` (`confirmed`, or `narrowed to ...`).
5. The source list is part of the report: the deliverable ends with it, and the citation gate must pass. The flow
   checks it automatically when `sources/` exists: `python -m ariadne.citations .` fails on a marker with no entry,
   and in strict mode on an entry nobody cites.
A piece that makes no claims about the world (a product announcement, an internal note) needs no pack; the gate is
skipped when there is no `sources/` folder.

## Models
- Default `gemma-4-26b-a4b` (MoE) for drafting and editing.
- `gemma-4-31b` when the prose is the deliverable and the task can afford it; say so in the step.
- The `text` server (`generate_text`) is for short passages in a fixed voice; it never rewrites the whole document.

## Tools
- `file` for the Markdown, `export` for docx/pdf, `image` for pictures (`generate_image`), `web` for source reading.
- `browser` only when the piece requires checking a live page.

## Writing rules
- Read the whole file before rewriting it; a partial read plus an append duplicates the document.
- One idea per paragraph. No throat-clearing opener, no summary that repeats the piece.
- Concrete nouns and numbers over adjectives. Cut "very", "really", "in today's world".
- Quote and attribute anyone else's words.

## Gates
- Citations: every `[S<n>]` has an entry in `sources/SOURCES.md`, and every entry is cited (see the check above).
- Word count within the range the brief gives.
- No `TODO`, `[placeholder]` or unfilled template markers.
- Every image referenced in the document exists in the workspace.
- An export gate must open the produced file (`pandoc` exit 0 plus a non-zero size), not just create it.
