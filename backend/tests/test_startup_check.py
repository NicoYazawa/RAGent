"""启动自检 — ES 连通性 / 供应商密钥探测 / 错误体解析

startup_check 是"服务能否正常工作"的第一道闸门，
覆盖率 63%：check_es / check_provider / _err_message 的分支从未被测过。
"""
import httpx
import pytest

from app import startup_check
from app.config import settings


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock.es")


# ---------- check_es ----------

async def test_check_es_ok(monkeypatch):
    """ES returns 200 -> the connection is healthy."""
    monkeypatch.setattr(startup_check.elastic, "client", _mock_client(lambda r: httpx.Response(200)))
    ok, detail = await startup_check.check_es()
    assert ok is True
    assert "连接正常" in detail


async def test_check_es_auth_failure(monkeypatch):
    """401 -> hints to check ES_USER / ES_PASSWORD."""
    monkeypatch.setattr(startup_check.elastic, "client", _mock_client(lambda r: httpx.Response(401)))
    ok, detail = await startup_check.check_es()
    assert ok is False
    assert "401" in detail
    assert "ES_USER" in detail


async def test_check_es_unexpected_status(monkeypatch):
    """Any other status -> abnormal response."""
    monkeypatch.setattr(startup_check.elastic, "client", _mock_client(lambda r: httpx.Response(503)))
    ok, detail = await startup_check.check_es()
    assert ok is False
    assert "503" in detail


async def test_check_es_connection_error(monkeypatch):
    """A connection error -> hints to confirm ES is running."""
    def _boom(req):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(startup_check.elastic, "client", _mock_client(_boom))
    ok, detail = await startup_check.check_es()
    assert ok is False
    assert "连接失败" in detail
    assert "ConnectError" in detail


# ---------- _err_message ----------

def test_err_message_extracts_error_message():
    """Read error.message from an OpenAI-compatible error body."""
    r = httpx.Response(400, json={"error": {"message": "模型不存在"}})
    assert startup_check._err_message(r) == "模型不存在"


def test_err_message_falls_back_to_text():
    """A non-JSON error body -> the truncated raw text."""
    r = httpx.Response(500, text="oops")
    assert startup_check._err_message(r) == "oops"


def test_err_message_handles_missing_error_field():
    """A body without an error field -> fall back to the raw text."""
    r = httpx.Response(500, json={"detail": "x"})
    assert startup_check._err_message(r) == r.text


def test_err_message_truncates_long_message():
    """The error message is truncated to 160 chars."""
    r = httpx.Response(400, json={"error": {"message": "x" * 500}})
    assert len(startup_check._err_message(r)) == 160


# ---------- check_provider ----------

@pytest.fixture
def provider_client(monkeypatch):
    """Replace the httpx client that check_provider builds internally and restore a key (conftest cleared it)."""
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-test", raising=False)
    box = {"handler": lambda r: httpx.Response(200, json={})}
    real_client_cls = httpx.AsyncClient  # grab the reference first so the patched version cannot recurse into itself

    def _factory(*a, **kw):
        return real_client_cls(transport=httpx.MockTransport(box["handler"]),
                               base_url="https://mock.local")

    monkeypatch.setattr(startup_check.httpx, "AsyncClient", _factory)
    return box


async def test_check_provider_llm_ok(provider_client):
    """A valid LLM key -> OK and the model name is shown."""
    provider_client["handler"] = lambda r: httpx.Response(200, json={})
    ok, detail = await startup_check.check_provider("llm")
    assert ok is True
    assert settings.resolved_llm_model in detail


async def test_check_provider_embedding_reports_dims(provider_client):
    """The embedding check result carries the dimension info."""
    provider_client["handler"] = lambda r: httpx.Response(200, json={})
    ok, detail = await startup_check.check_provider("embedding")
    assert ok is True
    assert str(settings.resolved_embed_dims) in detail


async def test_check_provider_missing_api_key(monkeypatch, provider_client):
    """No key configured -> a clear hint (no request is sent)."""
    monkeypatch.setattr(settings, "deepseek_api_key", "", raising=False)
    monkeypatch.setattr(settings, "dashscope_api_key", "", raising=False)
    ok, detail = await startup_check.check_provider("llm")
    assert ok is False
    assert "未配置" in detail
    assert "DEEPSEEK_API_KEY" in detail


@pytest.mark.parametrize("status,hint", [
    (401, "密钥无效"),
    (402, "账户余额不足"),
    (404, "模型不存在"),
    (429, "密钥不可用"),
])
async def test_check_provider_status_hints(provider_client, status, hint):
    """Each status code maps to a different failure reason."""
    provider_client["handler"] = lambda r: httpx.Response(
        status, json={"error": {"message": "detail"}})
    ok, detail = await startup_check.check_provider("llm")
    assert ok is False
    assert hint in detail
    assert str(status) in detail


async def test_check_provider_network_error(provider_client):
    """A network error -> hints to check the network."""
    def _boom(req):
        raise httpx.ConnectError("dns")

    provider_client["handler"] = _boom
    ok, detail = await startup_check.check_provider("llm")
    assert ok is False
    assert "请求失败" in detail


# ---------- run_startup_checks ----------

async def test_run_startup_checks_survives_gather_failure(monkeypatch):
    """An error from asyncio.gather itself still prints a hint (never silent)."""

    def _boom(*coros, **kw):
        for c in coros:
            c.close()
        raise RuntimeError("gather 崩了")

    monkeypatch.setattr(startup_check.asyncio, "gather", _boom)
    captured = {}
    monkeypatch.setattr(startup_check, "_print_block", lambda t: captured.setdefault("text", t))

    await startup_check.run_startup_checks()
    assert "执行异常" in captured["text"]


async def test_run_startup_checks_reports_provider_labels(monkeypatch):
    """The summary carries the provider label and the check names."""
    captured = {}

    async def _ok(*a, **k):
        return True, "ok"

    for name in ("check_es", "check_provider", "check_embedding_dims", "check_es_mysql_consistency"):
        monkeypatch.setattr(startup_check, name, _ok)
    monkeypatch.setattr(startup_check, "_print_block", lambda t: captured.setdefault("text", t))

    await startup_check.run_startup_checks()
    text = captured["text"]
    assert "Elasticsearch" in text
    assert "ES 索引维度一致性" in text
    assert "ES/MySQL 数据一致性" in text
    assert "全部依赖正常" in text


def test_print_block_writes_to_stdout(capsys):
    """_print_block writes to stdout (visible in the startup log)."""
    startup_check._print_block("启动自检输出")
    out = capsys.readouterr().out
    assert "启动自检输出" in out


def test_print_block_tolerates_stdout_without_reconfigure(monkeypatch):
    """stdout does not support reconfigure (e.g. when redirected) -> keep printing, no exception."""
    written = []

    class _NoReconfigure:
        def write(self, s):
            written.append(s)
            return len(s)

        def flush(self):
            pass

    monkeypatch.setattr(startup_check.sys, "stdout", _NoReconfigure())
    startup_check._print_block("降级输出")
    assert any("降级输出" in w for w in written)
