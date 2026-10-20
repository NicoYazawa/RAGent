"""LLM 门面 — JSON 提取容错 / 提示词历史块 / 供应商切换分发"""
import pytest

from app.agent import prompts
from app.agent.llm import _extract_json, chat_messages, detect_lang

# ---------- _extract_json ----------

def test_extract_json_plain_object():
    """标准 JSON"""
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_code_fence():
    """容忍 ```json 围栏"""
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_tolerates_surrounding_text():
    """容忍前后缀文本"""
    assert _extract_json('好的，结果是：{"a": 1} 希望有帮助') == {"a": 1}


def test_extract_json_raises_when_no_json():
    """完全没有 JSON → 明确报错（不返回空 dict）"""
    with pytest.raises(ValueError, match="未返回 JSON"):
        _extract_json("模型只返回了自然语言")


def test_extract_json_raises_on_invalid_json():
    """形似 JSON 但非法 → 报错"""
    with pytest.raises(ValueError):
        _extract_json("{不是合法 json}")


# ---------- detect_lang 边界 ----------

def test_detect_lang_mixed_text():
    """中英混合：CJK 数 ≥ 拉丁字母数 → zh-CN，反之 → en-US"""
    assert detect_lang("迟到 late 认定") == "zh-CN"   # CJK 4 == 拉丁 4
    assert detect_lang("late 迟到") == "en-US"       # 拉丁 4 > CJK 2


def test_detect_lang_pure_ascii():
    """纯 ASCII → en-US"""
    assert detect_lang("hello world") == "en-US"


# ---------- chat_messages ----------

def test_chat_messages_handles_none_history():
    """history 为 None → 不崩"""
    msgs = chat_messages("sys", None, "q")
    assert len(msgs) == 2
    assert msgs[1]["content"] == "q"


def test_chat_messages_missing_content_key():
    """历史消息缺 content → 空串"""
    msgs = chat_messages("sys", [{"role": "user"}], "q")
    assert msgs[1]["content"] == ""


def test_chat_messages_non_assistant_role_is_user():
    """非 assistant 的历史角色一律当 user"""
    msgs = chat_messages("sys", [{"role": "system", "content": "x"}], "q")
    assert msgs[1]["role"] == "user"


# ---------- 提示词历史块 ----------

def test_history_block_empty_history():
    """无历史 → 提示语（中文/英文）"""
    assert "无历史" in prompts._history_block([], "zh-CN")
    assert "No conversation history" in prompts._history_block(None, "en-US")


def test_history_block_renders_roles():
    """历史块按角色渲染并截断过长内容"""
    out = prompts._history_block(
        [{"role": "user", "content": "问题甲"}, {"role": "assistant", "content": "答案乙"}],
        "zh-CN")
    assert "用户：问题甲" in out
    assert "助手：答案乙" in out


def test_history_block_english_roles():
    """英文历史块"""
    out = prompts._history_block([{"role": "user", "content": "Q"}], "en-US")
    assert "User: Q" in out


def test_history_block_truncates_long_content():
    """历史内容截断到 120 字符"""
    out = prompts._history_block([{"role": "user", "content": "字" * 500}], "zh-CN")
    assert "字" * 120 in out
    assert "字" * 121 not in out
