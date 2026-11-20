# Models and resources

Ariadne owns model management end to end: the catalog, the server registry, the weights, the pins, and the hardware index. The user is never asked to configure Ollama, edit a config, or remember a port.

## The catalog

`serving/models.yaml` is a **closed set**. Each entry declares kind (`agent`, `generate`, `image`, `embed`), roles, size, weights (Hugging Face repo/file, or an Ollama blob) and llama-server arguments. `policy.families` is the approved set; a model outside it is refused. The LFS sha256 is pinned in `.ariadne/model-pins.json` on first fetch and verified after.

## Where inference happens

`serving/servers.yaml` (committed, never a secret) plus `.ariadne/servers.local.yaml` (this machine, gitignored) name one active server:

| Kind | What it is | Weights |
|---|---|---|
| `llama-server` | Our pinned binary (`serving/bin`, sha256 in `serving/bin.lock`), started by Ariadne | downloaded into `models/<name>/` |
| `ollama` | A local Ollama, installed by `ariadne install --system` if absent | pulled by Ollama |
| `remote` | An OpenAI-compatible or Ollama endpoint on the LAN | none - the server already has them |

`serving.py` exposes `endpoint()` and `base()` - the single answer to "where is inference". Every caller (llm, KV cache, image generation, jobs, watchdog, flow homes) reads through it.

## local_only

`ariadne/local_only.py` refuses any endpoint that is not loopback, RFC1918/ULA/link-local, a LAN suffix, or in `ARIADNE_ALLOW_HOSTS`. It also refuses any API key. `serving.check_url` runs on every `endpoint()` call, and `orchestrator.serve` re-checks the home before it starts a worker. A remote server cannot become a cloud provider. `ARIADNE_LLM_URL` remains an escape hatch for a one-off endpoint; it is checked by the same lock.

## The model index

At every startup and on demand (`python -m ariadne models index [--json] [--pulse agent|image|embed] [--refresh]`), Ariadne measures GPU/VRAM, RAM, CPU, cores, backend and free disk, then gives every catalog model one verdict:

- **`gpu`**: weights + 1.5 GB (KV cache at the 64K window, CUDA context, buffers) fits in 90% of VRAM. Fast.
- **`hybrid`**: it fits inside the profile's total (VRAM plus the share of RAM the profile allows), so part of the weights runs on the CPU. MoE models say so, because only their active parameters are computed.
- **`no`**: it does not fit, and the reason prints the two numbers.

The 1.5 GB reservation is deliberately the same for every model (`models.OVERHEAD_GB`), used by both the index and `Catalog.pickable`, so the planner's menu and the index cannot disagree.

`--pulse agent|image|embed` is opt-in: it asks Hugging Face for the most downloaded models of that task, estimates a 4-bit size from the reported parameter count, filters through the same arithmetic, and caches for a day (`--refresh` polls again). Pulse results are **suggestions**; the catalog is a closed set and admitting a model stays a person's decision.

## Resource profiles

`python -m ariadne resources [max|shared|light]` chooses how much of the machine models may take; the worker applies it between tasks. `shared` is the default: VRAM with headroom, the rest on the CPU in RAM, normal priority.

## CLI

```
ariadne models                 the catalog: what each model is for, size, where it lives, installed?
ariadne models index [--json] [--pulse agent|image|embed] [--refresh]
ariadne models install NAME... fetch and verify weights
ariadne server                 the active model server and its live probe
ariadne server list            the registered servers (the active one is marked *)
ariadne server setup           the onboarding conversation (probe, ask, reconcile, persist)
ariadne server remote URL      point at an OpenAI-compatible/Ollama endpoint on the LAN
ariadne resources [max|shared|light]
```

## llama-swap on another machine

llama-swap is just an OpenAI-compatible endpoint, so the model server does not have to be local:

```sh
python -m ariadne server remote http://gpu-box.lan:8912
python -m ariadne up
```

`local_only` accepts loopback, RFC1918 and the allowlist, so a LAN box is allowed and a public URL is refused.
