"""检索测试 Playground API — 单路召回 / RRF 融合 / 精排 / Grader 评分"""

from app.agent import orchestrator
from app.agent.rrf import RetrieverResult

# ---------- 单路召回 ----------

async def test_lane_vector_returns_hits(api, monkeypatch):
    """向量路召回：返回 hits 与延迟"""
    from app.agent import retrievers

    async def _search(query, kb_ids, top_k=5):
        return [RetrieverResult(source="vector", score=0.9, title="手册", content="迟到认定",
                                metadata={"doc_name": "手册", "chunk_no": 1, "doc_id": 3})]

    monkeypatch.setattr(retrievers.vector_retriever, "search", _search)
    r = api.post("/api/admin/retrieval-test/lane",
                 json={"query": "迟到", "source": "vector", "top_k": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "vector"
    assert len(body["hits"]) == 1
    assert body["hits"][0]["snippet"] == "迟到认定"
    # doc_id 不外泄到前端
    assert body["hits"][0]["meta"]["doc_id"] == 3
    assert body["latency_ms"] >= 0


async def test_lane_keyword_returns_hits(api, monkeypatch):
    """关键词路召回"""
    from app.agent import retrievers

    async def _search(query, kb_ids, top_k=5):
        return []

    monkeypatch.setattr(retrievers.keyword_retriever, "search", _search)
    r = api.post("/api/admin/retrieval-test/lane",
                 json={"query": "迟到", "source": "keyword"})
    assert r.status_code == 200
    assert r.json()["hits"] == []


async def test_lane_database_degrades_on_error(api, monkeypatch):
    """database 路出错 → 降级为空命中，不阻断其余路"""
    from app.agent import retrievers

    async def _boom(*a, **k):
        raise RuntimeError("SQL 非法")

    monkeypatch.setattr(retrievers.db_retriever, "search", _boom)
    r = api.post("/api/admin/retrieval-test/lane",
                 json={"query": "销售额", "source": "database"})
    assert r.status_code == 200
    assert r.json()["hits"] == []


def test_lane_rejects_unknown_source(api):
    """未知源类型 → 400"""
    r = api.post("/api/admin/retrieval-test/lane", json={"query": "x", "source": "web"})
    assert r.status_code == 400


# ---------- 融合 + 评分 ----------

async def test_fuse_merges_lanes_and_grades(api, monkeypatch):
    """多路融合 + Grader 评分：返回 rrf / from_lanes / grade"""
    async def _grade(question, sub_queries, ctx_blocks, usage, locale=None):
        return 8.5, "pass", "内容相关"

    monkeypatch.setattr(orchestrator, "do_grade", _grade)

    r = api.post("/api/admin/retrieval-test/fuse", json={
        "query": "迟到怎么认定",
        "lanes": [
            {"source": "vector", "hits": [
                {"title": "手册", "snippet": "迟到认定标准", "score": 0.9,
                 "meta": {"doc_name": "手册", "chunk_no": 1}}]},
            {"source": "keyword", "hits": [
                {"title": "制度", "snippet": "处罚标准", "score": 0.7,
                 "meta": {"doc_name": "制度", "chunk_no": 2}}]},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert len(body["fused"]) == 2
    assert body["fused"][0]["from_lanes"] == ["vector"]
    assert body["fused"][0]["rrf"] > 0
    assert body["grade"]["score"] == 8.5
    assert body["grade"]["verdict"] == "pass"


def test_fuse_with_empty_query_uses_default_query(api, monkeypatch):
    """空 query → 用占位查询串（Grader 仍能评估）"""
    seen = {}

    async def _grade(question, sub_queries, ctx_blocks, usage, locale=None):
        seen["q"] = question
        return 0.0, "fail", "无命中"

    monkeypatch.setattr(orchestrator, "do_grade", _grade)
    r = api.post("/api/admin/retrieval-test/fuse", json={"query": "   ", "lanes": []})
    assert r.status_code == 200
    assert seen["q"]


def test_fuse_rerank_failure_is_reported(api, monkeypatch):
    """精排失败 → rerank 字段带 error，其余流程不中断"""
    async def _grade(question, sub_queries, ctx_blocks, usage, locale=None):
        return 5.0, "partial", "部分相关"

    async def _apply(query, items, locale=None):
        return items, None, "精排失败（RuntimeError）"

    monkeypatch.setattr(orchestrator, "do_grade", _grade)
    monkeypatch.setattr(orchestrator, "_apply_rerank", _apply)
    monkeypatch.setattr(orchestrator.settings, "rerank_enabled", True)

    r = api.post("/api/admin/retrieval-test/fuse", json={
        "query": "迟到", "rerank": True,
        "lanes": [{"source": "vector", "hits": [
            {"title": "手册", "snippet": "甲", "score": 0.9,
             "meta": {"doc_name": "手册", "chunk_no": 1}}]}],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["rerank"] == {"error": "精排失败（RuntimeError）"}
    assert body["fused"]  # 粗排结果仍在
