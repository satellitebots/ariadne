# Models and resources

Ariadne owns model management end to end: the catalog, the server registry, the weights and the pins.

## The catalog

`serving/models.yaml` is a **closed set**. Each entry declares kind (`agent`, `generate`, `image`, `embed`), roles,
size, weights (Hugging Face repo/file, or an Ollama blob) and llama-server arguments. `policy.families` is the approved
set; a model outside it is refused. The LFS sha256 is pinned in `.ariadne/model-pins.json` on first fetch and verified
after.

## Where inference happens

`serving/servers.yaml` (committed) plus `.ariadne/servers.local.yaml` (this machine) name one active server:

- our pinned `llama-server` (binary in `serving/bin`, sha256 in `serving/bin.lock`), started by Ariadne;
- a local `ollama`;
- a `remote` OpenAI-compatible/Ollama URL on the LAN - no weights downloaded here.

`serving.endpoint()` is the single answer to "where is inference"; every caller reads it. `local_only` refuses any
endpoint that is not loopback, RFC1918/ULA/link-local, a LAN suffix or in `ARIADNE_ALLOW_HOSTS`, and refuses any key.

## The model index

At every startup and on demand (`python -m ariadne models index`), Ariadne measures GPU/VRAM, RAM, CPU, cores,
backend and free disk, then gives every catalog model one verdict:

- `gpu`: weights + 1.5 GB (KV at the 64K window, CUDA context, buffers) fits in 90% of VRAM;
- `hybrid`: it fits inside the profile's total, so part of the weights runs on the CPU (MoE models note why that
  costs less);
- `no`: it does not fit, with both numbers in the reason.

The planner's menu uses the same rule, so the catalog and the index cannot disagree. `--pulse agent|image|embed`
asks Hugging Face for the most downloaded models of that task, estimates a q4 size from the reported parameter
count, filters by the same arithmetic and caches for a day (`--refresh` polls again). Suggestions never edit the
catalog.

## Resource profiles

`python -m ariadne resources [max|shared|light]` chooses how much of the machine models may take; the worker applies it
between tasks. `shared` is the default: VRAM with headroom, the rest on the CPU in RAM, normal priority.
