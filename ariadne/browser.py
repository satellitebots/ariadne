"""Browser automation and logins.

Models search the web (web_search, web_fetch) and drive a visible Chrome (the browser MCP server) on their own.
By default that Chrome is a fresh, isolated profile with no logins. Models never type passwords, card numbers or
one-time codes. When a step needs a login, the model calls need_login: Ariadne pauses the task at the next step
boundary (the same park as the desktop button) and tells you. You turn on debug mode, which attaches the browser
tools to your own running Chrome (its remote-debugging connection, so your existing sign-ins are there), log in
there yourself, and resume. Debug mode stays on until you turn it off.

  python -m ariadne browser [status]     which Chrome the models use
  python -m ariadne browser debug on     attach to your Chrome (one-time: chrome://inspect/#remote-debugging -> allow;
                                         Chrome asks before each connection)
  python -m ariadne browser debug off    back to each flow's own setting (isolated unless the flow says otherwise)
"""
import json
import sys
import time

from . import paths

STATE = paths.STATE / "browser.json"


def _read():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def debug_on() -> bool:
    return bool(_read().get("debug"))


def set_debug(on: bool):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"debug": bool(on), "changed": time.time()}), encoding="utf-8")


def real_logins(flow) -> bool:
    """Whether this flow's browser attaches to the person's Chrome: debug mode, else the flow's own setting."""
    return True if debug_on() else bool(flow.real_logins)


def login_note(site, why):
    return (f"login needed: {site} ({why}). Turn on debug mode (`python -m ariadne browser debug on`), log in to "
            f"{site} in your own Chrome, then resume (`python -m ariadne park --resume`, R in the watch window, or the "
            "desktop Resume button). Ariadne never types your password.")


def main(argv):
    if argv[:1] == ["debug"] and argv[1:2] in (["on"], ["off"]):
        set_debug(argv[1] == "on")
        print("debug mode on: the browser tools attach to your running Chrome (allow it once at "
              "chrome://inspect/#remote-debugging)" if argv[1] == "on" else
              "debug mode off: each flow uses its own browser setting")
        return 0
    if argv in ([], ["status"]):
        print("debug mode: " + ("on (your Chrome, your logins)" if debug_on() else "off (each flow's own setting)"))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
