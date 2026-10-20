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
    """ES 返回 200 → 连接正常"""
    monkeypatch.setattr(startup_check.elastic, "client", _mock_client(lambda r: httpx.Response(200)))
    ok, detail = await startup_check.check_es()
    assert ok is True
    assert "连接正常" in detail


async def test_check_es_auth_failure(monkeypatch):
    """401 → 提示检查 ES_USER / ES_PASSWORD"""
    monkeypatch.setattr(startup_check.elastic, "client", _mock_client(lambda r: httpx.Response(401)))
    ok, detail = await startup_check.check_es()
    assert ok is False
    assert "401" in detail
    assert "ES_USER" in detail


async def test_check_es_unexpected_status(monkeypatch):
    """其他状态码 → 响应异常"""
    monkeypatch.setattr(startup_check.elastic, "client", _mock_client(lambda r: httpx.Response(503)))
    ok, detail = await startup_check.check_es()
    assert ok is False
    assert "503" in detail


async def test_check_es_connection_error(monkeypatch):
    """连接异常 → 提示确认 ES 已启动"""
    def _boom(req):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(startup_check.elastic, "client", _mock_client(_boom))
    ok, detail = await startup_check.check_es()
    assert ok is False
    assert "连接失败" in detail
    assert "ConnectError" in detail


# ---------- _err_message ----------

def test_err_message_extracts_error_message():
    """从 OpenAI 兼容错误体里取 error.message"""
    r = httpx.Response(400, json={"error": {"message": "模型不存在"}})
    assert startup_check._err_message(r) == "模型不存在"


def test_err_message_falls_back_to_text():
    """非 JSON 错误体 → 截断的原始文本"""
    r = httpx.Response(500, text="oops")
    assert startup_check._err_message(r) == "oops"


def test_err_message_handles_missing_error_field():
    """错误体无 error 字段 → 回退到原文"""
    r = httpx.Response(500, json={"detail": "x"})
    assert startup_check._err_message(r) == r.text


def test_err_message_truncates_long_message():
    """错误信息截断到 160 字符"""
    r = httpx.Response(400, json={"error": {"message": "x" * 500}})
    assert len(startup_check._err_message(r)) == 160


# ---------- check_provider ----------

@pytest.fixture
def provider_client(monkeypatch):
    """替换 check_provider 内部新建的 httpx 客户端，并补上密钥（conftest 已清空）"""
    monkeypatch.setattr(settings, "deepseek_api_key", "sk-test", raising=False)
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-test", raising=False)
    box = {"handler": lambda r: httpx.Response(200, json={})}
    real_client_cls = httpx.AsyncClient  # 先取引用，避免替换后自调用导致递归

    def _factory(*a, **kw):
        return real_client_cls(transport=httpx.MockTransport(box["handler"]),
                               base_url="https://mock.local")

    monkeypatch.setattr(startup_check.httpx, "AsyncClient", _factory)
    return box


async def test_check_provider_llm_ok(provider_client):
    """LLM 密钥有效 → OK，并显示模型名"""
    provider_client["handler"] = lambda r: httpx.Response(200, json={})
    ok, detail = await startup_check.check_provider("llm")
    assert ok is True
    assert settings.resolved_llm_model in detail


async def test_check_provider_embedding_reports_dims(provider_client):
    """Embedding 检查结果带维度信息"""
    provider_client["handler"] = lambda r: httpx.Response(200, json={})
    ok, detail = await startup_check.check_provider("embedding")
    assert ok is True
    assert str(settings.resolved_embed_dims) in detail


async def test_check_provider_missing_api_key(monkeypatch, provider_client):
    """未配置密钥 → 明确提示（不发请求）"""
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
    """按状态码给出不同的失败原因"""
    provider_client["handler"] = lambda r: httpx.Response(
        status, json={"error": {"message": "detail"}})
    ok, detail = await startup_check.check_provider("llm")
    assert ok is False
    assert hint in detail
    assert str(status) in detail


async def test_check_provider_network_error(provider_client):
    """网络异常 → 提示检查网络"""
    def _boom(req):
        raise httpx.ConnectError("dns")

    provider_client["handler"] = _boom
    ok, detail = await startup_check.check_provider("llm")
    assert ok is False
    assert "请求失败" in detail


# ---------- run_startup_checks ----------

async def test_run_startup_checks_survives_gather_failure(monkeypatch):
    """asyncio.gather 本身抛错时也要打印提示（不静默）"""

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
    """摘要里带厂商标签与检查项名称"""
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
    """_print_block 把内容打到 stdout（启动日志可见）"""
    startup_check._print_block("启动自检输出")
    out = capsys.readouterr().out
    assert "启动自检输出" in out


def test_print_block_tolerates_stdout_without_reconfigure(monkeypatch):
    """stdout 不支持 reconfigure（如被重定向）→ 降级继续输出，不抛异常"""
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
