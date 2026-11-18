Build version 1 of the RAG system designed in C:\repos\ariadne\sandbox\rag-design\DESIGN.md (read it first; follow
its Version 1 section and component choices where they fit one machine). Build it in this folder (an empty git repo).
An 80% solution is the goal: working end to end on a real corpus, simple, tested.

- Corpus: the Kubernetes documentation, the Markdown sources under content/en/docs/concepts in the
  github.com/kubernetes/website repository (fetch only that folder, e.g. a sparse or shallow git checkout into
  `corpus/`, which must not be committed). Treat each page as a document; keep its source path and the
  kubernetes.io URL it maps to.
- Access control as in the design, simulated: give each document ACL principals from a small `acl.yaml`
  (e.g. group `platform` can read everything, group `security` can read concepts/security only, user `alice` in
  group `security`). Filter on principals inside retrieval.
- Embeddings: the local model at http://127.0.0.1:8090/v1 (OpenAI-compatible, model `embed`). Answers: the local
  model at the same URL (model `qwen3.6-35b-a3b`), with citations (URL + section) for every answer.
- Hybrid retrieval: vector search plus BM25 keyword search, merged.
- A command line: `python -m rag ingest` (build or update the index), `python -m rag ask "question" --user alice`
  (answer with citations, only from documents that user may read), `python -m rag eval` (run the golden set).
- A golden set of at least 10 Kubernetes questions with the expected source page, in `eval/golden.yaml`.
- Tests with pytest (use small fixtures; tests must not need the models running).
- README.md: setup, commands, how ACLs work, results of `rag eval`.

Gates:
- run: python -m pytest -q
- `python -m rag ingest` indexes the concepts docs (README states the document and chunk counts from a real run)
- `python -m rag ask "What is a Pod?" --user alice` returns an answer that cites a kubernetes.io URL (README shows a real transcript)
- A user without access to a page never gets it cited: a test proves the principal filter, and README shows a denied example
- `python -m rag eval` reports hit rate on the golden set (at least 10 questions); README records the number and it is at least 0.7
- Retrieval is hybrid (vector + BM25) and the code shows where they are merged
- corpus/, the index files and model outputs are not committed; the source code, tests, eval set and README are committed (clean tree)
