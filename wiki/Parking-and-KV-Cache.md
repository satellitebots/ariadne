# Parking and the KV cache

## Park: a deliberate pause

There is one GPU and one model slot. While a task runs, your chat waits for the task's current run to finish.
Nothing interrupts a task on its own. To have the model now:

- **Park** (console *Park*, **P** in the watch window, `python -m ariadne park`): the task finishes the model
  or tool call in flight, stops at that step boundary, saves its KV cache and waits.
- **Resume** (console *Resume*, **R**, `python -m ariadne park --resume`): the cache is restored and the
  *same* Hermes session continues, told to pick up where it left off.

A park never resumes on its own. The only other thing that parks a task is a step that needs a login
(`need_login`, see [Web, browser and logins](Web-and-Browser.md)).

The state is one file, `.ariadne/park.json`, so the worker, CLI, watch window and console all see the same
thing.

## KV cache parking

Every model swap normally throws away the model's KV cache, so the next run re-reads (prefills) the whole
conversation. Ariadne saves the llama.cpp slot to disk after each run, under **session + step + model**, and
restores it when that session resumes on that model.

- `python -m ariadne kv` lists the caches; `kv drop SESSION` forgets one.
- They are capped at 40 GB, and the least recently used go first. Set `ARIADNE_KV=off` to disable.

## Checkpoints: keeping contexts small

Small models work best with small contexts. At every phase boundary (plan approved, each step group done, QA
done), the model that just worked writes a handoff brief, and the next phase starts a fresh segment from it.
Inside a run, Hermes compresses past about 30K tokens. On the case-study runs that compression took about 85 s per
pass, with a median 22% reduction.
