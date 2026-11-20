"""Ariadne must be runnable next to Hermes: its ports never collide with Hermes's own."""
from ariadne import paths, serving


HERMES_PORTS = {8787, 8791, 8799, 8080, 8090, 9222}


def test_ariadne_uses_its_own_port_block():
    ours = {paths.PORT_MCP, paths.PORT_MODELS, paths.PORT_UI, paths.PORT_BROWSER}
    assert not (ours & HERMES_PORTS), f"Ariadne still uses a Hermes port: {ours & HERMES_PORTS}"


def test_the_ports_are_distinct():
    assert len({paths.PORT_MCP, paths.PORT_MODELS, paths.PORT_UI, paths.PORT_BROWSER}) == 4


def test_the_model_registry_follows_the_model_port():
    assert serving.DEFAULT["url"].endswith(f":{paths.PORT_MODELS}")
