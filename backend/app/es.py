"""Elasticsearch 客户端 — kb_chunks 索引（dense_vector kNN + BM25 双路检索）

单索引承载全部知识库切片，kb_id 字段隔离多库。
IK 分词插件未安装时自动退回 standard 分词器。
"""
import json
import logging

import httpx

from .config import settings

logger = logging.getLogger("agentic.es")

INDEX = "kb_chunks"
_SOURCE_FIELDS = ["kb_id", "doc_id", "chunk_uid", "doc_name", "section_path", "chunk_no", "content"]


class Elastic:
    def __init__(self) -> None:
        auth = (settings.es_user, settings.es_password) if settings.es_user else None
        # trust_env=False：ES 是内部服务（容器内 es:9200 / 本机 localhost:9200），
        # 不应走系统代理。Windows「系统代理」/ Clash 等会把 localhost 请求也代理出去，
        # 导致 ES 探测与检索全部 502（httpx 默认读取系统代理设置）。
        # 外部 LLM/Embedding 供应商的客户端保持 trust_env 默认值，仍可正常走代理。
        self.client = httpx.AsyncClient(base_url=settings.es_url, auth=auth, timeout=30, trust_env=False)

    async def close(self) -> None:
        await self.client.aclose()

    async def probe_analyzer(self) -> str:
        try:
            r = await self.client.post("/_analyze", json={"analyzer": "ik_max_word", "text": "中文分词测试"})
            if r.status_code == 200:
                return "ik_max_word"
        except httpx.HTTPError:
            pass
        logger.info("IK 插件不可用，content/section_path 退回 standard 分词器")
        return "standard"

    async def ensure_index(self) -> None:
        r = await self.client.head(f"/{INDEX}")
        if r.status_code == 200:
            return
        analyzer = await self.probe_analyzer()
        mapping = {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "kb_id": {"type": "integer"},
                    "doc_id": {"type": "long"},
                    "chunk_uid": {"type": "keyword"},
                    "doc_name": {"type": "keyword", "ignore_above": 256},
                    "section_path": {"type": "text", "analyzer": analyzer},
                    "chunk_no": {"type": "integer"},
                    "content": {"type": "text", "analyzer": analyzer},
                    "embedding": {
                        "type": "dense_vector",
                        "dims": settings.resolved_embed_dims,
                        "similarity": "cosine",
                        "index": True,
                        "index_options": {"type": "hnsw", "m": 16, "ef_construction": 100},
                    },
                    "created_at": {"type": "date"},
                }
            },
        }
        r = await self.client.put(f"/{INDEX}", json=mapping)
        r.raise_for_status()
        logger.info("已创建 ES 索引 %s（analyzer=%s）", INDEX, analyzer)

    async def index_dims(self) -> int | None:
        """读取现有索引的 dense_vector 维度；索引不存在或 mapping 异常返回 None"""
        r = await self.client.get(f"/{INDEX}/_mapping")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        try:
            props = r.json()[INDEX]["mappings"]["properties"]
            return int(props["embedding"]["dims"])
        except (KeyError, TypeError, ValueError):
            logger.warning("ES 索引 %s mapping 中未找到 embedding.dims", INDEX)
            return None

    @staticmethod
    def _kb_filter(kb_ids: list[int] | None) -> dict:
        if kb_ids:
            return {"term": {"kb_id": kb_ids[0]}} if len(kb_ids) == 1 else {"terms": {"kb_id": kb_ids}}
        return {"match_all": {}}

    async def knn_search(self, query_vector: list[float], kb_ids: list[int] | None, k: int = 5) -> list[dict]:
        """语义检索：顶层 knn + kb_id 过滤，_score = (1+cosine)/2"""
        body = {
            "size": k,
            "_source": _SOURCE_FIELDS,
            "knn": {
                "field": "embedding",
                "query_vector": query_vector,
                "k": k,
                "num_candidates": 100,
                # 顶层 query 与 knn 是 OR；库隔离必须在向量候选召回前生效。
                "filter": self._kb_filter(kb_ids),
            },
        }
        r = await self.client.post(f"/{INDEX}/_search", json=body)
        r.raise_for_status()
        hits = r.json().get("hits", {}).get("hits", [])
        return [{"score": h["_score"] or 0.0, **h["_source"]} for h in hits]

    async def match_search(self, query: str, kb_ids: list[int] | None, k: int = 5) -> list[dict]:
        """关键词检索：BM25 match（content 主字段 + section_path 加权）"""
        body = {
            "size": k,
            "_source": _SOURCE_FIELDS,
            "query": {
                "bool": {
                    "must": {
                        "multi_match": {"query": query, "fields": ["content^1", "section_path^2"], "type": "best_fields"}
                    },
                    "filter": self._kb_filter(kb_ids),
                }
            },
        }
        r = await self.client.post(f"/{INDEX}/_search", json=body)
        r.raise_for_status()
        hits = r.json().get("hits", {}).get("hits", [])
        return [{"score": h["_score"] or 0.0, **h["_source"]} for h in hits]

    async def bulk_index(self, docs: list[dict]) -> None:
        lines: list[str] = []
        for d in docs:
            lines.append('{"index": {"_index": "%s", "_id": "%s"}}' % (INDEX, d["chunk_uid"]))
            lines.append(json.dumps(d, ensure_ascii=False))
        body = "\n".join(lines) + "\n"
        r = await self.client.post("/_bulk", content=body.encode("utf-8"), headers={"Content-Type": "application/x-ndjson"})
        r.raise_for_status()
        resp = r.json()
        if resp.get("errors"):
            raise RuntimeError(f"ES bulk 写入存在失败项：{str(resp)[:200]}")

    async def delete_by_doc(self, doc_id: int) -> None:
        """删除文档：先 ES 后 MySQL"""
        r = await self.client.post(
            f"/{INDEX}/_delete_by_query",
            json={"query": {"term": {"doc_id": doc_id}}, "conflicts": "proceed"},
            params={"refresh": "true"},
        )
        r.raise_for_status()

    async def delete_by_kb(self, kb_id: int) -> None:
        # delete_by_query 仅能看到已刷新的切片；bulk 写入后立即删除也必须完整清理。
        refreshed = await self.client.post(f"/{INDEX}/_refresh")
        if refreshed.status_code == 404 and refreshed.json().get('error', {}).get('type') == 'index_not_found_exception':
            return
        refreshed.raise_for_status()
        if refreshed.json().get('_shards', {}).get('failed', 0):
            raise RuntimeError('Knowledge base index refresh incomplete; please retry.')
        r = await self.client.post(
            f"/{INDEX}/_delete_by_query",
            json={"query": {"term": {"kb_id": kb_id}}},
            params={"refresh": "true"},
        )
        if r.status_code == 404 and r.json().get('error', {}).get('type') == 'index_not_found_exception':
            return
        r.raise_for_status()
        result = r.json()
        if result.get('timed_out') or result.get('failures') or result.get('version_conflicts'):
            raise RuntimeError('Knowledge base index cleanup incomplete; please retry.')

    async def count(self) -> int:
        r = await self.client.get(f"/{INDEX}/_count")
        r.raise_for_status()
        return int(r.json().get("count", 0))

    async def ping(self) -> bool:
        try:
            r = await self.client.get("/")
            return r.status_code == 200
        except httpx.HTTPError:
            return False


elastic = Elastic()
