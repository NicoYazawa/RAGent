"""LLM facade — judge / stream_generate / chat_messages (provider-agnostic, dispatched via providers).

judge uses temperature 0.2 (structured decisions) and generate uses 0.7 (streaming), unchanged
from before the refactor; when a provider lacks json_mode the _extract_json regex is the fallback.
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
    """Detect the language from the CJK character ratio: CJK count >= Latin letter count means
    zh-CN, otherwise en-US (an empty string falls back to zh-CN).

    Used to pick the prompt language — the answer language follows the question, not the UI.
    """
    if not text:
        return "zh-CN"
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    if cjk == 0:
        return "en-US"
    latin = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "zh-CN" if cjk >= latin else "en-US"


def _extract_json(text: str) -> dict:
    """Extract a JSON object from the model output (tolerating a ```json fence and surrounding text)."""
    text = text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"LLM 未返回 JSON：{text[:200]}")
    return json.loads(m.group(0))


def _vision_content(user: str, images: list[str]) -> list[dict]:
    """Multimodal vision content blocks (OpenAI-compatible format, used as the request body)."""
    blocks: list[dict] = [{"type": "text", "text": user}]
    blocks += [{"type": "image_url", "image_url": {"url": u}} for u in images]
    return blocks


def chat_messages(system: str, history: list[dict], user_content: str, images: list[str] | None = None) -> list[dict]:
    """Assemble multi-turn messages (OpenAI-compatible dicts; a non-empty images list turns the
    last user message into multimodal content blocks)."""
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
    """Structured decision: returns a Pydantic instance; the usage dict (may be None) accumulates
    token counts.

    A non-empty images list attaches the images to the last user message (the vision model reads
    them and emits JSON so the Router can extract the key points).
    """
    provider = get_llm()
    msgs = chat_messages(system, [], user, images)
    text, u = await provider.ainvoke(msgs, temperature=0.2, json_mode=True)
    _accumulate(usage, u)
    data = _extract_json(text)
    return schema.model_validate(data)


async def stream_generate(messages: list, usage: dict | None = None) -> AsyncGenerator[str, None]:
    """Streaming generation: yields text deltas; when finished the usage dict is filled in."""
    provider = get_llm()
    async for delta, u in provider.astream(messages, temperature=0.7):
        if u is not None:
            _accumulate(usage, u)
        if delta:
            yield delta
