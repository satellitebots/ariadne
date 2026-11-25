import json
import threading

from ariadne import browser, park
from ariadne import flows as flowlib
from ariadne.tests.test_core import REPO_FLOWS, env  # noqa: F401 -- env is a fixture


def _browser_args(fl):
    return flowlib.mcp_server_config(fl, REPO_FLOWS)["browser"]["args"]


def test_flows_browse_isolated_until_debug_mode(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr(browser, "STATE", env / "browser.json")
    fl = flowlib.load_flows(REPO_FLOWS)["coding"]
    assert "--isolated" in _browser_args(fl)
    assert browser.main(["debug", "on"]) == 0 and browser.debug_on()
    assert "--autoConnect" in _browser_args(fl)
    browser.main(["debug", "off"])
    assert "--isolated" in _browser_args(fl)


def test_every_flow_can_search_and_hand_off_logins():
    for name, fl in flowlib.load_flows(REPO_FLOWS).items():
        assert "search" in fl.execute_toolsets and "web" in fl.mcp_servers and "jobs" in fl.mcp_servers, name
        assert "browser" in fl.mcp_servers and not fl.real_logins, name


