"""决策日志 API — 过滤分页 / 时间区间 / 单条回放"""
import datetime


def test_query_decision_logs_returns_page(api, fake_db):
    """基础分页返回 items / total / page / page_size"""
    fake_db.route("FROM agent_decision_log", [{"id": 1, "question": "迟到怎么认定"}])
    fake_db.route("COUNT(*) AS n FROM agent_decision_log", {"n": 12})

    r = api.get("/api/admin/decision-logs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 12
    assert body["page"] == 1
    assert body["page_size"] == 8
    assert body["items"][0]["question"] == "迟到怎么认定"


def test_query_decision_logs_filters_by_session(api, fake_db):
    """按 session_id 过滤"""
    fake_db.route("SELECT COUNT(*) AS n FROM agent_decision_log", {"n": 1})
    fake_db.route("FROM agent_decision_log", [])
    api.get("/api/admin/decision-logs?session_id=7")
    cond_sql = fake_db.sqls()[0]
    assert "session_id=%s" in cond_sql
    assert fake_db.calls[0][1] == (7,)


def test_query_decision_logs_applies_time_range(api, fake_db):
    """start / end 生成时间区间条件"""
    fake_db.route("SELECT COUNT(*) AS n FROM agent_decision_log", {"n": 0})
    fake_db.route("FROM agent_decision_log", [])
    api.get("/api/admin/decision-logs?start=2026-10-01&end=2026-10-20")
    cond_sql = fake_db.sqls()[0]
    assert "created_at >= %s" in cond_sql
    assert "created_at <= %s" in cond_sql
    params = fake_db.calls[0][1]
    assert params[0] == datetime.datetime(2026, 10, 1, 0, 0, 0)
    assert params[1] == datetime.datetime(2026, 10, 20, 23, 59, 59, 999999)


def test_query_decision_logs_ignores_invalid_date(api, fake_db):
    """非法日期被忽略（不报错、不加条件）"""
    fake_db.route("SELECT COUNT(*) AS n FROM agent_decision_log", {"n": 0})
    fake_db.route("FROM agent_decision_log", [])
    r = api.get("/api/admin/decision-logs?start=not-a-date")
    assert r.status_code == 200
    assert "created_at >= %s" not in fake_db.sqls()[0]


def test_query_decision_logs_ignores_invalid_end_date(api, fake_db):
    """非法 end 日期同样被忽略（不抛异常）"""
    fake_db.route("SELECT COUNT(*) AS n FROM agent_decision_log", {"n": 0})
    fake_db.route("FROM agent_decision_log", [])
    r = api.get("/api/admin/decision-logs?end=2026-13-45")
    assert r.status_code == 200
    assert "created_at <= %s" not in fake_db.sqls()[0]


def test_query_decision_logs_clamps_pagination(api, fake_db):
    """分页参数越界被夹紧"""
    fake_db.route("SELECT COUNT(*) AS n FROM agent_decision_log", {"n": 0})
    fake_db.route("FROM agent_decision_log", [])
    body = api.get("/api/admin/decision-logs?page=0&page_size=999").json()
    assert body["page"] == 1
    assert body["page_size"] == 50


def test_get_decision_log_404(api, fake_db):
    """日志不存在 → 404"""
    fake_db.route("FROM agent_decision_log WHERE id=%s", None)
    r = api.get("/api/admin/decision-logs/99")
    assert r.status_code == 404


def test_get_decision_log_returns_row(api, fake_db):
    """单条日志回放"""
    fake_db.route("FROM agent_decision_log WHERE id=%s", {"id": 5, "steps": [{"step": 1}]})
    r = api.get("/api/admin/decision-logs/5")
    assert r.status_code == 200
    assert r.json()["id"] == 5
