"""LLM 提示词双语化 — 语言探测 + 提示词 bundle 一致性"""
import re

import pytest

from app.agent import prompts
from app.agent.llm import detect_lang

CJK = re.compile(r"[\u4e00-\u9fff]")


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_router_and_sql_generator_receive_the_same_source_capabilities(locale):
    schema = prompts.BUSINESS_DB_SCHEMAS[locale]
    assert schema in prompts.router_user("question", None, locale=locale)
    assert schema in prompts.get_prompt("nl2sql_sys", locale)


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_disabled_database_is_not_advertised_to_router(locale):
    text = prompts.router_user("question", None, locale=locale, database_enabled=False)
    assert "sales" not in text
    assert prompts.BUSINESS_DB_SCHEMAS[locale] not in text


def test_detect_lang():
    assert detect_lang("迟到是怎么认定和处罚的？") == "zh-CN"
    assert detect_lang("How is lateness handled?") == "en-US"
    assert detect_lang("ES 的向量检索怎么配合 BM25？") == "zh-CN"  # mostly Chinese
    assert detect_lang("What is the RRF fusion k value?") == "en-US"
    assert detect_lang("") == "zh-CN"  # an empty string falls back to the default


def test_prompt_bundles_have_same_keys():
    keys = set(prompts.PROMPTS["zh-CN"].keys())
    assert keys == set(prompts.PROMPTS["en-US"].keys())
    # the required system prompts
    assert {
        "router_sys",
        "planner_sys",
        "grader_sys",
        "crag_sys",
        "reflect_sys",
        "nl2sql_sys",
        "generate_sys",
        "chat_sys",
    } <= keys


def test_en_prompts_have_no_chinese():
    for key, text in prompts.PROMPTS["en-US"].items():
        assert not CJK.search(text), f"en-US 提示词 {key} 仍含中文"


def test_en_user_builders_are_english():
    assert not CJK.search(prompts.router_user("How is lateness handled?", None, locale="en-US"))
    assert not CJK.search(prompts.planner_user("How is lateness handled?", None, locale="en-US"))
    assert not CJK.search(prompts.grader_user("q", ["a"], ["ctx"], locale="en-US"))
    assert not CJK.search(prompts.crag_user("q", "reason", ["ctx"], locale="en-US"))
    assert not CJK.search(prompts.reflect_user("q", "answer", ["ctx"], locale="en-US"))
    assert not CJK.search(prompts.nl2sql_user("q", locale="en-US"))
    assert not CJK.search(prompts.generate_user("q", ["ctx"], None, locale="en-US"))


def test_zh_backward_compat_constants():
    # orchestration and older tests can still use the module-level read-only constants (Chinese)
    assert prompts.ROUTER_SYS == prompts.PROMPTS["zh-CN"]["router_sys"]
    assert prompts.GENERATE_SYS == prompts.PROMPTS["zh-CN"]["generate_sys"]
