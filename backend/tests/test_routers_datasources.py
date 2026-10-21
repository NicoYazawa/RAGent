"""数据源配置 API — 列表按固定顺序 / 新增与更新 / 未知类型拦截"""
import json


def test_get_datasources_returns_ordered_sources(api, fake_db):
    """The list is returned in the fixed vector / keyword / database order."""
    fake_db.route("FROM datasource_config", [
        {"source_type": "database", "enabled": True, "config": {}, "updated_at": "t3"},
        {"source_type": "vector", "enabled": True, "config": {"k": "v"}, "updated_at": "t1"},
        {"source_type": "keyword", "enabled": False, "config": None, "updated_at": "t2"},
    ])
    r = api.get("/api/admin/datasources")
    assert r.status_code == 200
    body = r.json()
    assert [b["source_type"] for b in body] == ["vector", "keyword", "database"]
    assert body[0]["config"] == {"k": "v"}
    assert body[1]["enabled"] is False
    assert body[1]["config"] == {}  # None is normalized to an empty object


def test_get_datasources_skips_unknown_source(api, fake_db):
    """An unknown source type in the config table never appears in the result."""
    fake_db.route("FROM datasource_config", [
        {"source_type": "web", "enabled": True, "config": {}, "updated_at": "t"},
    ])
    body = api.get("/api/admin/datasources").json()
    assert body == []


def test_update_datasources_rejects_unknown_type(api, fake_db):
    """An unknown source type -> 400."""
    r = api.put("/api/admin/datasources", json={"items": [{"source_type": "web", "enabled": True}]})
    assert r.status_code == 400


def test_update_datasources_inserts_new_source(api, fake_db):
    """A source that does not exist -> INSERT."""
    fake_db.route("SELECT id FROM datasource_config", None)
    r = api.put("/api/admin/datasources", json={
        "items": [{"source_type": "vector", "enabled": True, "config": {"top_k": "5"}}]})
    assert r.status_code == 200
    assert r.json() == {"updated": 1}
    sqls = fake_db.sqls()
    assert any("INSERT INTO datasource_config" in s for s in sqls)
    ins = [c for c in fake_db.calls if "INSERT INTO datasource_config" in c[0]][0]
    assert json.loads(ins[1][2]) == {"top_k": "5"}
    assert ins[1][1] == 1  # enabled → int


def test_update_datasources_updates_existing_source(api, fake_db):
    """An existing source -> UPDATE."""
    fake_db.route("SELECT id FROM datasource_config", {"id": 2})
    r = api.put("/api/admin/datasources", json={
        "items": [{"source_type": "keyword", "enabled": False, "config": {}}]})
    assert r.status_code == 200
    assert any("UPDATE datasource_config" in s for s in fake_db.sqls())
    assert not any("INSERT INTO datasource_config" in s for s in fake_db.sqls())


def test_update_datasources_counts_all_items(api, fake_db):
    """The count is correct for several items."""
    fake_db.route("SELECT id FROM datasource_config", {"id": 1})
    r = api.put("/api/admin/datasources", json={"items": [
        {"source_type": "vector", "enabled": True},
        {"source_type": "keyword", "enabled": True},
    ]})
    assert r.json() == {"updated": 2}


def test_update_datasources_accepts_empty_list(api, fake_db):
    """An empty item list -> updated=0."""
    r = api.put("/api/admin/datasources", json={"items": []})
    assert r.status_code == 200
    assert r.json() == {"updated": 0}
