"""检索适配层 — SQL 只读白名单 / DB 路 / ES 路映射 / 检索源开关

重点覆盖 validate_select：它是 NL2SQL 唯一的安全闸门，
历史上完全没有测试（可以改坏而测试全绿）。
"""
import pytest

from app.agent import retrievers
from app.agent.retrievers import enabled_sources, gather_lanes, validate_select
from app.agent.rrf import RetrieverResult

# ---------- validate_select: allowlist ----------

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
    """Anything other than SELECT, and every write, is rejected."""
    with pytest.raises(ValueError):
        validate_select(sql)


def test_validate_select_rejects_non_select_prefix():
    """The statement must start with SELECT."""
    with pytest.raises(ValueError, match="仅允许 SELECT"):
        validate_select("SHOW TABLES")


def test_validate_select_rejects_statement_separator():
    """Statement chaining must be blocked — the read-only account's defense."""
    with pytest.raises(ValueError):
        validate_select("SELECT * FROM sales; DROP TABLE sales")


def test_validate_select_rejects_comment_injection():
    """Comment injection (-- and /*) must be blocked."""
    with pytest.raises(ValueError):
        validate_select("SELECT * FROM sales -- x")
    with pytest.raises(ValueError):
        validate_select("SELECT * FROM sales /* x */")


def test_validate_select_allows_common_column_names():
    """Common audit column names must not trip the keyword blacklist (updated_at / created_at / deleted_at)."""
    sql = "SELECT id, product, created_at, updated_at, deleted_at FROM sales"
    out = validate_select(sql)
    assert out.startswith("SELECT id, product, created_at, updated_at, deleted_at FROM sales")


# ---------- validate_select: LIMIT truncation ----------

def test_validate_select_appends_limit_when_absent():
    """No LIMIT -> append LIMIT 20."""
    assert validate_select("SELECT * FROM sales") == "SELECT * FROM sales LIMIT 20"


def test_validate_select_caps_oversized_limit():
    """A LIMIT above 20 is clamped to 20 (a huge result set would blow up the context)."""
    out = validate_select("SELECT * FROM sales LIMIT 100")
    assert out == "SELECT * FROM sales LIMIT 20"
    assert "100" not in out


def test_validate_select_keeps_limit_within_cap():
    """A LIMIT within 20 is left untouched."""
    out = validate_select("SELECT * FROM sales LIMIT 5")
    assert out == "SELECT * FROM sales LIMIT 5"


def test_validate_select_strips_trailing_semicolon():
    """A trailing semicolon is stripped before LIMIT is appended."""
    out = validate_select("SELECT * FROM sales;")
    assert out == "SELECT * FROM sales LIMIT 20"


# ---------- DBRetriever (NL2SQL lane) ----------

def _patch_judge(monkeypatch, sql: str):
    async def _judge(schema, system, user, usage=None, attempts=2, images=None):
        return retrievers.SqlOut(sql=sql)

    monkeypatch.setattr(retrievers, "judge", _judge)


async def test_db_retriever_returns_sql_and_results(monkeypatch, fake_db):
    """NL2SQL: generate a SELECT -> execute -> return (sql, results)."""
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
    """Under the English locale the DB result copy takes the English branch."""
    _patch_judge(monkeypatch, "SELECT product FROM sales")
    fake_db.route("FROM sales", [{"id": 1, "product": "A"}])

    _, results = await retrievers.db_retriever.search("sales", locale="en-US")
    assert "Business database sales table query results" in results[0].content


async def test_db_retriever_caps_rows_at_20(monkeypatch, fake_db):
    """A hard cap of 20 rows (the SQL is already limited; the result side guards again)."""
    _patch_judge(monkeypatch, "SELECT id FROM sales")
    fake_db.route("FROM sales", [{"id": i, "product": f"P{i}"} for i in range(25)])

    _, results = await retrievers.db_retriever.search("all")
    assert len(results) == 20


async def test_db_retriever_rejects_non_select(monkeypatch, fake_db):
    """A non-SELECT from the LLM -> validate_select raises (never executed)."""
    _patch_judge(monkeypatch, "DROP TABLE sales")
    with pytest.raises(ValueError):
        await retrievers.db_retriever.search("drop it")


# ---------- The two ES lanes ----------

async def test_vector_retriever_maps_hits(monkeypatch):
    """Vector lane: embed -> kNN -> RetrieverResult mapping."""
    async def _embed(text):
        return [0.1, 0.2]

    async def _knn(vector, kb_ids, k=5):
        assert vector == [0.1, 0.2]
        # the ES layer already renames _score to score (see knn_search in app/es.py)
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
    """Keyword lane: BM25 -> RetrieverResult mapping (without section_path the title is just the doc name)."""
    async def _match(query, kb_ids, k=5):
        return [{"score": 0.5, "doc_name": "手册", "section_path": "", "chunk_no": 0,
                 "content": "c", "doc_id": 1}]

    monkeypatch.setattr(retrievers.elastic, "match_search", _match)

    results = await retrievers.keyword_retriever.search("手册", None, 5)
    assert results[0].source == "keyword"
    assert results[0].title == "手册"


async def test_es_hit_defaults_when_fields_missing(monkeypatch):
    """A hit missing fields uses defaults (score 0, chunk_no 0, empty title)."""
    async def _match(query, kb_ids, k=5):
        return [{}]

    monkeypatch.setattr(retrievers.elastic, "match_search", _match)
    results = await retrievers.keyword_retriever.search("x", None, 5)
    assert results[0].score == 0.0
    assert results[0].title == ""
    assert results[0].metadata["chunk_no"] == 0


async def test_es_hit_null_score_is_tolerated(monkeypatch):
    """A null score counts as 0 (a malformed hit must not 500 the whole lane)."""
    async def _match(query, kb_ids, k=5):
        return [{"score": None, "doc_name": "d"}]

    monkeypatch.setattr(retrievers.elastic, "match_search", _match)
    results = await retrievers.keyword_retriever.search("x", None, 5)
    assert results[0].score == 0.0


# ---------- enabled_sources / gather_lanes ----------

async def test_enabled_sources_reads_config_table(fake_db):
    """The lane switches come from the datasource_config table."""
    fake_db.route("datasource_config", [
        {"source_type": "vector", "enabled": True},
        {"source_type": "keyword", "enabled": False},
    ])
    srcs = await enabled_sources()
    assert srcs == {"vector": True, "keyword": False, "database": True}


async def test_enabled_sources_defaults_true_when_missing(fake_db):
    """A source absent from the config table is enabled by default (database defaults to True)."""
    fake_db.route("datasource_config", [])
    srcs = await enabled_sources()
    assert srcs == {"vector": True, "keyword": True, "database": True}


async def test_gather_lanes_collects_both_sources(monkeypatch):
    """Recall in parallel across the enabled sources and group the results by source."""
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
    """A disabled source takes no part in retrieval."""
    called = {"n": 0}

    async def _vec(query, kb_ids, top_k=5):
        called["n"] += 1
        return []

    async def _kw(query, kb_ids, top_k=5):
        return [RetrieverResult(source="keyword", score=0.5, title="k", content="kc")]

    # both lanes are doubled: no real ES needed (tests run in CI without ES)
    monkeypatch.setattr(retrievers.vector_retriever, "search", _vec)
    monkeypatch.setattr(retrievers.keyword_retriever, "search", _kw)
    lanes, errors = await gather_lanes("q", None, 5, ["keyword"])
    assert called["n"] == 0
    assert "vector" not in lanes
    assert errors == {}
