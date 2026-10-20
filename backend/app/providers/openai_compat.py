"""OpenAI 兼容协议实现 — LLM 对话 / 流式生成（httpx 直连，无 SDK 依赖）

- judge 场景：response_format=json_object（供应商不支持时自动省略，由门面 _extract_json 兜底）
- 流式场景：stream_options.include_usage=true 取末包用量；供应商忽略时末尾补全 0 用量
- client 可注入（测试 MockTransport）；None 时惰性自建并复用，aclose() 关闭
"""
import json
import logging
from collections.abc import AsyncIterator

import httpx

from .base import LLMCapabilities, Message, Usage

logger = logging.getLogger("agentic.providers.openai_compat")

_TIMEOUT = 120


class OpenAICompatLLM:
    """LLM 实现：POST {base_url}/chat/completions（流式 / 非流式）"""

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        api_key: str,
        capabilities: LLMCapabilities,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.capabilities = capabilities
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=_TIMEOUT)
        return self._client

    def _auth_headers(self) -> dict:
        """按请求携带鉴权头（不依赖 client 构造方式，注入 client 同样生效）"""
        return {"Authorization": f"Bearer {self._api_key}"}

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _body(
        self,
        messages: list[Message],
        temperature: float,
        json_mode: bool,
        stream: bool,
    ) -> dict:
        body: dict = {"model": self.model, "messages": messages, "temperature": temperature}
        if json_mode and self.capabilities.json_mode:
            body["response_format"] = {"type": "json_object"}
        if stream:
            body["stream"] = True
            if self.capabilities.stream_usage:
                body["stream_options"] = {"include_usage": True}
        return body

    @staticmethod
    def _usage_of(data: dict) -> Usage:
        raw = data.get("usage") or {}
        return Usage(
            prompt_tokens=int(raw.get("prompt_tokens", 0) or 0),
            completion_tokens=int(raw.get("completion_tokens", 0) or 0),
        )

    async def ainvoke(
        self, messages: list[Message], *, temperature: float = 0.2, json_mode: bool = False
    ) -> tuple[str, Usage]:
        client = self._get_client()
        r = await client.post(
            "/chat/completions",
            json=self._body(messages, temperature, json_mode, False),
            headers=self._auth_headers(),
        )
        r.raise_for_status()
        data = r.json()
        text = (data["choices"][0]["message"].get("content") or "") if data.get("choices") else ""
        return text, self._usage_of(data)

    async def astream(
        self, messages: list[Message], *, temperature: float = 0.7
    ) -> AsyncIterator[tuple[str, Usage | None]]:
        client = self._get_client()
        usage_sent = False
        async with client.stream(
            "POST",
            "/chat/completions",
            json=self._body(messages, temperature, False, True),
            headers=self._auth_headers(),
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except json.JSONDecodeError:
                    logger.warning("流式响应解析失败，已跳过该行：%s", payload[:120])
                    continue
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        yield delta, None
                if chunk.get("usage") and not usage_sent:
                    # 只认首个 usage 包（防门面重复累加）；置于 choices 之后，
                    # 保证与文本增量合包发送时（部分网关/代理）增量不被丢弃
                    yield "", self._usage_of(chunk)
                    usage_sent = True
        if not usage_sent:
            # 供应商忽略 stream_options：补全 0 用量，门面据此跳过累加
            yield "", Usage()


class OpenAICompatEmbedder:
    """Embedding 实现：POST {base_url}/embeddings（批 ≤10 / 重试 1 次 / 截断 6000 字符）"""

    _BATCH = 10
    _MAX_CHARS = 6000

    def __init__(
        self,
        name: str,
        model: str,
        dims: int,
        base_url: str,
        api_key: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.dims = dims
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client
        self._owns_client = client is None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=60)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _embed_batch(self, client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
        body: dict = {"model": self.model, "input": texts, "encoding_format": "float"}
        if self.dims > 0:
            body["dimensions"] = self.dims
        r = await client.post(
            "/embeddings",
            json=body,
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in data]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        prepared = [t[: self._MAX_CHARS] if t else " " for t in texts]
        out: list[list[float]] = []
        client = self._get_client()
        for i in range(0, len(prepared), self._BATCH):
            batch = prepared[i : i + self._BATCH]
            for attempt in range(2):
                try:
                    out.extend(await self._embed_batch(client, batch))
                    break
                except Exception as e:
                    if attempt == 1:
                        raise
                    logger.warning("Embedding 批次失败重试：%s", e)
        return out

    async def embed_query(self, text: str) -> list[float]:
        vecs = await self.embed_texts([text])
        return vecs[0]
