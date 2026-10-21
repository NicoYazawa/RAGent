"""registry 厂商目录 — 查询 / 容错 / 默认值"""
import pytest

from app.providers.registry import UnknownProviderError, get_spec


def test_get_spec_known_providers():
    for name in ("deepseek", "qwen", "openai", "moonshot", "zhipu", "siliconflow", "ollama"):
        spec = get_spec(name)
        assert spec.name == name
        assert spec.kind == "openai_compat"
        assert spec.base_url.startswith("http")


def test_get_spec_case_and_space_insensitive():
    assert get_spec("  DeepSeek ").name == "deepseek"


def test_get_spec_unknown_raises_with_options():
    with pytest.raises(UnknownProviderError) as ei:
        get_spec("gpt4all")
    assert "deepseek" in str(ei.value)  # the error message lists the available options


def test_deepseek_defaults_preserve_current_behavior():
    """Backward compatibility: the deepseek default model must match the pre-refactor config default."""
    spec = get_spec("deepseek")
    assert spec.default_llm_model == "deepseek-v4-flash-vision-exp"
    assert spec.llm_capabilities.vision is True
    assert spec.llm_capabilities.json_mode is True
    assert spec.api_key_env == "DEEPSEEK_API_KEY"


def test_qwen_defaults_preserve_current_embedding_behavior():
    """Backward compatibility: the qwen (Bailian) default embedding must match the pre-refactor value."""
    spec = get_spec("qwen")
    assert spec.default_embed_model == "text-embedding-v4"
    assert spec.default_embed_dims == 1024
    assert spec.api_key_env == "DASHSCOPE_API_KEY"
    assert spec.base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"


def test_ollama_keyless():
    spec = get_spec("ollama")
    assert spec.api_key_env == ""
    assert spec.base_url == "http://localhost:11434/v1"
