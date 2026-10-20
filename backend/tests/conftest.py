"""pytest 公共 fixture — 确定性测试环境

三条铁律：
1. **环境无关**：backend/.env 里的模型/维度/密钥/厂商一律不参与测试。
   `settings` 单例在会话开始时被归一到「厂商目录默认值 + 无密钥」，
   于是同一份代码在任何机器、任何 .env 内容下跑出同样的结果。
2. **不外呼**：密钥被清空，杜绝任何测试意外打到真实 DeepSeek/DashScope。
3. **无污染**：每个用例后重置 provider 缓存与全局 i18n 目录。
"""
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import providers
from app.config import settings
from app.i18n import MESSAGES

# 归一化清单：属性名 -> 归一化后的值（"" / 0 表示清空，走厂商目录默认值）
_NORMALIZE: dict[str, object] = {
    # 厂商
    "llm_provider": "deepseek",
    "embed_provider": "qwen",
    "rerank_provider": "qwen",
    # 模型 / 维度：留空 -> 走厂商目录默认值
    "llm_model": "",
    "embed_model": "",
    "embed_dims": 0,
    "rerank_model": "",
    "rerank_base_url": "",
    # base_url：留空 -> 走厂商目录默认值（避免 .env 里的旧 base_url 指向错误厂商）
    "llm_base_url": "",
    "embed_base_url": "",
    "deepseek_base_url": "",
    "dashscope_base_url": "",
    # 密钥：清空 -> 杜绝真实外呼
    "deepseek_api_key": "",
    "dashscope_api_key": "",
    "openai_api_key": "",
    "moonshot_api_key": "",
    "zhipu_api_key": "",
    "siliconflow_api_key": "",
    # 功能开关：精排默认关（各用例显式开启）
    "rerank_enabled": False,
}


@pytest.fixture(scope="session", autouse=True)
def _deterministic_settings():
    """会话级：把 settings 归一到与 .env 无关的确定性状态"""
    for name, value in _NORMALIZE.items():
        setattr(settings, name, value)
    # 兜底：清掉同名进程环境变量，避免 os.environ 再次覆盖 .env
    for name in _NORMALIZE:
        os.environ.pop(name.upper(), None)
    return None


@pytest.fixture(autouse=True)
def reset_providers():
    """每个用例后重置 provider 单例，防止跨用例污染"""
    yield
    providers.reset_providers()


@pytest.fixture(autouse=True)
def _restore_i18n_catalog():
    """每个用例后还原全局 MESSAGES 目录（防止用例注入的临时 key 泄漏出去）"""
    snapshot = dict(MESSAGES)
    yield
    MESSAGES.clear()
    MESSAGES.update(snapshot)


# ---------- 公共替身 ----------

_MISSING = object()  # 哨兵：区分「路由未命中」与「命中但值为 None」


class FakeDb:
    """可编程的 db 层替身：按 SQL 关键词路由返回值，并记录全部调用"""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.rows: list[dict] = []
        self.one: dict | None = {}
        self._routes: list[tuple[str, object]] = []

    def route(self, keyword: str, value):
        """按 SQL 关键词路由：命中则返回指定值（value 可为 dict / list / 可调用对象）

        后注册的路由优先（可覆盖 fixture 默认值）。
        """
        self._routes.append((keyword, value))
        return self

    def _match(self, sql):
        """返回 (是否命中, 值)；未命中时值为 _MISSING（区别于「命中但值为 None」）"""
        for keyword, value in reversed(self._routes):
            if keyword in sql:
                return True, value
        return False, _MISSING

    async def aquery_all(self, sql, params=None):
        self.calls.append((sql, params))
        hit, value = self._match(sql)
        if not hit:
            return list(self.rows)
        return value(params) if callable(value) else value

    async def aquery_one(self, sql, params=None):
        self.calls.append((sql, params))
        hit, value = self._match(sql)
        if not hit:
            return self.one
        return value(params) if callable(value) else value

    async def aexecute(self, sql, params=None):
        self.calls.append((sql, params))
        return 1

    async def aexecute_many(self, sql, seq):
        self.calls.append((sql, seq))
        return len(seq)

    def sqls(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture
def fake_db(monkeypatch):
    """把 app.db 的四个异步函数换成 FakeDb；返回 FakeDb 实例供断言"""
    from app import db

    fake = FakeDb()
    monkeypatch.setattr(db, "aquery_all", fake.aquery_all)
    monkeypatch.setattr(db, "aquery_one", fake.aquery_one)
    monkeypatch.setattr(db, "aexecute", fake.aexecute)
    monkeypatch.setattr(db, "aexecute_many", fake.aexecute_many)
    @asynccontextmanager
    async def lock(kb_id):
        yield

    async def transaction(statements):
        for sql, params in statements:
            await fake.aexecute(sql, params)

    monkeypatch.setattr(db, "kb_write_lock", lock)
    monkeypatch.setattr(db, "aexecute_transaction", transaction)
    return fake


def make_es_mock(handler):
    """构造一个基于 httpx.MockTransport 的 AsyncClient（与 ES 客户端同构）"""
    import httpx

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock.es")


@pytest.fixture
def api(fake_db):
    """FastAPI TestClient（db 层已由 fake_db 替换；不触发 lifespan）"""
    from fastapi.testclient import TestClient

    from app import main

    return TestClient(main.app)
