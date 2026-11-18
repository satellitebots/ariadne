Design a retrieval-augmented generation (RAG) system for a mid-size company whose knowledge is spread across many
places: network file shares (SMB), SharePoint/OneDrive folders, a Confluence-style wiki, Git repositories with
docs, and people's local folders synced to a shared drive. Everything must run on the company's own hardware with
local models (no cloud AI APIs).

The design must cover:
- Connectors and crawling: how each source is found, read incrementally, and re-synced (changes, deletes).
- Access control: users must only get answers from documents they are allowed to read (permissions carried
  from each source into the index and enforced at query time).
- Ingestion: parsing (PDF, Office, Markdown, HTML, code), chunking, metadata, deduplication.
- Index: embeddings (local model), vector store plus keyword search (hybrid), and where each lives.
- Query path: retrieval, re-ranking, answer generation with citations back to the source document and location.
- Operations: freshness, monitoring, evaluation (how we know answers are good), scale (start: ~2 million documents).
- A first-version scope (what to build first, what to leave for later).

Deliverables in this folder:
- `DESIGN.md`: the design, with the Mermaid source of every diagram embedded in ```mermaid blocks.
- Diagrams rendered to `diagrams/*.svg` (and .png) with their .mmd sources: at least an architecture overview
  (components and data flow), an ingestion/sync sequence, and a query-time sequence including the permission check.
- The first version will be built and tested on the Kubernetes documentation (https://kubernetes.io/docs/home/)
  as the sample corpus, so say how that maps onto the design.
