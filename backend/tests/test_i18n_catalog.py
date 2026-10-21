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
    """Exclude the temporary keys injected by tests."""
    return {k: v for k, v in MESSAGES.items() if not k.startswith("test.")}


# ---------- Catalog structure ----------

def test_catalog_has_entries():
    """The catalog is not empty."""
    assert len(_real_keys()) > 50


def test_every_key_has_both_locales():
    """Every key must have both zh-CN and en-US."""
    missing = [k for k, v in _real_keys().items() if set(v.keys()) != set(SUPPORTED)]
    assert not missing, f"语言不全的 key：{missing}"


def test_no_empty_translations():
    """No language may be empty or whitespace only (a missing translation must be caught)."""
    empties = [
        f"{k}/{loc}"
        for k, v in _real_keys().items()
        for loc, text in v.items()
        if not (text or "").strip()
    ]
    assert not empties, f"空文案：{empties}"


def test_placeholders_match_between_locales():
    """zh and en must carry the same placeholder set (otherwise English rendering drops parameters)."""
    bad = []
    for k, v in _real_keys().items():
        zh = set(PLACEHOLDER_RE.findall(v.get("zh-CN", "")))
        en = set(PLACEHOLDER_RE.findall(v.get("en-US", "")))
        if zh != en:
            bad.append(f"{k}: zh={sorted(zh)} en={sorted(en)}")
    assert not bad, "占位符不一致：\n" + "\n".join(bad)


def test_catalog_keys_are_namespaced():
    """Keys must carry a namespace prefix (easier to locate and maintain in bulk)."""
    allowed = ("intent.", "sse.", "api.", "error.", "disclaimer.", "cite.")
    bad = [k for k in _real_keys() if not k.startswith(allowed)]
    assert not bad, f"缺少命名空间的 key：{bad}"


# ---------- Locale negotiation ----------

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
    """Accept-Language negotiation."""
    assert resolve_locale(header) == expected


def test_resolve_locale_skips_empty_parts():
    """Empty segments are skipped (a malformed header does not crash)."""
    assert resolve_locale(",,zh-CN,,en") == "zh-CN"


def test_set_locale_rejects_unsupported():
    """An invalid locale falls back to the default."""
    set_locale("fr-FR")
    assert i18n.current_locale() == DEFAULT_LOCALE
    set_locale("en-US")
    assert i18n.current_locale() == "en-US"
    set_locale(DEFAULT_LOCALE)


# ---------- t() ----------

def test_t_returns_key_when_missing():
    """A missing key returns the key itself."""
    assert t("definitely.absent.key", "zh-CN") == "definitely.absent.key"


def test_t_falls_back_to_zh_when_en_missing():
    """Missing English -> fall back to Chinese."""
    MESSAGES["test.only_zh"] = {"zh-CN": "仅中文"}
    try:
        assert t("test.only_zh", "en-US") == "仅中文"
    finally:
        MESSAGES.pop("test.only_zh", None)


def test_t_interpolates_params():
    """Placeholder substitution."""
    MESSAGES["test.with_param"] = {"zh-CN": "你好 {name}", "en-US": "Hello {name}"}
    try:
        assert t("test.with_param", "zh-CN", name="世界") == "你好 世界"
        assert t("test.with_param", "en-US", name="World") == "Hello World"
    finally:
        MESSAGES.pop("test.with_param", None)


def test_t_missing_param_does_not_crash():
    """A missing parameter does not raise (a readable string is returned)."""
    MESSAGES["test.needs_param"] = {"zh-CN": "值 {x}", "en-US": "value {x}"}
    try:
        out = t("test.needs_param", "zh-CN")
        assert isinstance(out, str) and out
    finally:
        MESSAGES.pop("test.needs_param", None)


def test_t_returns_key_when_entry_has_no_text_at_all():
    """The entry exists but neither language has copy -> fall back to the key (and warn)."""
    MESSAGES["test.no_text"] = {"zh-CN": None, "en-US": None}
    try:
        assert t("test.no_text", "zh-CN") == "test.no_text"
    finally:
        MESSAGES.pop("test.no_text", None)


def test_t_keeps_text_when_format_fails():
    """Placeholder formatting fails (parameter names mismatch) -> keep the raw text, no exception."""
    MESSAGES["test.bad_fmt"] = {"zh-CN": "值 {missing}", "en-US": "v {missing}"}
    try:
        out = t("test.bad_fmt", "zh-CN", other=1)
        assert "missing" in out
    finally:
        MESSAGES.pop("test.bad_fmt", None)
