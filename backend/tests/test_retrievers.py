"""检索适配层 — SQL 只读白名单 / DB 路 / ES 路映射 / 检索源开关

重点覆盖 validate_select：它是 NL2SQL 唯一的安全闸门，
历史上完全没有测试（可以改坏而测试全绿）。
"""
import pytest

from app.agent import retrievers
from app.agent.retrievers import enabled_sources, gather_lanes, validate_select
from app.agent.rrf import RetrieverResult

# ---------- validate_select：白名单 ----------

@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE sales",
        "DELETE FROM sales",
        "UPDATE sales SET product='x'",
        "INSERT INTO sales VALUES (1)",
        "TRUNCATE TABLE sales",
        "ALTER TABLE sales ADD COLUMN x INT",
        "GRANT ALL ON sales TO 'u'",
    ],
)
def test_validate_select_rejects_write_statements(sql):
    """非 SELECT / 写操作一律拒绝"""
    with pytest.raises(ValueError):
        validate_select(sql)


def test_validate_select_rejects_non_select_prefix():
    """必须以 SELECT 开头"""
    with pytest.raises(ValueError, match="仅允许 SELECT"):
        validate_select("SHOW TABLES")


def test_validate_select_rejects_statement_separator():
    """多语句拼接必须拦截 —— 只读账号的防线"""
    with pytest.raises(ValueError):
        validate_select("SELECT * FROM sales; DROP TABLE sales")


def test_validate_select_rejects_comment_injection():
    """注释注入（-- 与 /*）必须拦截"""
    with pytest.raises(ValueError):
        validate_select("SELECT * FROM sales -- x")
    with pytest.raises(ValueError):
        validate_select("SELECT * FROM sales /* x */")


def test_validate_select_allows_common_column_names():
    """常见审计列名不得被关键字黑名单误伤（updated_at / created_at / deleted_at）"""
    sql = "SELECT id, product, created_at, updated_at, deleted_at FROM sales"
    out = validate_select(sql)
    assert out.startswith("SELECT id, product, created_at, updated_at, deleted_at FROM sales")


# ---------- validate_select：LIMIT 截断 ----------

def test_validate_select_appends_limit_when_absent():
    """无 LIMIT 时自动补 LIMIT 20"""
    assert validate_select("SELECT * FROM sales") == "SELECT * FROM sales LIMIT 20"


def test_validate_select_caps_oversized_limit():
    """LIMIT 超过 20 必须被压到 20（防大结果集打爆上下文）"""
    out = validate_select("SELECT * FROM sales LIMIT 100")
    assert out == "SELECT * FROM sales LIMIT 20"
    assert "100" not in out


def test_validate_select_keeps_limit_within_cap():
    """LIMIT 在 20 以内保持原样"""
    out = validate_select("SELECT * FROM sales LIMIT 5")
    assert out == "SELECT * FROM sales LIMIT 5"


def test_validate_select_strips_trailing_semicolon():
    """尾部多余分号先剥离再补 LIMIT"""
    out = validate_select("SELECT * FROM sales;")
    assert out == "SELECT * FROM sales LIMIT 20"


# ---------- DBRetriever（NL2SQL 路） ----------

def _patch_judge(monkeypatch, sql: str):
    async def _judge(schema, system, user, usage=None, attempts=2, images=None):
        return retrievers.SqlOut(sql=sql)

    monkeypatch.setattr(retrievers, "judge", _judge)


async def test_db_retriever_returns_sql_and_results(monkeypatch, fake_db):
    """NL2SQL：生成 SELECT → 执行 → 返回 (sql, results)"""
    _patch_judge(monkeypatch, "SELECT product, quarter FROM sales")
    fake_db.route("FROM sales", [{"id": 1, "product": "A", "quarter": "Q1", "region": "east"}])

    sql, results = await retrievers.db_retriever.search("一季度销售额", top_k=5)

    assert sql.startswith("SELECT product, quarter FROM sales")
    assert sql.endswith("LIMIT 20")
    assert len(results) == 1
    assert results[0].source == "database"
    assert results[0].metadata["db"] is True
    assert results[0].metadata["sql"] == sql
    assert "sales 表查询结果" in results[0].content


async def test_db_retriever_english_content(monkeypatch, fake_db):
    """英文 locale 下 DB 结果文案走英文分支"""
    _patch_judge(monkeypatch, "SELECT product FROM sales")
    fake_db.route("FROM sales", [{"id": 1, "product": "A"}])

    _, results = await retrievers.db_retriever.search("sales", locale="en-US")
    assert "Business database sales table query results" in results[0].content


async def test_db_retriever_caps_rows_at_20(monkeypatch, fake_db):
    """结果行数硬上限 20（SQL 已限 20，结果侧再兜一层）"""
    _patch_judge(monkeypatch, "SELECT id FROM sales")
    fake_db.route("FROM sales", [{"id": i, "product": f"P{i}"} for i in range(25)])

    _, results = await retrievers.db_retriever.search("all")
    assert len(results) == 20


async def test_db_retriever_rejects_non_select(monkeypatch, fake_db):
    """LLM 生成非 SELECT → validate_select 抛错（不得执行）"""
    _patch_judge(monkeypatch, "DROP TABLE sales")
    with pytest.raises(ValueError):
        await retrievers.db_retriever.search("drop it")


# ---------- ES 两路 ----------

async def test_vector_retriever_maps_hits(monkeypatch):
    """向量路：embed → kNN → RetrieverResult 映射"""
    async def _embed(text):
        return [0.1, 0.2]

    async def _knn(vector, kb_ids, k=5):
        assert vector == [0.1, 0.2]
        # ES 层已把 _score 归一为 score（见 app/es.py knn_search）
        return [{"score": 0.8, "doc_name": "考勤制度", "section_path": "第二章",
                 "chunk_no": 3, "content": "迟到认定标准", "doc_id": 7, "kb_id": 2, "chunk_uid": "original-7"}]

    monkeypatch.setattr(retrievers, "embed_query", _embed)
    monkeypatch.setattr(retrievers.elastic, "knn_search", _knn)

    results = await retrievers.vector_retriever.search("迟到", None, 5)
    assert len(results) == 1
    r = results[0]
    assert r.source == "vector"
    assert r.score == 0.8
    assert r.title == "考勤制度 · 第二章"
    assert r.content == "迟到认定标准"
    assert r.metadata["doc_id"] == 7
    assert r.metadata["kb_id"] == 2
    assert r.metadata["chunk_uid"] == "original-7"
    assert r.metadata["chunk_no"] == 3


async def test_keyword_retriever_maps_hits(monkeypatch):
    """关键词路：BM25 → RetrieverResult 映射（无 section_path 时标题只有文档名）"""
    async def _match(query, kb_ids, k=5):
        return [{"score": 0.5, "doc_name": "手册", "section_path": "", "chunk_no": 0,
                 "content": "c", "doc_id": 1}]

    monkeypatch.setattr(retrievers.elastic, "match_search", _match)

    results = await retrievers.keyword_retriever.search("手册", None, 5)
    assert results[0].source == "keyword"
    assert results[0].title == "手册"


async def test_es_hit_defaults_when_fields_missing(monkeypatch):
    """ES hit 缺字段时用默认值（score 0、chunk_no 0、空标题）"""
    async def _match(query, kb_ids, k=5):
        return [{}]

    monkeypatch.setattr(retrievers.elastic, "match_search", _match)
    results = await retrievers.keyword_retriever.search("x", None, 5)
    assert results[0].score == 0.0
    assert results[0].title == ""
    assert results[0].metadata["chunk_no"] == 0


async def test_es_hit_null_score_is_tolerated(monkeypatch):
    """score 为 null 时按 0 处理（畸形 hit 不得让整路检索 500）"""
    async def _match(query, kb_ids, k=5):
        return [{"score": None, "doc_name": "d"}]

    monkeypatch.setattr(retrievers.elastic, "match_search", _match)
    results = await retrievers.keyword_retriever.search("x", None, 5)
    assert results[0].score == 0.0


# ---------- enabled_sources / gather_lanes ----------

async def test_enabled_sources_reads_config_table(fake_db):
    """检索源开关来自 datasource_config 表"""
    fake_db.route("datasource_config", [
        {"source_type": "vector", "enabled": True},
        {"source_type": "keyword", "enabled": False},
    ])
    srcs = await enabled_sources()
    assert srcs == {"vector": True, "keyword": False, "database": True}


async def test_enabled_sources_defaults_true_when_missing(fake_db):
    """配置表里没有该源 → 默认启用（database 缺省为 True）"""
    fake_db.route("datasource_config", [])
    srcs = await enabled_sources()
    assert srcs == {"vector": True, "keyword": True, "database": True}


async def test_gather_lanes_collects_both_sources(monkeypatch):
    """按启用的源并行召回并按 source 分组"""
    async def _vec(query, kb_ids, top_k=5):
        return [RetrieverResult(source="vector", score=1.0, title="v", content="vc")]

    async def _kw(query, kb_ids, top_k=5):
        return [RetrieverResult(source="keyword", score=0.5, title="k", content="kc")]

    monkeypatch.setattr(retrievers.vector_retriever, "search", _vec)
    monkeypatch.setattr(retrievers.keyword_retriever, "search", _kw)

    lanes, errors = await gather_lanes("q", None, 5, ["vector", "keyword"])
    assert errors == {}
    assert lanes["vector"][0].content == "vc"
    assert lanes["keyword"][0].content == "kc"


async def test_gather_lanes_skips_disabled_source(monkeypatch):
    """未启用的源不参与召回"""
    called = {"n": 0}

    async def _vec(query, kb_ids, top_k=5):
        called["n"] += 1
        return []

    async def _kw(query, kb_ids, top_k=5):
        return [RetrieverResult(source="keyword", score=0.5, title="k", content="kc")]

    # 两路都替换为替身：不依赖真实 ES（CI 环境无 ES 时也能跑）
    monkeypatch.setattr(retrievers.vector_retriever, "search", _vec)
    monkeypatch.setattr(retrievers.keyword_retriever, "search", _kw)
    lanes, errors = await gather_lanes("q", None, 5, ["keyword"])
    assert called["n"] == 0
    assert "vector" not in lanes
    assert errors == {}
