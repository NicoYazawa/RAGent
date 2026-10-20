"""LLM 门面 — judge / stream_generate / chat_messages（供应商无关，经 providers 层分发）

judge 温度 0.2（结构化判定）、generate 温度 0.7（流式生成），与重构前一致；
json_mode 在供应商不支持时由 _extract_json 正则兜底。
"""
import json
import re
from collections.abc import AsyncGenerator
from typing import TypeVar

from pydantic import BaseModel

from ..providers import get_llm
from ..providers.base import Usage

T = TypeVar("T", bound=BaseModel)


def detect_lang(text: str) -> str:
    """按 CJK 字符占比探测语言：CJK 数 ≥ 拉丁字母数 → zh-CN，否则 en-US（空串回落 zh-CN）

    用于选择 LLM 提示词语言 —— 答案语言跟随「提问语言」，不跟随 UI 语言。
    """
    if not text:
        return "zh-CN"
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk == 0:
        return "en-US"
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "zh-CN" if cjk >= latin else "en-US"


def _extract_json(text: str) -> dict:
    """从模型输出提取 JSON 对象（容忍 ```json 围栏与前后缀文本）"""
    text = text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"LLM 未返回 JSON：{text[:200]}")
    return json.loads(m.group(0))


def _vision_content(user: str, images: list[str]) -> list[dict]:
    """视觉多模态 content 块（OpenAI 兼容格式，直接作为请求体）"""
    blocks: list[dict] = [{"type": "text", "text": user}]
    blocks += [{"type": "image_url", "image_url": {"url": u}} for u in images]
    return blocks


def chat_messages(system: str, history: list[dict], user_content: str, images: list[str] | None = None) -> list[dict]:
    """组装多轮对话消息（OpenAI 兼容 dict；images 非空时末条 user 为多模态 content 块）"""
    msgs: list[dict] = [{"role": "system", "content": system}]
    for h in history or []:
        content = h.get("content", "")
        if h.get("images"):
            content = f"{content}（附图 ×{len(h['images'])}）"
        msgs.append({"role": "assistant" if h.get("role") == "assistant" else "user", "content": content})
    if images:
        msgs.append({"role": "user", "content": _vision_content(user_content, images)})
    else:
        msgs.append({"role": "user", "content": user_content})
    return msgs


def _accumulate(usage: dict | None, u: Usage) -> None:
    if usage is not None:
        usage["prompt"] = usage.get("prompt", 0) + u.prompt_tokens
        usage["completion"] = usage.get("completion", 0) + u.completion_tokens


async def judge(
    schema: type[T], system: str, user: str, usage: dict | None = None, images: list[str] | None = None
) -> T:
    """结构化判定：返回 Pydantic 实例；usage 字典（可 None）累计 token 用量

    images 非空时末条 user 消息携带图片（vision 模型读图后输出 JSON，供 Router 提取图中要点）。
    """
    provider = get_llm()
    msgs = chat_messages(system, [], user, images)
    text, u = await provider.ainvoke(msgs, temperature=0.2, json_mode=True)
    _accumulate(usage, u)
    data = _extract_json(text)
    return schema.model_validate(data)


async def stream_generate(messages: list, usage: dict | None = None) -> AsyncGenerator[str, None]:
    """流式生成：逐段 yield 文本增量；完成后 usage 写入字典"""
    provider = get_llm()
    async for delta, u in provider.astream(messages, temperature=0.7):
        if u is not None:
            _accumulate(usage, u)
        if delta:
            yield delta
