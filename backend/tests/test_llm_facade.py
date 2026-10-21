"""LLM 门面 — JSON 提取容错 / 提示词历史块 / 供应商切换分发"""
import pytest

from app.agent import prompts
from app.agent.llm import _extract_json, chat_messages, detect_lang

# ---------- _extract_json ----------

def test_extract_json_plain_object():
    """Plain JSON."""
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_strips_code_fence():
    """Tolerates a ```json fence."""
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_tolerates_surrounding_text():
    """Tolerates surrounding text."""
    assert _extract_json('好的，结果是：{"a": 1} 希望有帮助') == {"a": 1}


def test_extract_json_raises_when_no_json():
    """No JSON at all -> a clear error (never an empty dict)."""
    with pytest.raises(ValueError, match="未返回 JSON"):
        _extract_json("模型只返回了自然语言")


def test_extract_json_raises_on_invalid_json():
    """JSON-like but invalid -> error."""
    with pytest.raises(ValueError):
        _extract_json("{不是合法 json}")


# ---------- detect_lang edge cases ----------

def test_detect_lang_mixed_text():
    """Mixed Chinese/English: CJK count >= Latin letter count -> zh-CN, otherwise en-US."""
    assert detect_lang("迟到 late 认定") == "zh-CN"   # CJK 4 == Latin 4
    assert detect_lang("late 迟到") == "en-US"       # Latin 4 > CJK 2


def test_detect_lang_pure_ascii():
    """Pure ASCII -> en-US."""
    assert detect_lang("hello world") == "en-US"


# ---------- chat_messages ----------

def test_chat_messages_handles_none_history():
    """history is None -> no crash."""
    msgs = chat_messages("sys", None, "q")
    assert len(msgs) == 2
    assert msgs[1]["content"] == "q"


def test_chat_messages_missing_content_key():
    """A history message without content -> empty string."""
    msgs = chat_messages("sys", [{"role": "user"}], "q")
    assert msgs[1]["content"] == ""


def test_chat_messages_non_assistant_role_is_user():
    """Any non-assistant history role is treated as user."""
    msgs = chat_messages("sys", [{"role": "system", "content": "x"}], "q")
    assert msgs[1]["role"] == "user"


# ---------- Prompt history block ----------

def test_history_block_empty_history():
    """No history -> the placeholder notice (Chinese/English)."""
    assert "无历史" in prompts._history_block([], "zh-CN")
    assert "No conversation history" in prompts._history_block(None, "en-US")


def test_history_block_renders_roles():
    """The history block renders per role and truncates over-long content."""
    out = prompts._history_block(
        [{"role": "user", "content": "问题甲"}, {"role": "assistant", "content": "答案乙"}],
        "zh-CN")
    assert "用户：问题甲" in out
    assert "助手：答案乙" in out


def test_history_block_english_roles():
    """English history block."""
    out = prompts._history_block([{"role": "user", "content": "Q"}], "en-US")
    assert "User: Q" in out


def test_history_block_truncates_long_content():
    """History content is truncated to 120 chars."""
    out = prompts._history_block([{"role": "user", "content": "字" * 500}], "zh-CN")
    assert "字" * 120 in out
    assert "字" * 121 not in out
