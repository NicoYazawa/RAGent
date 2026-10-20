"""rerank 门面与配置 — registry 条目解析 / 缓存 / 容错"""
import pytest

from app import providers
from app.config import Settings, settings
from app.providers.registry import UnknownProviderError


def _clear_overrides(monkeypatch):
    """清空模型/维度/rerank 覆盖字段，使 resolved_* 回退目录默认值"""
    for name in ("llm_model", "embed_model", "embed_dims", "rerank_model", "rerank_base_url"):
        monkeypatch.setattr(settings, name, "" if name != "embed_dims" else 0, raising=False)


# ---------- config ----------

def test_rerank_defaults_preserve_catalog():
    s = Settings(_env_file=None)
    assert s.rerank_enabled is False  # 默认关，灰度开启
    assert s.rerank_provider == "qwen"
    assert s.rerank_top_n == 8
    assert s.rerank_candidates == 20
    assert s.resolved_rerank_model == "gte-rerank-v2"
    assert s.resolved_rerank_base_url == "https://dashscope.aliyuncs.com"


def test_rerank_overrides():
    s = Settings(_env_file=None, rerank_model="qwen3-reranker-0.6b", rerank_base_url="https://gw.example.com",
                 rerank_top_n=5, rerank_candidates=30, rerank_enabled=True)
    assert s.resolved_rerank_model == "qwen3-reranker-0.6b"
    assert s.resolved_rerank_base_url == "https://gw.example.com"
    assert (s.rerank_top_n, s.rerank_candidates, s.rerank_enabled) == (5, 30, True)


# ---------- 门面 ----------

def test_get_rerank_from_qwen_spec(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "rerank_provider", "qwen", raising=False)
    rr = providers.get_rerank()
    assert rr.name == "qwen"
    assert rr.model == "gte-rerank-v2"


def test_get_rerank_siliconflow_flat_shape(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "rerank_provider", "siliconflow", raising=False)
    rr = providers.get_rerank()
    assert rr.name == "siliconflow"
    assert rr.model == "BAAI/bge-reranker-v2-m3"


def test_get_rerank_provider_without_rerank_config_raises(monkeypatch):
    monkeypatch.setattr(settings, "rerank_provider", "deepseek", raising=False)
    with pytest.raises(UnknownProviderError, match="rerank"):
        providers.get_rerank()


def test_get_rerank_cached_singleton(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "rerank_provider", "qwen", raising=False)
    assert providers.get_rerank() is providers.get_rerank()


def test_get_rerank_after_reset_reflects_new_provider(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "rerank_provider", "qwen", raising=False)
    assert providers.get_rerank().name == "qwen"
    providers.reset_providers()
    monkeypatch.setattr(settings, "rerank_provider", "siliconflow", raising=False)
    assert providers.get_rerank().name == "siliconflow"


async def test_close_providers_closes_rerank_too(monkeypatch):
    _clear_overrides(monkeypatch)
    monkeypatch.setattr(settings, "rerank_provider", "qwen", raising=False)
    providers.get_rerank()  # 构建单例
    await providers.close_providers()  # 不得抛异常
    assert providers._rerank_singleton is None
