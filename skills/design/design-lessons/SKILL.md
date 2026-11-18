---
name: design-lessons
description: How to write a system design that an engineer can build from - decisions, numbers, diagrams that match the text.
---
# Design lessons

Learned from reviews of earlier designs (first RAG design draft: real design, too thin to build from).

## Decide, do not list
- One choice per component (store, index, parser, re-ranker, model), each with a one-line reason. Never "X or Y".
- Name exact versions, models and endpoints when they exist locally (e.g. embeddings: Qwen3 Embedding 0.6B at
  http://127.0.0.1:8090/v1, model `embed`).

## Give numbers
- Size the target scale: documents -> chunks -> vectors, index size on disk, RAM, ingestion time on one machine,
  and the point where it needs sharding.
- State assumptions (average document size, chunk size, overlap) so the numbers can be checked.

## Access control at scale
- Store ACL principals (users, groups) on every chunk at ingestion; expand the user's groups at query time and
  filter on principals inside the search. A list of allowed document ids does not scale to millions of documents.
- Say what happens when permissions change on the source (re-permissioning without re-embedding).

## Diagrams must match the text
- Every component and data path in the text appears in a diagram, and every edge in a diagram is explained.
  (The first draft never fed the keyword index.)
- Check with check_diagram, render with render_diagram, and re-render after any change to the source.
- Link every rendered diagram (PNG) in the document and embed its Mermaid source.

## Hand over through files
- Write the document early and improve it in place; content only "thought" in one step is lost by the next.
- To rewrite a file, read it whole first (no offset/limit) or change it with patch. write_file refuses to
  overwrite a file you only read in pages; never work around that by appending a second copy. (RAG design
  iteration 3: 21 refused writes, and the new design ended up appended under the old one, every section twice.)
- Give tools absolute paths inside the workspace (render_diagram output, export, images). A relative path lands
  in the tool server's own folder, not the workspace. After rendering, list diagrams/ and confirm the PNG and SVG
  are newer than their .mmd.

## One source per diagram
- diagrams/<name>.mmd is the source. When a diagram changes, edit the .mmd, re-render PNG and SVG from it, then
  copy the same Mermaid into DESIGN.md. Never change only the copy in DESIGN.md: the rendered image keeps the
  old content (RAG design: DESIGN.md said qwen3.6, architecture.png still said Llama-3).
- Render last, after the final edit of every diagram.

## Before you finish
- Every section heading appears once. Every diagram in diagrams/ is rendered, current and linked.
