"""The lock is about inference endpoints and keys, not about the network the model may use."""
import pytest

from ariadne import local_only as lo


def test_a_local_endpoint_and_no_key_passes():
    cfg = {"model": {"provider": "custom", "base_url": "http://127.0.0.1:8090/v1", "default": "qwen"}}
    assert lo.violations(cfg) == []


def test_a_lan_gateway_passes():
    cfg = {"model": {"provider": "custom", "base_url": "http://192.168.1.40:8000/v1"}}
    assert lo.violations(cfg) == []


def test_a_cloud_endpoint_fails_even_with_a_custom_name():
    cfg = {"model": {"provider": "custom", "base_url": "https://api.openai.com/v1"}}
    assert any("not this machine or the LAN" in v for v in lo.violations(cfg))


def test_a_cloud_provider_with_no_base_url_fails():
    cfg = {"model": {"provider": "openrouter", "default": "x"}}
    assert any("cloud endpoint" in v for v in lo.violations(cfg))


def test_an_api_key_fails():
    cfg = {"providers": {"openai": {"base_url": "http://127.0.0.1:1/v1", "api_key": "sk-..."}}}
    assert any("api_key is set" in v for v in lo.violations(cfg))


def test_a_key_env_passes_only_when_unset():
    cfg = {"model": {"provider": "custom", "base_url": "http://127.0.0.1:1/v1", "key_env": "OPENAI_KEY"}}
    assert lo.violations(cfg, environ={}) == []
    assert any("OPENAI_KEY" in v for v in lo.violations(cfg, environ={"OPENAI_KEY": "sk-..."}))


def test_custom_providers_list_is_checked():
    cfg = {"custom_providers": [{"name": "gpu", "base_url": "https://api.anthropic.com"}]}
    assert lo.violations(cfg)


def test_the_guard_reads_the_home_config(tmp_path):
    (tmp_path / "config.yaml").write_text("model:\n  provider: openai\n  api_key: sk-...\n", encoding="utf-8")
    with pytest.raises(lo.LocalOnlyError, match="cloud endpoint"):
        lo.guard_home(tmp_path)


def test_a_public_gateway_needs_the_allowlist(monkeypatch):
    monkeypatch.delenv(lo.ALLOW_ENV, raising=False)
    cfg = {"model": {"base_url": "https://gpu.example.com/v1"}}
    assert lo.violations(cfg), "a public host is not the LAN"
    monkeypatch.setenv(lo.ALLOW_ENV, "gpu.example.com")
    assert lo.violations(cfg) == []
