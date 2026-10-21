"""后端 i18n 基建 — 语言协商 / 目录取值 / ContextVar"""
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app import i18n
from app.i18n import MESSAGES, resolve_locale, t


def test_resolve_locale_variants():
    assert resolve_locale("zh-CN,zh;q=0.9") == "zh-CN"
    assert resolve_locale("en-US,en;q=0.9") == "en-US"
    assert resolve_locale("zh") == "zh-CN"
    assert resolve_locale("en") == "en-US"
    assert resolve_locale("fr-FR,fr;q=0.9") == "zh-CN"  # an unsupported language falls back to the default
    assert resolve_locale(None) == "zh-CN"
    assert resolve_locale("") == "zh-CN"
    assert resolve_locale("EN-us") == "en-US"  # case insensitive


def test_t_reads_catalog_with_params():
    MESSAGES["test.hello"] = {"zh-CN": "你好 {name}", "en-US": "Hello {name}"}
    assert t("test.hello", "zh-CN", name="世界") == "你好 世界"
    assert t("test.hello", "en-US", name="World") == "Hello World"


def test_t_falls_back_to_zh_when_en_missing():
    MESSAGES["test.only_zh"] = {"zh-CN": "仅中文"}
    assert t("test.only_zh", "en-US") == "仅中文"


def test_t_missing_key_returns_key(caplog):
    assert t("test.absent", "zh-CN") == "test.absent"


def test_middleware_sets_contextvar():
    async def _endpoint(request):
        return JSONResponse({"locale": i18n.current_locale()})

    app = Starlette(routes=[Route("/probe", _endpoint)])
    app.add_middleware(i18n.LocaleMiddleware)
    client = TestClient(app)
    assert client.get("/probe", headers={"Accept-Language": "en"}).json()["locale"] == "en-US"
    assert client.get("/probe").json()["locale"] == "zh-CN"
    assert client.get("/probe", headers={"Accept-Language": "zh"}).json()["locale"] == "zh-CN"
