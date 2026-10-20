"""清理验证测试残留：空「新会话」与验证用知识库"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402

EMPTY_SQL = (
    "SELECT s.id FROM chat_session s "
    "WHERE s.title='新会话' AND NOT EXISTS ("
    "SELECT 1 FROM chat_message m WHERE m.session_id=s.id AND m.role='assistant')"
)
empty = db.query_all(EMPTY_SQL)
for s in empty:
    db.execute("DELETE FROM chat_message WHERE session_id=%s", (s["id"],))
    db.execute("DELETE FROM chat_session WHERE id=%s", (s["id"],))
print("removed empty sessions:", [s["id"] for s in empty])

db.execute("DELETE FROM kb_database WHERE name=%s", ("测试库A",))
print("removed kb 测试库A")
print("sessions:", [r["id"] for r in db.query_all("SELECT id FROM chat_session ORDER BY id")])
print("logs:", db.query_one("SELECT COUNT(*) n FROM agent_decision_log")["n"])
