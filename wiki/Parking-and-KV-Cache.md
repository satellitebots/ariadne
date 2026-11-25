# Parking and the KV cache

## Park: a deliberate pause

There is one GPU. While a run holds it, the orchestrator waits for the run's next step boundary (the machine bar says
so). Nothing interrupts a run on its own. To take the machine now:

- **Park** (the console's *Park*, **P** in the watch window, `ariadne park <run>`): the step finishes the model or
  tool call in flight, stops at that boundary, saves its cache and releases the machine.
- **Steer** (`ariadne steer <run> "note"`, the console's steer box, or ask the orchestrator): the note is delivered
  when the step continues.
- **Resume** (`ariadne resume <run>`): the run waits for the machine, restores the cache and continues the *same*
  Hermes session with your notes.

A step that needs a login parks itself the same way (`need_login`; see [Web, browser and logins](Web-and-Browser.md)).

## KV cache parking

Every model swap throws the KV cache away, so the next call re-reads the whole conversation. Ariadne saves the
llama.cpp slot to disk under **run + step + model** whenever a step is interrupted (a park or a job) and restores it
when that step continues.

- `python -m ariadne kv` lists the caches; they are dropped when the run ends.
- Capped at 40 GB, least recently used first. `ARIADNE_KV=off` disables it.

## Small contexts

Each step starts a fresh worker and reads what earlier steps left in files, so no context grows across a task. Inside
one Hermes run, context is compressed past about 30K tokens.
