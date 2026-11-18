Continue iteration 2 of the RAG design (the last run ran out of time): DESIGN.md was rewritten but the diagrams were not re-rendered. Check DESIGN.md against everything below, fix what is missing, re-render all diagrams.

Iteration 2 of the company RAG design in this folder (DESIGN.md and diagrams/ are the first draft from the last
task in this session). The draft covers every section but is too thin to build from. Revise DESIGN.md and the
diagrams so an engineer could build version 1 from it:

- Make concrete choices, one per component, with a one-line reason each: the vector store, the keyword index
  (BM25), the metadata/ACL store, the parser, the chunker settings, the re-ranker, and the generator. Embeddings use
  our local Qwen3 Embedding 0.6B (served at http://127.0.0.1:8090/v1, model `embed`).
- Access control: store ACL principals (users and groups) on every chunk at ingestion; at query time expand the
  user's groups (from AD/LDAP) and filter on principals inside the search. Do not filter by a list of allowed
  document ids (does not scale to 2 million documents). Show this in the query sequence diagram.
- The architecture diagram must show the keyword index being fed at ingestion, and the ACL path.
- Sizing for 2 million documents: estimated chunks, vector count, index size on disk, RAM, ingestion time on one
  machine, and how to shard when it outgrows one machine.
- Freshness, deletes and re-permissioning: what happens when a file's permissions change.
- Evaluation: a small golden question set and the metrics to track.
- Version 1 for the Kubernetes docs: the exact corpus (which part of kubernetes.io/docs), the components used, and
  what is deliberately left out.
- Link all three rendered PNGs in DESIGN.md (not just the first).

Gates:
- DESIGN.md names exactly one choice for vector store, keyword index, ACL store, parser, re-ranker and generator, each with a reason
- DESIGN.md stores ACL principals per chunk and filters on them at query time; it does not filter on a list of allowed document ids
- The architecture diagram shows ingestion feeding both the vector index and the keyword index
- The query sequence diagram shows group expansion and the principal filter inside retrieval
- DESIGN.md has a sizing section with numbers for 2 million documents (chunks, vectors, disk, RAM, ingestion time)
- DESIGN.md has a Version 1 section that maps the design onto the Kubernetes docs corpus
- All three diagrams are rendered (diagrams/*.png and *.svg exist, newer than DESIGN.md's first draft) and linked from DESIGN.md

