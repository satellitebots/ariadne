# Model management (native to Ariadne)

Ariadne owns model management end to end. The user is never asked to go configure Ollama, edit a Hermes config, or
remember a port. Everything lives in this repo: the catalog in `serving/models.yaml`, the binaries in `serving/bin`
(sha256-pinned by `serving/bin.lock`), the weights in `models/<name>/`, and the pin record in
`.ariadne/model-pins.json`.

## What already exists

- `ariadne/models.py`: the catalog (`Catalog`, `Model`), `plan_fetch()`, `install()`, `missing()`, and the pin file —
  a Hugging Face LFS sha256 is recorded on first fetch and verified on every fetch after.
- `serving/bin`: our own `llama-server` and `stable-diffusion.cpp`, fetched by `deps.py` with a sha256 check, so a
  machine with nothing installed still gets a working runtime from the repo.
- `serving/llama-swap.yaml` + `llama_server_exclusive.py`: one model on the GPU at a time.
- `ariadne/deps.py`: installs `ollama` (winget/brew/apt) and the other system tools, and `doctor` reports what is
  missing without changing anything.
- `ariadne/local_only.py`: refuses any endpoint that is not loopback, LAN, or allowlisted.

## What is missing: the server abstraction

A **model server** is where inference happens. Ariadne recognises three kinds, and one is always *active*:

| Kind | What it is | Weights |
|---|---|---|
| `llama-server` | our pinned binary, started by Ariadne | downloaded by us into `models/` |
| `ollama` | a local Ollama, installed by `ariadne install --system` if absent | pulled by Ollama |
| `remote` | an OpenAI-compatible or Ollama endpoint on the LAN (`http://192.168.x.x:11434`) | **none** — the server already has them |

Registration lives in `serving/servers.yaml` (committed, never a secret) with a machine-local override in
`.ariadne/servers.local.yaml` (gitignored) holding the active choice and any LAN URL. Every URL is checked by
`local_only` before it is used, so a remote server cannot become a cloud provider.

## Onboarding: the conversation Ariadne has

`ariadne models setup` (and the first run of `ariadne up` when no server is registered) asks, in this order:

1. **Probe.** Is a `llama-server` binary present? Is Ollama running on `127.0.0.1:11434`? Is a GPU visible
   (`deps.gpu()`), and how much VRAM?
2. **If nothing is found**, offer exactly three answers:
   - *Use the runtime in this repo* — no install, we start our own `llama-server` (default, recommended).
   - *Install Ollama here* — runs `deps.install(system=True)` and shows the command it will run first.
   - *Point at a server on my network* — asks for a URL, validates it (`local_only` + a live `/api/tags` or
     `/v1/models` probe), enumerates what it serves, and registers it.
3. **Reconcile.** Compare the approved catalog with what the chosen server actually has. Report three lists:
   available now, fetchable (with size and free-disk check), and unavailable (the flow that needs it is refused with
   the reason, not silently downgraded).
4. **Persist** the choice and print what happens next.

Non-interactive use (`--json`, or a CI box) takes flags instead: `ariadne models setup --remote http://gpu.lan:11434`
or `--local llama-server`.

## Fetching

- `ariadne models install <name>` → `plan_fetch()` resolves the HF repo/file, checks free disk against the size in
  the catalog, downloads into `models/<name>/`, verifies the sha256 (recording it on first fetch), and registers the
  model as available.
- Downloads are **authorised by sign-off**, not by the fetch: the backbrief names what will be fetched
  (`TO FETCH AFTER SIGN-OFF`) and approving it is the permission. `prepare()` runs before step 1.
- A `remote` server never downloads: its models are enumerated from the server, and a task may name one only if it
  is in the approved catalog.
- Interrupted fetches resume; a pin mismatch is a hard failure with the expected and actual hashes printed.

## Selection at runtime

The task's model is explicit (chosen at submit, changeable at sign-off). The worker resolves it against the active
server: present → load it; absent but fetchable → fetch it (already authorised); absent and not fetchable →
`needs_attention` naming the gap. Only one model holds the GPU at a time, and the planner's model is unloaded after
sign-off.

## CLI

```
ariadne models                 the catalog: what each model is for, size, where it lives, installed?
ariadne models setup           the onboarding conversation above
ariadne models server          show / change the active server (local llama-server, local ollama, remote URL)
ariadne models install <name>  fetch and verify weights
ariadne models use <name>      make a model the default for new tasks
```

## To build

1. ~~`serving/servers.yaml` + `.ariadne/servers.local.yaml`, and a `ModelServer` type (kind, url, probe, list) in
   `ariadne/serving.py`.~~ **Built**: `serving.py` (kind, url, `probe`, `reconcile`, `use`), plus `endpoint()` /
   `base()` - the one answer to "where is inference".
2. `models setup` with the probe → ask → reconcile → persist flow; `models server` to switch. **Partly built**: the
   flow lives in `ariadne server setup`; `ariadne models setup` still has to become its alias.
3. ~~Route every inference call through the active server instead of assuming a local binary.~~ **Built** (B3):
   `llm`, the KV cache, image generation, jobs' unload, the watchdog and every compiled flow home read
   `serving.endpoint()`; `serve` starts our binary only when it is the active kind.
4. ~~`local_only` checks the server URL at registration and at startup.~~ **Built**: `serving.check_url` on every
   `endpoint()`, and `orchestrator.serve` re-checks the home before it starts a worker.

`ARIADNE_LLM_URL` remains an escape hatch for a one-off endpoint; it is checked by the same lock, so it cannot
become a cloud provider.
