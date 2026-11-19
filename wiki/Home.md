# Ariadne wiki

Ariadne is a harness for doing real work with **local models only**, on one consumer machine. It sits on an
unmodified, pinned [Hermes Agent](https://github.com/NousResearch/hermes-agent) and adds a fixed way of working:
the task comes with check gates, the model plans read-only, you sign off the plan, and then it executes and checks
every gate until they pass.

This wiki is the map. The [README](../README.md) is the quick start. The [case studies](Case-Studies.md) show
real runs.

## The idea in five lines

1. **You set the bar.** A task states how we will know it is done (check gates). Without gates, nothing starts.
2. **The model plans; you decide.** A read-only plan comes back as a backbrief: steps, a model per step, which step
   passes which gate. You approve, revise or cancel it.
3. **Models think and write; Ariadne runs.** Heavy work (installs, ingest, builds, test suites) is written as a
   script and handed to Ariadne as a job. The model is unloaded while the job has the machine.
4. **Nothing is interrupted by accident.** Work runs outside any terminal or chat. It pauses only when you park it
   or a login is needed, and it stops only when you stop it.
5. **Hermes is the worker runtime, not the product.** Ariadne keeps what Hermes is good at - sessions, tools, MCP,
   skills - and owns its own frontend. `upstream/` is never edited.

Three documents outrank every page in this wiki: [`docs/DESIGN-RESET.md`](../docs/DESIGN-RESET.md) (the drill and
the backend shape), [`docs/FRONTEND.md`](../docs/FRONTEND.md) (our own UI and chat, decoupled from the Hermes
desktop shell), and [`docs/MCP.md`](../docs/MCP.md) (how Claude or any MCP client integrates). Where a page below
disagrees with those, the page is stale - the status column says which.

## The funnel

```
doors              our UI (browser) · terminal · MCP client
                      │  same verbs, same document
                    service.py ── present.py
                      │
                    store ── one queue, one truth
                      │
                    worker ── one Hermes session, one local model
                      │
                    gates → report → workspace + session memory
```

Many doors, one stream. No surface owns a rule (`service.py`); no surface formats a task (`present.py`).

## Pages

| Page | Status |
|---|---|
| [Task-Lifecycle](Task-Lifecycle.md) | current - the drill, retries, what each status means |
| [Operations](Operations.md) | current - install, up, down, doctor |
| [Jobs](Jobs.md) · [Parking-and-KV-Cache](Parking-and-KV-Cache.md) · [Web-and-Browser](Web-and-Browser.md) | current |
| [Case-Studies](Case-Studies.md) | current |
| [CLI-Reference](CLI-Reference.md) | partly current - missing `local-only` and the explicit flow/model rule |
| [Flows-and-Skills](Flows-and-Skills.md) | **stale** - `writing` is retired; flows are coding, design, investigation, content |
| [Models-and-Resources](Models-and-Resources.md) | **stale** - policy now lives in `serving/models.yaml` under `policy:` |
| [Concepts](Concepts.md) | **stale** - the session is the unit of work; schedules are created from a session |
| [Architecture](Architecture.md) | **stale** - the Hermes desktop plugin is retired; see `docs/FRONTEND.md` |
| [Decisions](Decisions.md) | **stale** - missing the frontend pivot and the local-only provider lock |
| [Status-and-Roadmap](Status-and-Roadmap.md) | **stale** - the migration order is in `docs/FRONTEND.md` |
| [Desktop](Desktop.md) | **retired** - kept only until the new frontend lands |

## Rules that do not bend

- **Closed sets.** Flows (`flows/flows.yaml`), models (`policy.families` in `serving/models.yaml`), tools
  (`flows/tools.yaml`). Unknown is refused, never guessed.
- **Local-only inference.** Every `base_url` must be loopback, LAN, or allowlisted; a cloud provider name with no
  `base_url`, or any `api_key`, stops the run before it starts. The model may still use the internet.
- **Explicit choice.** The person names the flow, the model and the gates. Nothing is pre-selected.

## Status

Coding flow beta; design, investigation and content shipped but not validated end to end. The frontend is mid-pivot:
the Hermes plugin page is retired in favour of our own UI, which does not exist yet - the terminal and MCP are the
working doors today.
