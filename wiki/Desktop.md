# Ariadne Desktop

The Hermes desktop app, rebranded and locked to the local runtime. Hermes itself is not changed.

```sh
python -m ariadne desktop --cwd C:\path\to\repo   # first launch builds the app (needs Node.js; a few minutes)
python -m ariadne desktop --build                 # rebuild, e.g. after changing desktop/assets/
python -m ariadne desktop --restart               # fresh backend, after config or plugin changes
```

## What is different from stock Hermes

| Change | How |
|---|---|
| Name, icons, window title "Ariadne" | `desktop/branding.json` + `desktop/assets/`, applied to a throwaway copy of Hermes at the pinned commit. Every edit states how many places it expects to change, so a Hermes update that moves one stops the build and names it. |
| Local only | No setup screen, gateway URL or installer. A broken local runtime is reported, never "fixed" by connecting elsewhere. |
| A focused shell | Only chat and sessions. Capabilities, messaging, artifacts and scheduled jobs are hidden (a desktop plugin, `desktop/plugin`). |
| Status and park | The status bar shows what the local model is doing. A banner above the message box shows the task holding it, with Park / Resume. |
| Own state | `.ariadne/desktop-data`, separate from any stock Hermes install. |

## Use

Ask in the chat: *"Give Ariadne a task: add a --verbose flag to the CLI in this repo. Gates: pytest passes; README
documents the flag."* The assistant submits it, shows you the backbrief, and waits for your approve, revise or
cancel. All the tasks from one desktop conversation share a session.

**Status:** this is the last thing to validate. The changes are in, but it is not part of the current test runs.
