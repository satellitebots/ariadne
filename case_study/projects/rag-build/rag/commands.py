"""Commands: ingest, ask, eval — implemented as argparse subcommands."""

import argparse
import json
import sys
from pathlib import Path

from rag.acl import ACL
from rag.chunker import chunk_document
from rag.embedder import Embedder
from rag.generator import Generator
from rag.index import Index
from rag.eval import load_golden_set, run_eval_set, EvalResult


def cmd_ingest(args):
    """Ingest documents from the corpus/ directory into the index."""
    corpus_dir = Path(args.corpus)
    if not corpus_dir.exists():
        print(f"Error: corpus directory '{corpus_dir}' not found.", file=sys.stderr)
        sys.exit(1)

    acl = ACL(args.acl)
    embedder = Embedder(args.base_url)
    index = Index(args.db)

    md_files = sorted(corpus_dir.rglob("*.md"))
    doc_count = 0
    chunk_count = 0
    errors = 0

    for md_file in md_files:
        source_path = str(md_file.relative_to(corpus_dir))
        # Map source path to kubernetes.io URL
        # e.g. "corpus/content/en/docs/concepts/workloads/pods/_index.md"
        # -> "https://kubernetes.io/docs/concepts/workloads/pods/"
        path_parts = source_path.replace("\\", "/").split("/")
        # Remove leading "content" and "en/docs" prefix
        if path_parts[0] == "content":
            path_parts = path_parts[1:]
        # Skip "en" and "docs" segments
        while path_parts and path_parts[0] in ("en", "docs"):
            path_parts.pop(0)
        # Strip .md extension
        if path_parts and path_parts[-1].endswith(".md"):
            path_parts[-1] = path_parts[-1][:-3]

        url = "https://kubernetes.io/docs/" + "/".join(path_parts)
        if not url.endswith("/"):
            url += "/"

        principals = acl.get_principals_for_doc(source_path)

        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"  Skipping {source_path}: {e}", file=sys.stderr)
            errors += 1
            continue

        # Skip very small files
        if len(text.strip()) < 100:
            continue

        index.add_document(
            doc_id=source_path,
            url=url,
            source_path=source_path,
            principals=principals,
        )

        for chunk in chunk_document(
            doc_id=source_path, text=text, url=url,
            chunk_size=500, overlap=0.1
        ):
            try:
                emb = embedder.embed([chunk.text])
                index.add_chunk(
                    chunk_id=chunk.chunk_id,
                    doc_id=chunk.doc_id,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    url=chunk.url,
                    principals=principals,
                    embedding=emb[0],
                )
                chunk_count += 1
            except Exception as e:
                print(f"  Embedding error for {source_path} chunk {chunk.chunk_index}: {e}",
                      file=sys.stderr)
                errors += 1
                continue

        doc_count += 1
        if doc_count % 5 == 0:
            print(f"  Ingested {doc_count} docs, {chunk_count} chunks...")

    index.commit()
    print(f"Done. {doc_count} documents, {chunk_count} chunks indexed "
          f"({errors} errors).")
    return 0


def cmd_ask(args):
    """Answer a question using hybrid retrieval + generation."""
    acl = ACL(args.acl)
    embedder = Embedder(args.base_url)
    generator = Generator(args.base_url)
    index = Index(args.db)

    # Resolve user principals
    user_principals = acl.resolve_user_principals(args.user)

    # Embed the query
    query_vec = embedder.embed([args.question])[0]

    # Hybrid search with ACL
    chunks = index.search_with_acl(
        query=args.question,
        query_vec=query_vec,
        user_principals=list(user_principals),
        top_k=10,
    )

    if not chunks:
        print("No relevant documents found for this user's permissions.")
        return 0

    # Build context with citations
    context_lines = []
    for i, chunk in enumerate(chunks):
        context_lines.append(
            f"[{i+1}] URL: {chunk['url']} | Principals: {chunk['principals']}\n"
            f"    {chunk['text']}"
        )
    context = "\n\n".join(context_lines)

    # Generate answer
    system_prompt = (
        "You are a helpful assistant that answers questions about Kubernetes. "
        "Use ONLY the provided context to answer. Cite the kubernetes.io URL "
        "for each claim. If the context doesn't contain enough information, "
        "say so."
    )
    user_prompt = (
        f"Question: {args.question}\n\n"
        f"Context:\n{context}\n\n"
        "Answer with citations to kubernetes.io URLs."
    )

    try:
        answer = generator.generate([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ])
    except Exception as e:
        print(f"Generation error: {e}", file=sys.stderr)
        answer = "Could not generate an answer."

    print(f"\nAnswer:\n{answer}\n")
    print("--- Retrieved chunks ---")
    for chunk in chunks:
        print(f"  URL: {chunk['url']}")
        print(f"  Text: {chunk['text'][:200]}...")
        print()

    return 0


def cmd_eval(args):
    """Run the golden set evaluation."""
    acl = ACL(args.acl)
    embedder = Embedder(args.base_url)
    generator = Generator(args.base_url)
    index = Index(args.db)

    user_principals = acl.resolve_user_principals(args.user)

    try:
        summary = run_eval_set(
            index=index,
            embedder=embedder,
            generator=generator,
            user_principals=user_principals,
            top_k=args.top_k,
        )
    except Exception as e:
        print(f"Evaluation error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== Evaluation Results ===")
    print(f"Total questions: {summary.total}")
    print(f"Hit rate (recall@{args.top_k}): {summary.hit_rate:.2%}")
    print(f"Average precision: {summary.avg_precision:.2%}")
    print(f"Average recall: {summary.avg_recall:.2%}")

    print(f"\nDetailed results:")
    for r in summary.results:
        status = "HIT" if r.hit else "MISS"
        print(f"  [{status}] {r.question}")
        print(f"    Expected: {r.expected_urls}")
        print(f"    Retrieved: {r.retrieved_urls}")

    # Save results to JSON
    results_path = Path("eval/results.json")
    results_data = {
        "total": summary.total,
        "hits": summary.hits,
        "hit_rate": summary.hit_rate,
        "avg_precision": summary.avg_precision,
        "avg_recall": summary.avg_recall,
        "results": [
            {
                "question": r.question,
                "expected_urls": r.expected_urls,
                "retrieved_urls": r.retrieved_urls,
                "hit": r.hit,
                "precision": r.precision,
                "recall": r.recall,
            }
            for r in summary.results
        ],
    }
    with open(results_path, "w") as f:
        json.dump(results_data, f, indent=2)
    print(f"\nResults saved to {results_path}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="rag",
        description="Local RAG system for Kubernetes documentation",
    )
    parser.add_argument("--acl", default="acl.yaml",
                        help="Path to ACL config YAML")
    parser.add_argument("--db", default="rag/index.db",
                        help="Path to SQLite index database")
    parser.add_argument("--base-url", default="http://127.0.0.1:8090/v1",
                        help="Base URL for the local model API")

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # ingest
    ingest_parser = subparsers.add_parser("ingest", help="Ingest documents")
    ingest_parser.add_argument("corpus", nargs="?", default="corpus",
                               help="Path to corpus directory")
    ingest_parser.set_defaults(func=cmd_ingest)

    # ask
    ask_parser = subparsers.add_parser("ask", help="Ask a question")
    ask_parser.add_argument("question", help="Question to ask")
    ask_parser.add_argument("--user", required=True, help="User principal")
    ask_parser.add_argument("--top-k", type=int, default=10)
    ask_parser.set_defaults(func=cmd_ask)

    # eval
    eval_parser = subparsers.add_parser("eval", help="Run evaluation")
    eval_parser.add_argument("--user", default="alice", help="User for ACL")
    eval_parser.add_argument("--top-k", type=int, default=5)
    eval_parser.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    return args.func(args) or 0
