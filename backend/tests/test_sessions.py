"""会话服务 — 会话 CRUD / 历史消息 / 重新生成清理 / 落盘图片回收"""
import json

from app.services import chat_images, sessions

# ---------- create / list / get ----------

async def test_create_session_inserts_and_returns_row(fake_db):
    """Creating a session: INSERT first, then read the whole row back."""
    fake_db.route("INSERT INTO chat_session", 7)
    fake_db.route("SELECT * FROM chat_session", {"id": 7, "title": "新会话"})

    row = await sessions.create_session()
    assert row == {"id": 7, "title": "新会话"}
    assert any("INSERT INTO chat_session" in s for s in fake_db.sqls())


async def test_list_sessions_orders_by_recency(fake_db):
    """The session list is sorted by update time descending."""
    fake_db.route("FROM chat_session", [{"id": 2}, {"id": 1}])
    rows = await sessions.list_sessions()
    assert [r["id"] for r in rows] == [2, 1]
    assert "ORDER BY updated_at DESC" in fake_db.sqls()[0]


async def test_get_messages_selects_conversation_columns(fake_db):
    """Message history selects only the display columns in ascending id order."""
    fake_db.route("FROM chat_message", [{"role": "user", "content": "问"}])
    rows = await sessions.get_messages(3)
    assert rows[0]["role"] == "user"
    sql = fake_db.sqls()[0]
    assert "ORDER BY id ASC" in sql
    assert "session_id" in sql


# ---------- delete_session ----------

async def test_delete_session_removes_messages_and_session(fake_db):
    """Deleting a session: delete the messages first, then the session."""
    fake_db.route("SELECT images FROM chat_message", [])
    await sessions.delete_session(5)
    sqls = fake_db.sqls()
    assert "DELETE FROM chat_message WHERE session_id=%s" in sqls
    assert "DELETE FROM chat_session WHERE id=%s" in sqls


async def test_delete_session_cleans_up_image_files(fake_db, tmp_path, monkeypatch):
    """Deleting a session reclaims the stored images (no orphan files)."""
    d = tmp_path / "chat_images"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(chat_images, "CHAT_IMAGE_DIR", d)
    monkeypatch.setattr(sessions, "CHAT_IMAGE_DIR", d)
    name = "a" * 32 + ".png"
    (d / name).write_bytes(b"\x89PNG")
    fake_db.route("SELECT images FROM chat_message", [
        {"images": json.dumps([chat_images.CHAT_IMAGE_URL_PREFIX + name])}
    ])

    await sessions.delete_session(5)
    assert not (d / name).exists()


async def test_delete_session_tolerates_missing_image_file(fake_db, tmp_path, monkeypatch):
    """An already missing image file raises nothing."""
    d = tmp_path / "chat_images"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(chat_images, "CHAT_IMAGE_DIR", d)
    monkeypatch.setattr(sessions, "CHAT_IMAGE_DIR", d)
    fake_db.route("SELECT images FROM chat_message", [
        {"images": json.dumps([chat_images.CHAT_IMAGE_URL_PREFIX + "b" * 32 + ".png"])}
    ])
    await sessions.delete_session(5)  # must not raise
    assert any("DELETE FROM chat_session" in s for s in fake_db.sqls())


# ---------- purge_last_assistant ----------

async def test_purge_last_assistant_returns_false_when_none(fake_db):
    """No assistant message -> False (nothing is deleted)."""
    fake_db.route("role='assistant'", None)
    assert await sessions.purge_last_assistant(1) is False
    assert not any("DELETE FROM chat_message" in s for s in fake_db.sqls())


async def test_purge_last_assistant_removes_message(fake_db):
    """Removes the last assistant message."""
    fake_db.route("role='assistant'", {"id": 11, "decision_log_id": None})
    assert await sessions.purge_last_assistant(1) is True
    assert "DELETE FROM chat_message WHERE id=%s" in fake_db.sqls()


async def test_purge_last_assistant_also_removes_decision_log(fake_db):
    """The linked decision log is deleted too (regeneration leaves no stale log)."""
    fake_db.route("role='assistant'", {"id": 11, "decision_log_id": 22})
    assert await sessions.purge_last_assistant(1) is True
    sqls = fake_db.sqls()
    assert "DELETE FROM agent_decision_log WHERE id=%s" in sqls
    assert "DELETE FROM chat_message WHERE id=%s" in sqls
