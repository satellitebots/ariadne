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
5. **Hermes stays stock.** Everything Ariadne adds is configuration, plugins, MCP servers and skills on top of a
   pinned Hermes. `upstream/` is never edited.

## Pages

| Start here | How it works | Run it | Reference |
|---|---|---|---|
| [Concepts](Concepts.md) | [Architecture](Architecture.md) | [Operations](Operations.md) | [CLI reference](CLI-Reference.md) |
| [Status and roadmap](Status-and-Roadmap.md) | [Task lifecycle](Task-Lifecycle.md) | [Models and resources](Models-and-Resources.md) | [Flows and skills](Flows-and-Skills.md) |
| [Design decisions](Decisions.md) | [Jobs](Jobs.md) | [Desktop](Desktop.md) | [Case studies](Case-Studies.md) |
| | [Parking and KV cache](Parking-and-KV-Cache.md) | | |
| | [Web, browser and logins](Web-and-Browser.md) | | |

## Status

The coding flow is in beta. The design, writing and content flows have shipped but are not yet validated end to
end. For what is running, what is stalled and what comes next, see [Status and roadmap](Status-and-Roadmap.md).
