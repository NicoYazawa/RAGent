"""问答 API — 会话 CRUD / 图片静态服务 / SSE 问答入口

routers/chat.py 历史上覆盖率 44%：SSE 入口的 404/400 分支、
图片静态服务的路径穿越防护都没有测试。
"""


from app.routers import chat
from app.services import chat_images

# ---------- Sessions ----------

def test_create_session_returns_201(api, fake_db):
    """Creating a session -> 201."""
    fake_db.route("INSERT INTO chat_session", 5)
    fake_db.route("SELECT * FROM chat_session", {"id": 5, "title": "新会话"})
    r = api.post("/api/chat/sessions")
    assert r.status_code == 201
    assert r.json()["id"] == 5


def test_list_sessions(api, fake_db):
    """Session list."""
    fake_db.route("FROM chat_session", [{"id": 1}, {"id": 2}])
    r = api.get("/api/chat/sessions")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_get_messages_404_when_session_missing(api, fake_db):
    """Missing session -> 404."""
    fake_db.route("SELECT id FROM chat_session", None)
    r = api.get("/api/chat/sessions/9/messages")
    assert r.status_code == 404


def test_get_messages_returns_history(api, fake_db):
    """Existing session -> returns the message history."""
    fake_db.route("SELECT id FROM chat_session", {"id": 9})
    fake_db.route("FROM chat_message", [{"role": "user", "content": "问"}])
    r = api.get("/api/chat/sessions/9/messages")
    assert r.status_code == 200
    assert r.json()[0]["content"] == "问"


def test_delete_session_404_when_missing(api, fake_db):
    """Missing session -> 404."""
    fake_db.route("SELECT id FROM chat_session", None)
    r = api.delete("/api/chat/sessions/9")
    assert r.status_code == 404


def test_delete_session_success(api, fake_db):
    """Deleting a session -> 200."""
    fake_db.route("SELECT id FROM chat_session", {"id": 9})
    fake_db.route("SELECT images FROM chat_message", [])
    r = api.delete("/api/chat/sessions/9")
    assert r.status_code == 200
    assert r.json() == {"deleted": 9}


def test_purge_last_assistant_returns_removed_flag(api, fake_db):
    """Purging the last assistant message -> returns the removed flag."""
    fake_db.route("role='assistant'", {"id": 3, "decision_log_id": None})
    r = api.delete("/api/chat/sessions/9/last-assistant")
    assert r.status_code == 200
    assert r.json() == {"removed": True}


# ---------- Image static endpoint ----------

def test_get_image_404_for_unsafe_name(api):
    """An illegal image name -> 404 (blocks path traversal)."""
    r = api.get("/api/chat/images/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code == 404


def test_get_image_404_when_missing(api):
    """Missing file -> 404."""
    r = api.get("/api/chat/images/" + "a" * 32 + ".png")
    assert r.status_code == 404


def test_get_image_serves_file(api, tmp_path, monkeypatch):
    """A valid image -> 200 with the correct MIME type."""
    d = tmp_path / "chat_images"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(chat_images, "CHAT_IMAGE_DIR", d)
    monkeypatch.setattr(chat, "chat_images", chat_images)
    name = "b" * 32 + ".png"
    (d / name).write_bytes(b"\x89PNG")

    r = api.get("/api/chat/images/" + name)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")


# ---------- SSE Q&A entry ----------

def test_ask_404_when_session_missing(api, fake_db):
    """Missing session -> 404."""
    fake_db.route("SELECT id FROM chat_session", None)
    r = api.post("/api/chat/sessions/9/ask", json={"question": "迟到怎么认定"})
    assert r.status_code == 404


def test_ask_400_on_invalid_image(api, fake_db, tmp_path, monkeypatch):
    """An invalid image format -> 400."""
    monkeypatch.setattr(chat_images, "CHAT_IMAGE_DIR", tmp_path)
    fake_db.route("SELECT id FROM chat_session", {"id": 9})
    r = api.post("/api/chat/sessions/9/ask", json={
        "question": "迟到怎么认定",
        "images": ["data:image/svg+xml;base64,PHN2Zz4="]})
    assert r.status_code == 400


def test_ask_streams_sse_events(api, fake_db, monkeypatch):
    """The ask entry produces an SSE event stream (event:/data: pairs)."""
    async def _run_ask(session_id, question, kb_ids, skip_user_persist=False,
                       image_urls=None, locale=None):
        yield 'event: done\ndata: {"step": 0, "message_id": 1}\n\n'

    monkeypatch.setattr(chat, "run_ask", _run_ask)
    fake_db.route("SELECT id FROM chat_session", {"id": 9})

    r = api.post("/api/chat/sessions/9/ask", json={"question": "迟到怎么认定"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert "event: done" in r.text


def test_ask_passes_locale_to_run_ask(api, fake_db, monkeypatch):
    """The locale is resolved inside the route handler and passed to run_ask explicitly (the ContextVar
    may already be gone during SSE streaming)."""
    captured = {}

    async def _run_ask(session_id, question, kb_ids, skip_user_persist=False,
                       image_urls=None, locale=None):
        captured["locale"] = locale
        captured["question"] = question
        yield 'event: done\ndata: {}\n\n'

    monkeypatch.setattr(chat, "run_ask", _run_ask)
    fake_db.route("SELECT id FROM chat_session", {"id": 9})

    r = api.post("/api/chat/sessions/9/ask",
                 json={"question": "  迟到怎么认定  "},
                 headers={"Accept-Language": "en-US"})
    assert r.status_code == 200
    assert captured["locale"] == "en-US"
    assert captured["question"] == "迟到怎么认定"  # already stripped


def test_ask_rejects_empty_question(api, fake_db):
    """An empty question -> 422 (AskRequest validation)."""
    r = api.post("/api/chat/sessions/9/ask", json={"question": ""})
    assert r.status_code == 422
