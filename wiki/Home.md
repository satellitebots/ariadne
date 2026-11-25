# Ariadne wiki

Ariadne runs **durable tasks on local models**. With the help of a local orchestrator you define a task (a chain of
steps), sign it, and run it now or on a schedule. Workers do the steps one at a time on your own machine, and a broker
hands the one GPU between the orchestrator, the workers and heavy jobs.

The authority for all of this is [`docs/DESIGN.md`](../docs/DESIGN.md); this wiki is the map.

## The idea in five lines

1. **One front.** The console, the chat, the terminal and MCP are generated from the same verbs. MCP is also the
   bypass for an outside agent.
2. **The orchestrator defines; workers do.** The orchestrator fills a flow template in with you and has no tool that
   writes or runs anything. Each step is one headless Hermes run.
3. **A task is signed; a run executes a version.** Definitions are versioned YAML; triggers are manual, now, at a time,
   or cron.
4. **One owner of the machine.** Only the broker loads models. A running step keeps the machine until its boundary;
   park it to take the machine now. Steering is park, then steer, then resume.
5. **Hermes stays stock.** `vendor/hermes` is pinned and never edited.

## Pages

| Start here | How it works | Run it | Reference |
|---|---|---|---|
| [Concepts](Concepts.md) | [Architecture](Architecture.md) | [Operations](Operations.md) | [CLI reference](CLI-Reference.md) |
| [Status and roadmap](Status-and-Roadmap.md) | [Task lifecycle](Task-Lifecycle.md) | [Models and resources](Models-and-Resources.md) | [Flows and skills](Flows-and-Skills.md) |
| [Design decisions](Decisions.md) | [Jobs](Jobs.md) | [Web, browser and logins](Web-and-Browser.md) | [Case studies](Case-Studies.md) |
| | [Parking and KV cache](Parking-and-KV-Cache.md) | | |
