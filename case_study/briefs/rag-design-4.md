Finish the RAG design in this folder (DESIGN.md and diagrams/). The design content is done; this pass is
finishing work only. Do not redesign.

1. Render every diagram: for each diagrams/*.mmd, call render_diagram twice with ABSOLUTE output paths in this
   workspace (C:\repos\ariadne\sandbox\rag-design\diagrams\<name>.png and .svg). Relative paths are refused.
   Then list diagrams/ and confirm each .png and .svg is newer than its .mmd.
2. In DESIGN.md, link every rendered diagram (PNG) under the Diagrams section and embed its Mermaid source.
3. Name the generator and embeddings from the local catalog: generator qwen3.6-35b-a3b, embeddings `embed`
   (Qwen3 Embedding 0.6B at http://127.0.0.1:8090/v1). Replace Llama-3-8B.
4. Sizing: show the vector math for RAM (vectors x dimensions x bytes, plus HNSW overhead) and correct the total.
5. Edit DESIGN.md with patch, or read it whole before write_file. Never append a second copy.

Gates:
- run: python -c "import pathlib,sys; d=pathlib.Path('diagrams'); bad=[m.name for m in d.glob('*.mmd') for x in ('.png','.svg') if not m.with_suffix(x).exists() or m.with_suffix(x).stat().st_mtime < m.stat().st_mtime]; print(bad); sys.exit(1 if bad else 0)"
- run: python -c "import collections,sys; h=[l for l in open('DESIGN.md',encoding='utf-8') if l.startswith('## ')]; c=[k for k,v in collections.Counter(h).items() if v>1]; print(c); sys.exit(1 if c else 0)"
- Every diagrams/*.png is linked from DESIGN.md
- DESIGN.md names qwen3.6-35b-a3b as the generator and `embed` as the embedding model; no Llama-3
- The sizing section shows the RAM arithmetic (vectors x dimensions x bytes) and its total follows from it
