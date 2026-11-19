"""Model servers: the local-only lock applies to the endpoint, not just the provider config."""
import pytest

from ariadne import serving


def test_the_default_server_is_our_own_runtime():
    srv = serving.servers()["llama-server"]
    assert srv["url"].startswith("http://127.0.0.1")


def test_a_public_url_is_refused(monkeypatch):
    monkeypatch.delenv("ARIADNE_ALLOW_HOSTS", raising=False)
    with pytest.raises(serving.ServingError, match="not this machine or the LAN"):
        serving.check_url({"kind": "remote", "url": "https://api.openai.com/v1"})


def test_a_lan_url_is_accepted():
    serving.check_url({"kind": "remote", "url": "http://192.168.1.40:11434"})


def test_an_unknown_kind_is_refused():
    with pytest.raises(serving.ServingError, match="unknown server kind"):
        serving.use("openai")


def test_probe_reads_an_ollama_tag_list(monkeypatch):
    monkeypatch.setattr(serving, "_get_json",
                        lambda url, timeout=5: {"models": [{"name": "qwen3.6:latest"}]}
                        if url.endswith("/api/tags") else (_ for _ in ()).throw(OSError))
    found = serving.probe({"kind": "ollama", "url": "http://127.0.0.1:11434"})
    assert found["kind"] == "ollama" and found["models"] == ["qwen3.6:latest"]


def test_probe_falls_back_to_an_openai_compatible_list(monkeypatch):
    def fake(url, timeout=5):
        if url.endswith("/v1/models"):
            return {"data": [{"id": "qwen3.6-35b-a3b"}]}
        raise OSError("no ollama here")
    monkeypatch.setattr(serving, "_get_json", fake)
    found = serving.probe({"kind": "remote", "url": "http://gpu.lan:8000"})
    assert found["kind"] == "openai-compatible" and found["models"] == ["qwen3.6-35b-a3b"]


def test_probe_says_so_when_nothing_answers(monkeypatch):
    def boom(url, timeout=5):
        raise OSError("refused")
    monkeypatch.setattr(serving, "_get_json", boom)
    with pytest.raises(serving.ServingError, match="nothing answered"):
        serving.probe({"kind": "remote", "url": "http://10.0.0.5:11434"})
