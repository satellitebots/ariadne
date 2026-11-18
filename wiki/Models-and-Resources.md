# Models and resources

Reference machine: RTX 3070 Laptop (8 GB VRAM), 32 GB RAM, Windows 11. llama.cpp behind llama-swap.

## Catalog (`serving/models.yaml`)

| Use | Default | Also |
|---|---|---|
| Coding | Qwen3.6 35B-A3B (MoE, 3B active) | Qwen3.8 27B (dense, for the hardest steps), Qwen3.5 9B (quick steps) |
| Design, writing, content | Gemma 4 26B-A4B (MoE) | Gemma 4 12B, Gemma 4 31B (best prose, slow) |
| Images | Z-Image-Turbo | SD Turbo |
| Routing, memory | Qwen3.5 4B, Qwen3 Embedding 0.6B | |

Plans favour mixture-of-experts models: with only a few billion parameters active, they run several times faster
on this hardware than a dense model. `python -m ariadne models` lists the catalog. A model downloads the first
time a signed-off plan needs it.

## How the models are served

- **One agent model at a time** on the GPU. llama-swap swaps them, with KV cache parking so a swap costs a disk
  read, not a re-read of the conversation.
- **The embedding model runs on the CPU in its own group** (`side`, persistent, non-exclusive). Before this,
  every embedding call evicted the 22 GB agent model and the next agent call loaded it back ("swap thrash" in the
  RAG case study).
- **Jobs unload everything** before they run (llama-swap `/unload`).

## Resource profiles

`python -m ariadne resources <profile>`, applied between tasks:

| Profile | GPU | RAM | Priority |
|---|---|---|---|
| **max** | up to 100% | up to 80%, model pinned in RAM (mlock) | high |
| **shared** | leaves headroom | leaves headroom | normal |
| **light** | up to 80% | up to 50% | low |

The limits are measured at boot and written to `.ariadne/limits.json`. On the reference machine that is 8.0 GB of
GPU memory, 31.9 GB of RAM, and a largest model of 33.5 GB under `max`.

**Why the 80% RAM cap:** on 18 Nov the PC hard-crashed (Kernel-Power 41, no hardware errors). `max` had pinned 90%
of RAM while a CPU-heavy ingest and a QA run were going. The RAM cap was lowered to 80%; the GPU cap stays at 100%.
