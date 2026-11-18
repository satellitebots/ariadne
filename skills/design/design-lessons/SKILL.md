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
