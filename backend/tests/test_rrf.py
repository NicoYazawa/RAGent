"""RRF 融合 — 排序方向 / rank 权重 / 跨路累加 / 去重键

rrf_fuse 是检索排序的核心，历史上从未被单测覆盖（仅被执行到）。
本组用例钉死四个曾经「可以改坏而测试全绿」的语义：
  1. 融合结果按 rrf 降序（不能升序）
  2. rrf 分数随 rank 递减（不能全同分）
  3. 同文档相邻切片在单路内去重
  4. 去重键包含 chunk_no（不同切片不能误合并）
"""
from app.agent.rrf import RetrieverResult, dedupe_lane, item_key, rrf_fuse


def test_same_named_documents_are_distinct_within_and_across_lanes():
    first = _item("vector", 0.9, doc_name="manual")
    second = _item("keyword", 0.8, doc_name="manual")
    first.metadata.update(doc_id=10, kb_id=1, chunk_uid="a")
    second.metadata.update(doc_id=20, kb_id=2, chunk_uid="b")
    assert len(dedupe_lane([first, second])) == 2
    fused = rrf_fuse({"vector": [first], "keyword": [second]})
    assert {r["item"].metadata["doc_id"] for r in fused} == {10, 20}


def test_chunk_identity_survives_document_rename():
    first = _item("vector", 0.9, doc_name="before")
    second = _item("keyword", 0.8, doc_name="after")
    for item in [first, second]:
        item.metadata.update(doc_id=10, chunk_uid="stable")
    assert len(rrf_fuse({"vector": [first], "keyword": [second]})) == 1


def test_document_id_disambiguates_without_chunk_uid():
    first = _item("vector", 0.9, doc_name="manual")
    second = _item("keyword", 0.8, doc_name="manual")
    first.metadata["doc_id"] = 10
    second.metadata["doc_id"] = 20
    assert item_key(first) != item_key(second)


def _item(source, score, *, doc_name=None, chunk_no=1, url=None, title="标题", content="内容"):
    """By default each chunk belongs to a different document (doc_name derives from chunk_no) so single-lane
    dedupe does not collapse them."""
    if doc_name is None and chunk_no is not None:
        doc_name = f"文档{chunk_no}"
    meta = {}
    if doc_name is not None:
        meta["doc_name"] = doc_name
    if chunk_no is not None:
        meta["chunk_no"] = chunk_no
    if url is not None:
        meta["url"] = url
    return RetrieverResult(source=source, score=score, title=title, content=content, metadata=meta)


# ---------- item_key ----------

def test_item_key_distinguishes_chunk_no():
    """The dedupe key must include chunk_no: different chunks of one document are two entries."""
    a = _item("vector", 1.0, doc_name="考勤制度", chunk_no=1)
    b = _item("vector", 0.9, doc_name="考勤制度", chunk_no=2)
    assert item_key(a) == "chunk:考勤制度#1"
    assert item_key(b) == "chunk:考勤制度#2"
    assert item_key(a) != item_key(b)


def test_item_key_prefers_url_for_web_results():
    """A web result with a url keys by url (several fragments of one page merge)."""
    a = _item("web", 1.0, doc_name=None, chunk_no=None, url="https://a.com/x")
    b = _item("web", 0.8, doc_name=None, chunk_no=None, url="https://a.com/x")
    assert item_key(a) == "web:https://a.com/x"
    assert item_key(a) == item_key(b)


def test_item_key_falls_back_to_db_title():
    """Neither url nor doc_name/chunk_no -> degrade to db:title."""
    it = _item("database", 1.0, doc_name=None, chunk_no=None, title="Q1 销售额")
    assert item_key(it) == "db:Q1 销售额"


def test_item_key_requires_both_doc_name_and_chunk_no():
    """With only doc_name (no chunk_no) no chunk key is built (otherwise distinct chunks would merge)."""
    it = _item("vector", 1.0, chunk_no=None, title="T")
    assert item_key(it) == "db:T"


# ---------- dedupe_lane ----------

def test_dedupe_lane_removes_adjacent_same_doc_chunks():
    """Only the first of adjacent chunks from one document is kept (one document cannot flood the ranking)."""
    items = [
        _item("vector", 1.0, doc_name="考勤制度", chunk_no=1),
        _item("vector", 0.9, doc_name="考勤制度", chunk_no=2),
        _item("vector", 0.8, doc_name="考勤制度", chunk_no=3),
    ]
    kept = dedupe_lane(items)
    assert len(kept) == 1
    assert kept[0].metadata["chunk_no"] == 1


def test_dedupe_lane_keeps_non_adjacent_same_doc():
    """Non-adjacent chunks of the same document are all kept (only continuous runs merge)."""
    items = [
        _item("vector", 1.0, doc_name="A", chunk_no=1),
        _item("vector", 0.9, doc_name="B", chunk_no=1),
        _item("vector", 0.8, doc_name="A", chunk_no=2),
    ]
    kept = dedupe_lane(items)
    assert [i.metadata["doc_name"] for i in kept] == ["A", "B", "A"]


def test_dedupe_lane_keeps_items_without_doc_name():
    """Entries without doc_name (db/web lanes) take no part in dedupe."""
    items = [
        _item("database", 1.0, doc_name=None, chunk_no=None, title="A"),
        _item("database", 0.9, doc_name=None, chunk_no=None, title="B"),
    ]
    assert len(dedupe_lane(items)) == 2


# ---------- rrf_fuse ----------

def test_rrf_fuse_orders_by_rrf_descending():
    """Fused results must be sorted by rrf descending: the rank-0 chunk comes before rank 1."""
    lanes = {"vector": [
        _item("vector", 0.9, chunk_no=1),
        _item("vector", 0.8, chunk_no=2),
        _item("vector", 0.7, chunk_no=3),
    ]}
    fused = rrf_fuse(lanes, top_n=3)
    assert [f["item"].metadata["chunk_no"] for f in fused] == [1, 2, 3]
    assert fused[0]["rrf"] > fused[1]["rrf"] > fused[2]["rrf"]


def test_rrf_score_decays_with_rank():
    """The rrf score decreases with rank (1/(k+rank+1)) and cannot be identical for all."""
    lanes = {"vector": [
        _item("vector", 0.9, chunk_no=1),
        _item("vector", 0.8, chunk_no=2),
    ]}
    fused = rrf_fuse(lanes, top_n=2)
    assert fused[0]["rrf"] > fused[1]["rrf"]
    # rank0 = 1/61, rank1 = 1/62（k=60）
    assert fused[0]["rrf"] == round(1.0 / 61, 4)
    assert fused[1]["rrf"] == round(1.0 / 62, 4)


def test_rrf_accumulates_score_across_lanes():
    """An item hit by several lanes accumulates rrf and from_lanes records the sources."""
    shared = _item("vector", 0.9, chunk_no=1)
    lanes = {
        "vector": [shared, _item("vector", 0.5, chunk_no=2)],
        "keyword": [shared, _item("keyword", 0.4, chunk_no=3)],
    }
    fused = rrf_fuse(lanes, top_n=5)
    top = fused[0]
    assert top["item"].metadata["chunk_no"] == 1
    assert top["from_lanes"] == ["keyword", "vector"]
    assert top["rrf"] == round(1.0 / 61 + 1.0 / 61, 4)


def test_rrf_fuse_respects_top_n():
    """The result count is truncated to top_n."""
    lanes = {"vector": [_item("vector", 1.0 - i * 0.01, chunk_no=i + 1) for i in range(20)]}
    assert len(rrf_fuse(lanes, top_n=8)) == 8
    assert len(rrf_fuse(lanes, top_n=3)) == 3


def test_rrf_fuse_empty_lanes():
    """Empty lanes -> empty result without raising."""
    assert rrf_fuse({}, top_n=8) == []
    assert rrf_fuse({"vector": []}, top_n=8) == []


def test_rrf_fuse_dedupes_same_doc_adjacent_chunks():
    """Per-lane dedupe before fusion affects the final count (adjacent chunks of one document keep one)."""
    lanes = {"vector": [
        _item("vector", 0.9, doc_name="考勤制度", chunk_no=1),
        _item("vector", 0.8, doc_name="考勤制度", chunk_no=2),
    ]}
    fused = rrf_fuse(lanes, top_n=8)
    assert len(fused) == 1
    assert fused[0]["item"].metadata["chunk_no"] == 1


def test_rrf_fuse_result_shape():
    """Return structure contract: item / rrf / from_lanes."""
    fused = rrf_fuse({"vector": [_item("vector", 0.9, chunk_no=1)]}, top_n=1)
    assert set(fused[0]) == {"item", "rrf", "from_lanes"}
    assert isinstance(fused[0]["item"], RetrieverResult)
    assert isinstance(fused[0]["from_lanes"], list)
