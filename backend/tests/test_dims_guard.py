"""dims guard — 索引维度读取 + 启动期一致性检查"""
import httpx
import pytest

from app import startup_check
from app.config import settings
from app.es import Elastic


@pytest.fixture
def es_with_mapping(monkeypatch):
    """用 MockTransport 替换 es.client，返回可控的 ES 实例与安装器"""
    es = Elastic()

    def install(handler):
        monkeypatch.setattr(
            es, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock.es")
        )

    return es, install


def _mapping_response(dims):
    return httpx.Response(200, json={"kb_chunks": {"mappings": {"properties": {
        "embedding": {"type": "dense_vector", "dims": dims}
    }}}})


async def test_index_dims_reads_existing(es_with_mapping):
    es, install = es_with_mapping
    install(lambda r: _mapping_response(1024))
    assert await es.index_dims() == 1024


async def test_index_dims_none_when_index_missing(es_with_mapping):
    es, install = es_with_mapping
    install(lambda r: httpx.Response(404, json={"error": "index_not_found_exception"}))
    assert await es.index_dims() is None


async def test_index_dims_none_on_malformed_mapping(es_with_mapping):
    es, install = es_with_mapping
    install(lambda r: httpx.Response(200, json={"kb_chunks": {"mappings": {"properties": {}}}}))
    assert await es.index_dims() is None


async def test_check_embedding_dims_match(monkeypatch):
    monkeypatch.setattr(startup_check.elastic, "client", httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: _mapping_response(settings.resolved_embed_dims)),
        base_url="http://mock.es",
    ))
    ok, detail = await startup_check.check_embedding_dims()
    assert ok is True
    assert str(settings.resolved_embed_dims) in detail


async def test_check_embedding_dims_conflict(monkeypatch):
    monkeypatch.setattr(startup_check.elastic, "client", httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: _mapping_response(1536)),
        base_url="http://mock.es",
    ))
    ok, detail = await startup_check.check_embedding_dims()
    assert ok is False
    assert "1536" in detail and str(settings.resolved_embed_dims) in detail
    assert "重建" in detail  # 冲突信息必须给重建指引


async def test_check_embedding_dims_index_absent(monkeypatch):
    monkeypatch.setattr(startup_check.elastic, "client", httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(404, json={})),
        base_url="http://mock.es",
    ))
    ok, detail = await startup_check.check_embedding_dims()
    assert ok is True
    assert "创建" in detail
