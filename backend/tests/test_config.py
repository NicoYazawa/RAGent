"""config — provider switches / resolved fallbacks / key lookup / backward compatibility."""
import pytest

from app.config import Settings
from app.providers.registry import UnknownProviderError


def test_defaults_preserve_current_behavior():
    s = Settings(_env_file=None)
    assert s.llm_provider == "deepseek"
    assert s.embed_provider == "qwen"
    assert s.resolved_llm_model == "deepseek-v4-flash-vision-exp"
    assert s.resolved_embed_model == "text-embedding-v4"
    assert s.resolved_embed_dims == 1024
    assert s.resolved_llm_base_url == "https://api.deepseek.com"
    assert s.resolved_embed_base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_explicit_overrides_win_over_catalog():
    s = Settings(_env_file=None, llm_model="my-model", embed_model="my-embed", embed_dims=512,
                 deepseek_base_url="https://proxy.example.com", dashscope_base_url="https://dash.example.com")
    assert s.resolved_llm_model == "my-model"
    assert s.resolved_embed_model == "my-embed"
    assert s.resolved_embed_dims == 512
    assert s.resolved_llm_base_url == "https://proxy.example.com"
    assert s.resolved_embed_base_url == "https://dash.example.com"


def test_provider_switch_changes_resolved_values():
    s = Settings(_env_file=None, llm_provider="openai", embed_provider="openai")
    assert s.resolved_llm_model == "gpt-4o-mini"
    assert s.resolved_embed_model == "text-embedding-3-small"
    assert s.resolved_embed_dims == 1536
    assert s.active_llm_spec.name == "openai"


def test_new_base_url_override_beats_legacy():
    s = Settings(_env_file=None, llm_base_url="https://gw.example.com", deepseek_base_url="https://legacy.example.com")
    assert s.resolved_llm_base_url == "https://gw.example.com"


def test_unknown_provider_raises_on_resolve():
    s = Settings(_env_file=None, llm_provider="nope")
    with pytest.raises(UnknownProviderError):
        _ = s.active_llm_spec


def test_api_key_for_prefers_settings_then_environ(monkeypatch):
    s = Settings(_env_file=None, deepseek_api_key="sk-from-settings")
    assert s.api_key_for("DEEPSEEK_API_KEY") == "sk-from-settings"
    s2 = Settings(_env_file=None)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-from-env")
    assert s2.api_key_for("DEEPSEEK_API_KEY") == "sk-from-env"
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert s2.api_key_for("DEEPSEEK_API_KEY") == ""


def test_api_key_for_empty_env_name_returns_empty_string():
    """api_key_for returns an empty string for an unknown or empty env name (the placeholder is
    decided by the caller, providers._key_for)."""
    s = Settings(_env_file=None)
    assert s.api_key_for("") == ""
    assert s.api_key_for("NOT_A_REGISTERED_ENV_NAME") == ""


def test_key_for_ollama_uses_placeholder(monkeypatch):
    """A keyless provider (ollama) takes the _key_for placeholder branch and returns 'not-needed'
    instead of an empty string."""
    from app.config import settings
    from app.providers import _key_for
    from app.providers.registry import get_spec

    assert _key_for(get_spec("ollama")) == "not-needed"
    # For comparison: a provider with a key goes through settings.api_key_for
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-from-settings", raising=False)
    assert _key_for(get_spec("deepseek")) == "sk-from-settings"
