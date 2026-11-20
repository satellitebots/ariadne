"""Ariadne command line (Windows, Linux, macOS):  ariadne <command>   (or: python -m ariadne <command>)

  (no command)               the inbox: what needs you, what is running, what finished
  "a brief"                  one gesture: this folder, this session, followed live
  doctor                     check every dependency (changes nothing)
  install [--system] [--models]   install what is missing (--system: git/uv/ollama/node via winget, brew or apt;
                             --models: also fetch the default models now instead of when a plan first picks them)
  models [list | install NAME... | install --defaults]   the model catalog (serving/models.yaml)
  kv [list | drop SESSION]   parked KV caches, per session, step and model
  park [--resume | --status]   pause the running task at its next step boundary to have the model (never automatic)
  browser [status | debug on|off]   debug on: the models' browser attaches to your Chrome and its logins
  stop                       stop the background worker and models on purpose (also S in the watch window); they
                             run outside any terminal or session, so nothing else takes them down
  resources [max|shared|light]   how much of the machine the models may take (applied between tasks)
  up [--lan]                 start the models and the MCP endpoint (http://<host>:8791/mcp, bearer token)
  down                       stop them
  connect [--host H]         print client configs (Claude Code, Claude Desktop, other MCP clients)
  submit "text" --flow F --model M   give a task from the terminal (also: --file, --gate, --workspace, --session);
                             then follow it live
  task ...                   the same verbs: submit / wait / approve / revise / cancel / list / get
  inbox                      what needs you, what is running, what finished (no model, works while the GPU is busy)
  show [ID]                  a task as a person reads it: gates, backbrief, report, next action
  follow [ID]                print a task's activity live, then its card when it needs you or finishes
  ok [ID] [--model N=MODEL]  approve the backbrief (default: the task that needs you)
  fix [ID] "feedback"        send it back to planning with what to change
  no [ID]                    cancel it
  gates ID GATE...           answer "what are the check gates?"
  chat [--session NAME]      talk to Hermes in the terminal (ariadne-tasks skill); tasks you give it join this
                             chat's session, or NAME to continue a named one
  sessions                   Ariadne sessions: tasks, segments, last handoff brief
  watch [--open|--always|--never]   live activity: tasks, MCP calls, worker, models, Hermes tool and model calls
                             (--open: in its own window; --always: every run opens it; --never: only on --watch)
  --watch                    with any command: open the activity window too
  ui [--port N] [--bind HOST]    Ariadne's own console in a browser (loopback by default; ARIADNE_BIND for the LAN)
  desktop                        retired: `ariadne ui` is the console (docs/FRONTEND.md)
  serve | profile | flows | token     lower-level pieces

Every command except doctor and install first checks that the dependencies are there.
"""
import os
import subprocess
import sys

from . import deps, paths


def _profile():
    """Copy profiles/ariadne (config + skills) into the terminal's Hermes home, with this machine's paths."""
    import shutil
    from . import yamlio
    src = paths.ROOT / "profiles" / "ariadne"
    home = paths.GATEWAY_HOME
    home.mkdir(parents=True, exist_ok=True)
    cfg = yamlio.safe_load((src / "config.yaml").read_text(encoding="utf-8"))
    cfg["mcp_servers"]["ariadne_tasks"].update(command=str(paths.VENV_PY), env={"PYTHONPATH": str(paths.ROOT)})
    # Ariadne Desktop's package (desktop/plugin): status, park/resume, the chat-and-sessions shell. Hermes copies its
    # desktop half into desktop-plugins/; its routes load only when allow-listed in plugins.enabled.
    # The Hermes desktop plugin is retired (docs/FRONTEND.md): Ariadne serves its own UI. Remove any copy an older
    # profile installed so the shell cannot load it.
    pkg = home / "plugins" / "ariadne"
    if pkg.exists():
        shutil.rmtree(pkg)
    # The gate: this home may submit tasks, not do the work. A refused tool call is enforcement; a skill is advice.
    gate = home / "plugins" / "ariadne_gate"
    if gate.exists():
        shutil.rmtree(gate)
    shutil.copytree(paths.PLUGINS_DIR / "ariadne_gate", gate,
                    ignore=shutil.ignore_patterns("__pycache__", "tests"))
    plugins = cfg.setdefault("plugins", {})
    plugins["enabled"] = sorted((set(plugins.get("enabled") or []) | {"ariadne_gate"}) - {"ariadne"})
    from . import local_only
    bad = local_only.violations(cfg)
    if bad:
        raise SystemExit("refusing to write a cloud provider into the Ariadne home:\n  - " + "\n  - ".join(bad))
    (home / "config.yaml").write_text("# Generated by python -m ariadne profile from profiles/ariadne - do not edit.\n"
                                      + yamlio.safe_dump(cfg), encoding="utf-8")
    for skill in (src / "skills").iterdir():
        dst = home / "skills" / skill.name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(skill, dst)
    print(f"terminal Hermes home: {home}")


def _quick_task(text: str) -> int:
    """One gesture: a brief from this folder, followed live, in this folder's session."""
    from . import console, service
    from .orchestrator import _default_session, _default_workspace, ensure_worker
    workspace = _default_workspace()
    session = _default_session(workspace)
    store = service.store()
    tid = service.submit_unrouted(text, source="cli", workspace=workspace, session=session, store=store)
    ensure_worker()
    print(f"{tid}  session {session}  {workspace}")
    return console.follow(store, tid)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if not argv:
        # `ariadne` with nothing else is the inbox: what needs me, what is running, what finished.
        from . import console
        return console.main(["inbox"])
    if "--watch" in argv:  # any command: also open the activity window
        argv.remove("--watch")
        from . import activity
        activity.open_window()
        if not argv:
            return 0
    known = {"doctor", "install", "profile", "flows", "watch", "resources", "kv", "park", "browser", "casestudy",
             "stop", "models", "inbox", "show", "follow", "ok", "fix", "no", "gates", "serve", "up", "down",
             "connect", "token", "task", "desktop", "sessions", "chat", "local-only", "server", "watchdog", "submit",
             "ui"}
    # `ariadne "fix the failing date test"` - the one gesture the design asks for. Quoted, so the brief is one
    # argument; an unquoted multi-word brief works too.
    if argv and argv[0] not in known and not argv[0].startswith("-") and (len(argv) > 1 or " " in argv[0]):
        return _quick_task(" ".join(argv))
    cmd, rest = argv[0], argv[1:]
    if cmd == "local-only":
        from . import local_only
        bad = local_only.check_home()
        print("local-only: OK (inference is local; no key is configured)" if not bad
              else "local-only: FAIL\n  - " + "\n  - ".join(bad))
        return 1 if bad else 0
    if cmd in ("up", "serve", "chat", "task", "desktop"):
        # Anything that can start a model checks the provider first: local inference and no key, or it does not run.
        from . import local_only
        try:
            local_only.guard_home()
        except local_only.LocalOnlyError as e:
            print(str(e))
            print("Point base_url at this machine or the LAN (ARIADNE_ALLOW_HOSTS for a named gateway), "
                  "and remove the api_key; see docs/DESIGN-RESET.md.")
            return 2
    if cmd not in ("doctor", "install", "watch", "help"):
        from . import activity
        activity.maybe_open_window()  # watch --always: every run shows its activity
    if cmd == "doctor":
        return deps.doctor()
    if cmd == "install":
        return deps.install(system="--system" in rest, slack="--slack" in rest, models="--models" in rest)
    if cmd == "profile":
        return _profile() or 0
    if cmd == "flows":
        from .flows import compile_all
        for name, home in compile_all().items():
            print(f"{name}: {home}")
        return 0
    if cmd == "watch":
        from . import activity
        return activity.main(rest)
    if cmd == "resources":
        from . import resources
        return resources.main(rest)
    if cmd == "kv":
        from . import kvcache
        return kvcache.main(rest)
    if cmd == "park":
        from . import park
        return park.main(rest)
    if cmd == "browser":
        from . import browser
        return browser.main(rest)
    if cmd == "casestudy":
        from . import casestudy
        return casestudy.main(rest)
    if cmd == "stop":
        from .orchestrator import stop_all
        stopped = stop_all()
        print(f"Ariadne stopped: worker, Hermes gateways and models. Tasks back to you: {', '.join(stopped) or 'none'}")
        return 0
    if cmd == "watchdog":
        # One sample of the machine, no model loaded: RAM, VRAM, and whether the server answers.
        from . import watchdog
        return watchdog.main(rest)
    if cmd == "server":
        # Where inference happens: our llama-server, a local Ollama, or an endpoint on the LAN. Model-free.
        from . import serving
        return serving.main(rest)
    if cmd == "ui":
        # Our own console: it reads and signs off without a model, so it runs before the dependency gate. The bind is
        # checked first (loopback or the LAN, never the internet).
        from . import server
        return server.main(rest)
    if cmd == "models":
        from . import models
        return models.main(rest)
    # The model-free control surface: reading state and signing off must work while the models are down or the
    # GPU is busy, so these run before the dependency gate and never call a model.
    if cmd in ("inbox", "show", "follow", "ok", "fix", "no", "gates"):
        from . import console
        return console.main([cmd, *rest])
    deps.require()  # everything below needs the dependencies
    if cmd == "serve":
        from . import serve
        return serve.stop() if "--stop" in rest else serve.start()
    if cmd == "up":
        from . import host, serve
        serve.start()
        return host.main(["serve", "--host", "0.0.0.0" if "--lan" in rest else "127.0.0.1"])
    if cmd == "down":
        from . import serve
        return serve.stop()
    if cmd in ("connect", "token"):
        from . import host
        return host.main([cmd, *rest])
    if cmd in ("task", "submit"):
        from . import orchestrator
        return orchestrator.main([*rest] if cmd == "task" else ["submit", *rest])
    if cmd == "desktop":
        print("Ariadne Desktop (the rebranded Hermes app) is retired: Ariadne serves its own console - docs/FRONTEND.md.")
        print("Run it with:  python -m ariadne ui")
        return 1
    if cmd == "sessions":
        from . import orchestrator
        return orchestrator.main(["sessions"])
    if cmd == "chat":
        # Our own chat: a Hermes session in the chat home, launched with only the task verbs, skills, clarify and
        # read-only search - it can submit a task, not do one (ariadne/chat.py).
        from . import chat
        return chat.main(rest)
    print(f"unknown command '{cmd}'\n{__doc__}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
