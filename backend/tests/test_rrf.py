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
    """默认每个切片属于不同文档（doc_name 由 chunk_no 派生），避免被单路去重折叠"""
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
    """去重键必须含 chunk_no：同一文档的不同切片是两个条目"""
    a = _item("vector", 1.0, doc_name="考勤制度", chunk_no=1)
    b = _item("vector", 0.9, doc_name="考勤制度", chunk_no=2)
    assert item_key(a) == "chunk:考勤制度#1"
    assert item_key(b) == "chunk:考勤制度#2"
    assert item_key(a) != item_key(b)


def test_item_key_prefers_url_for_web_results():
    """带 url 的网页结果按 url 建键（同一页面的多片段应合并）"""
    a = _item("web", 1.0, doc_name=None, chunk_no=None, url="https://a.com/x")
    b = _item("web", 0.8, doc_name=None, chunk_no=None, url="https://a.com/x")
    assert item_key(a) == "web:https://a.com/x"
    assert item_key(a) == item_key(b)


def test_item_key_falls_back_to_db_title():
    """既无 url 又无 doc_name/chunk_no → 退化为 db:title"""
    it = _item("database", 1.0, doc_name=None, chunk_no=None, title="Q1 销售额")
    assert item_key(it) == "db:Q1 销售额"


def test_item_key_requires_both_doc_name_and_chunk_no():
    """只有 doc_name（缺 chunk_no）时不得建 chunk 键（否则不同切片会被误合并）"""
    it = _item("vector", 1.0, chunk_no=None, title="T")
    assert item_key(it) == "db:T"


# ---------- dedupe_lane ----------

def test_dedupe_lane_removes_adjacent_same_doc_chunks():
    """同一文档的相邻切片只保留首个（防单文档刷分）"""
    items = [
        _item("vector", 1.0, doc_name="考勤制度", chunk_no=1),
        _item("vector", 0.9, doc_name="考勤制度", chunk_no=2),
        _item("vector", 0.8, doc_name="考勤制度", chunk_no=3),
    ]
    kept = dedupe_lane(items)
    assert len(kept) == 1
    assert kept[0].metadata["chunk_no"] == 1


def test_dedupe_lane_keeps_non_adjacent_same_doc():
    """非相邻出现的同文档切片都保留（只合并连续段）"""
    items = [
        _item("vector", 1.0, doc_name="A", chunk_no=1),
        _item("vector", 0.9, doc_name="B", chunk_no=1),
        _item("vector", 0.8, doc_name="A", chunk_no=2),
    ]
    kept = dedupe_lane(items)
    assert [i.metadata["doc_name"] for i in kept] == ["A", "B", "A"]


def test_dedupe_lane_keeps_items_without_doc_name():
    """无 doc_name 的条目（db/web 路）不参与去重"""
    items = [
        _item("database", 1.0, doc_name=None, chunk_no=None, title="A"),
        _item("database", 0.9, doc_name=None, chunk_no=None, title="B"),
    ]
    assert len(dedupe_lane(items)) == 2


# ---------- rrf_fuse ----------

def test_rrf_fuse_orders_by_rrf_descending():
    """融合结果必须按 rrf 降序：rank 0 的片段排在 rank 1 之前"""
    lanes = {"vector": [
        _item("vector", 0.9, chunk_no=1),
        _item("vector", 0.8, chunk_no=2),
        _item("vector", 0.7, chunk_no=3),
    ]}
    fused = rrf_fuse(lanes, top_n=3)
    assert [f["item"].metadata["chunk_no"] for f in fused] == [1, 2, 3]
    assert fused[0]["rrf"] > fused[1]["rrf"] > fused[2]["rrf"]


def test_rrf_score_decays_with_rank():
    """rrf 分数随 rank 递减（1/(k+rank+1)），不能全部同分"""
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
    """同一条目在多路命中 → rrf 累加，from_lanes 记录来源路"""
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
    """结果数受 top_n 截断"""
    lanes = {"vector": [_item("vector", 1.0 - i * 0.01, chunk_no=i + 1) for i in range(20)]}
    assert len(rrf_fuse(lanes, top_n=8)) == 8
    assert len(rrf_fuse(lanes, top_n=3)) == 3


def test_rrf_fuse_empty_lanes():
    """空检索路 → 空结果，不抛异常"""
    assert rrf_fuse({}, top_n=8) == []
    assert rrf_fuse({"vector": []}, top_n=8) == []


def test_rrf_fuse_dedupes_same_doc_adjacent_chunks():
    """融合前的单路去重会影响最终条目数（同文档相邻切片只留一个）"""
    lanes = {"vector": [
        _item("vector", 0.9, doc_name="考勤制度", chunk_no=1),
        _item("vector", 0.8, doc_name="考勤制度", chunk_no=2),
    ]}
    fused = rrf_fuse(lanes, top_n=8)
    assert len(fused) == 1
    assert fused[0]["item"].metadata["chunk_no"] == 1


def test_rrf_fuse_result_shape():
    """返回结构契约：item / rrf / from_lanes"""
    fused = rrf_fuse({"vector": [_item("vector", 0.9, chunk_no=1)]}, top_n=1)
    assert set(fused[0]) == {"item", "rrf", "from_lanes"}
    assert isinstance(fused[0]["item"], RetrieverResult)
    assert isinstance(fused[0]["from_lanes"], list)
