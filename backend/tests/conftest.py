"""Shared pytest fixtures — a deterministic test environment.

Three hard rules:
1. **Environment independent**: models/dims/keys/providers in backend/.env never take part in
   tests. At session start the `settings` singleton is normalized to "provider catalog defaults
   plus no keys", so the same code produces the same results on any machine with any .env.
2. **No outbound calls**: keys are cleared, so no test can accidentally hit the real
   DeepSeek/DashScope endpoints.
3. **No leakage**: the provider cache and the global i18n catalog are reset after every test.
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

# Normalization table: attribute name -> normalized value ("" / 0 clears it and uses the catalog default)
_NORMALIZE: dict[str, object] = {
    # Providers
    "llm_provider": "deepseek",
    "embed_provider": "qwen",
    "rerank_provider": "qwen",
    # Models / dims: empty -> use the provider catalog default
    "llm_model": "",
    "embed_model": "",
    "embed_dims": 0,
    "rerank_model": "",
    "rerank_base_url": "",
    # base_url: empty -> use the provider catalog default (a stale base_url in .env would point at
    # the wrong provider)
    "llm_base_url": "",
    "embed_base_url": "",
    "deepseek_base_url": "",
    "dashscope_base_url": "",
    # Keys: cleared -> guarantees no real outbound call
    "deepseek_api_key": "",
    "dashscope_api_key": "",
    "openai_api_key": "",
    "moonshot_api_key": "",
    "zhipu_api_key": "",
    "siliconflow_api_key": "",
    # Feature switches: rerank is off by default (each test enables it explicitly)
    "rerank_enabled": False,
}


@pytest.fixture(scope="session", autouse=True)
def _deterministic_settings():
    """Session scope: normalize settings into a deterministic state independent of .env."""
    for name, value in _NORMALIZE.items():
        setattr(settings, name, value)
    # Safety net: drop same-named process environment variables so os.environ cannot override .env again
    for name in _NORMALIZE:
        os.environ.pop(name.upper(), None)
    return None


@pytest.fixture(autouse=True)
def reset_providers():
    """Reset the provider singletons after every test to prevent cross-test pollution."""
    yield
    providers.reset_providers()


@pytest.fixture(autouse=True)
def _restore_i18n_catalog():
    """Restore the global MESSAGES catalog after every test (so keys injected by a test do not leak)."""
    snapshot = dict(MESSAGES)
    yield
    MESSAGES.clear()
    MESSAGES.update(snapshot)


# ---------- Shared test doubles ----------

_MISSING = object()  # sentinel: distinguishes "route not matched" from "matched but value is None"


class FakeDb:
    """Programmable db-layer double: routes return values by SQL keyword and records every call."""

    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.rows: list[dict] = []
        self.one: dict | None = {}
        self._routes: list[tuple[str, object]] = []

    def route(self, keyword: str, value):
        """Route by SQL keyword: a match returns the given value (a dict / list / callable).

        Routes registered later win, so they can override a fixture default.
        """
        self._routes.append((keyword, value))
        return self

    def _match(self, sql):
        """Return (matched, value); when unmatched the value is _MISSING (unlike "matched but None")."""
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
    """Replace the four async db functions with FakeDb; returns the FakeDb instance for assertions."""
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
    """Build an httpx.MockTransport-backed AsyncClient shaped like the ES client."""
    import httpx

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://mock.es")


@pytest.fixture
def api(fake_db):
    """FastAPI TestClient (the db layer is already replaced by fake_db; lifespan is not triggered)."""
    from fastapi.testclient import TestClient

    from app import main

    return TestClient(main.app)
