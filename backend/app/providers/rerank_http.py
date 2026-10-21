"""HTTP rerank implementation — query + candidate documents -> (index, score) pairs sorted by
relevance descending (direct httpx calls).

Two request/response shapes, selected by registry.rerank_shape:
- dashscope: nested input plus parameters.top_n in the request, output.results in the response
  (Alibaba Cloud Bailian's native text-rerank service, outside compatible-mode)
- flat: top-level query/documents/top_n in the request, top-level results in the response
  (the shape used by SiliconFlow / Jina / Cohere)
"""
import logging

import httpx

logger = logging.getLogger("agentic.providers.rerank_http")


class HttpRerank:
    """Rerank implementation: a single POST; the caller controls the candidate count
    (<=50 recommended to stay within provider limits)."""

    def __init__(
        self,
        name: str,
        model: str,
        base_url: str,
        path: str,
        api_key: str,
        shape: str = "dashscope",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._path = path
        self._api_key = api_key
        self._shape = shape
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

    def _body(self, query: str, documents: list[str], top_n: int) -> dict:
        if self._shape == "dashscope":
            return {
                "model": self.model,
                "input": {"query": query, "documents": documents},
                "parameters": {"return_documents": False, "top_n": top_n},
            }
        return {"model": self.model, "query": query, "documents": documents, "top_n": top_n}

    @staticmethod
    def _results_of(data: dict, shape: str) -> list[dict]:
        if shape == "dashscope":
            return (data.get("output") or {}).get("results") or []
        return data.get("results") or []

    async def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        if not documents:
            return []
        client = self._get_client()
        r = await client.post(
            self._path,
            json=self._body(query, documents, top_n),
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        r.raise_for_status()
        out: list[tuple[int, float]] = []
        for item in self._results_of(r.json(), self._shape):
            try:
                idx = int(item.get("index", -1))
                score = float(item.get("relevance_score", 0.0))
            except (TypeError, ValueError):
                logger.warning("rerank 结果条目解析失败，已跳过：%s", item)
                continue
            if idx >= 0:
                out.append((idx, score))
        out.sort(key=lambda x: x[1], reverse=True)
        return out[:top_n]
