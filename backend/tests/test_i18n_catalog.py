"""i18n 目录完整性 — 语言对齐全 / 文案非空 / 占位符一致

前端 parity.test.ts 已经检查"无空文案"，后端此前只检查 key 集合，
漏翻译（en-US 为空串）会静默通过。本组用例把后端这道闸门补齐。
"""
import re

import pytest

from app import i18n
from app.i18n import DEFAULT_LOCALE, MESSAGES, SUPPORTED, resolve_locale, set_locale, t

PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


def _real_keys():
    """排除用例注入的临时 key"""
    return {k: v for k, v in MESSAGES.items() if not k.startswith("test.")}


# ---------- 目录结构 ----------

def test_catalog_has_entries():
    """目录非空"""
    assert len(_real_keys()) > 50


def test_every_key_has_both_locales():
    """每个 key 必须同时有 zh-CN 与 en-US"""
    missing = [k for k, v in _real_keys().items() if set(v.keys()) != set(SUPPORTED)]
    assert not missing, f"语言不全的 key：{missing}"


def test_no_empty_translations():
    """任何语言的文案都不得为空串或纯空白（漏翻译必须被发现）"""
    empties = [
        f"{k}/{loc}"
        for k, v in _real_keys().items()
        for loc, text in v.items()
        if not (text or "").strip()
    ]
    assert not empties, f"空文案：{empties}"


def test_placeholders_match_between_locales():
    """zh 与 en 的占位符集合必须一致（否则英文渲染会丢参数）"""
    bad = []
    for k, v in _real_keys().items():
        zh = set(PLACEHOLDER_RE.findall(v.get("zh-CN", "")))
        en = set(PLACEHOLDER_RE.findall(v.get("en-US", "")))
        if zh != en:
            bad.append(f"{k}: zh={sorted(zh)} en={sorted(en)}")
    assert not bad, "占位符不一致：\n" + "\n".join(bad)


def test_catalog_keys_are_namespaced():
    """key 必须带命名空间前缀（便于定位与批量维护）"""
    allowed = ("intent.", "sse.", "api.", "error.", "disclaimer.", "cite.")
    bad = [k for k in _real_keys() if not k.startswith(allowed)]
    assert not bad, f"缺少命名空间的 key：{bad}"


# ---------- 语言协商 ----------

@pytest.mark.parametrize("header,expected", [
    ("zh-CN,zh;q=0.9", "zh-CN"),
    ("en-US,en;q=0.9", "en-US"),
    ("zh", "zh-CN"),
    ("en", "en-US"),
    ("fr-FR,fr;q=0.9", DEFAULT_LOCALE),
    ("EN-us", "en-US"),
    ("", DEFAULT_LOCALE),
    (None, DEFAULT_LOCALE),
])
def test_resolve_locale(header, expected):
    """Accept-Language 协商"""
    assert resolve_locale(header) == expected


def test_resolve_locale_skips_empty_parts():
    """空片段被跳过（畸形头不崩）"""
    assert resolve_locale(",,zh-CN,,en") == "zh-CN"


def test_set_locale_rejects_unsupported():
    """非法 locale 回落默认"""
    set_locale("fr-FR")
    assert i18n.current_locale() == DEFAULT_LOCALE
    set_locale("en-US")
    assert i18n.current_locale() == "en-US"
    set_locale(DEFAULT_LOCALE)


# ---------- t() ----------

def test_t_returns_key_when_missing():
    """缺失 key → 返回 key 本身"""
    assert t("definitely.absent.key", "zh-CN") == "definitely.absent.key"


def test_t_falls_back_to_zh_when_en_missing():
    """缺英文 → 回落中文"""
    MESSAGES["test.only_zh"] = {"zh-CN": "仅中文"}
    try:
        assert t("test.only_zh", "en-US") == "仅中文"
    finally:
        MESSAGES.pop("test.only_zh", None)


def test_t_interpolates_params():
    """占位符替换"""
    MESSAGES["test.with_param"] = {"zh-CN": "你好 {name}", "en-US": "Hello {name}"}
    try:
        assert t("test.with_param", "zh-CN", name="世界") == "你好 世界"
        assert t("test.with_param", "en-US", name="World") == "Hello World"
    finally:
        MESSAGES.pop("test.with_param", None)


def test_t_missing_param_does_not_crash():
    """缺参数时不抛异常（返回可读串）"""
    MESSAGES["test.needs_param"] = {"zh-CN": "值 {x}", "en-US": "value {x}"}
    try:
        out = t("test.needs_param", "zh-CN")
        assert isinstance(out, str) and out
    finally:
        MESSAGES.pop("test.needs_param", None)


def test_t_returns_key_when_entry_has_no_text_at_all():
    """条目存在但两种语言都无文案 → 回落为 key（并告警）"""
    MESSAGES["test.no_text"] = {"zh-CN": None, "en-US": None}
    try:
        assert t("test.no_text", "zh-CN") == "test.no_text"
    finally:
        MESSAGES.pop("test.no_text", None)


def test_t_keeps_text_when_format_fails():
    """占位符格式化失败（参数名对不上）→ 保留原文，不抛异常"""
    MESSAGES["test.bad_fmt"] = {"zh-CN": "值 {missing}", "en-US": "v {missing}"}
    try:
        out = t("test.bad_fmt", "zh-CN", other=1)
        assert "missing" in out
    finally:
        MESSAGES.pop("test.bad_fmt", None)
