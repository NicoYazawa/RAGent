# -*- coding: utf-8 -*-
"""端到端验证：带图 ask → SSE 流 → 图片落盘 → 消息 images 字段 → 静态路由"""
import base64
import io
import json
import sys
import urllib.request

sys_deps = __file__.replace("scripts\\sse_check_vision.py", ".deps")
if sys_deps not in sys.path:
    sys.path.insert(0, sys_deps)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

BASE = "http://127.0.0.1:8001"


def make_png_b64() -> str:
    """Pillow 生成含中文问题的图片（复现用户场景：语义在图中，文字仅"回答这个问题"）"""
    img = Image.new("RGB", (420, 120), (246, 248, 252))
    d = ImageDraw.Draw(img)
    font = None
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
        try:
            font = ImageFont.truetype(f"C:\\Windows\\Fonts\\{name}", 26)
            break
        except OSError:
            continue
    d.text((18, 44), "迟到是怎么认定和处罚的？", fill=(20, 30, 50), font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def req(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=150) as resp:
        return resp.read().decode("utf-8")


# 1. 创建会话
sess = json.loads(req("/api/chat/sessions", "POST"))
sid = sess["id"]
print("session:", sid)

# 2. 带图提问（SSE 流）
raw = req(
    f"/api/chat/sessions/{sid}/ask",
    "POST",
    {"question": "回答这个问题", "images": [f"data:image/png;base64,{make_png_b64()}"]},
)

# SSE 块解析：event: 行定类型，紧随 data: 行为 JSON（type 不在 payload 内）
events: list[dict] = []
for block in raw.split("\n\n"):
    etype, data = "", ""
    for line in block.splitlines():
        if line.startswith("event: "):
            etype = line[7:]
        elif line.startswith("data: "):
            data = line[6:]
    if etype and data:
        events.append({"type": etype, **json.loads(data)})

router = next(e for e in events if e["type"] == "router")
rewrite = next((e for e in events if e["type"] == "rewrite"), None)
grades = [(e["score"], e["verdict"]) for e in events if e["type"] == "grade"]
answer_delta = "".join(e["delta"] for e in events if e["type"] == "generate")
done = next(e for e in events if e["type"] == "done")
print("router detail:", router["detail"])
print("rewritten_query:", rewrite["rewritten_query"] if rewrite else "(无)")
print("grades:", grades)
print("answer[:160]:", answer_delta[:160].replace("\n", " "))
print("done message_id:", done["message_id"])

# 3. 消息落库验证
msgs = json.loads(req(f"/api/chat/sessions/{sid}/messages"))
user_msg = next(m for m in msgs if m["role"] == "user")
print("user images persisted:", user_msg.get("images"))

# 4. 静态图片路由
img_url = user_msg["images"][0]
with urllib.request.urlopen(BASE + img_url, timeout=10) as resp:
    print("image route:", resp.status, resp.headers["Content-Type"], len(resp.read()), "bytes")

# 5. 清理测试会话
print("cleanup:", req(f"/api/chat/sessions/{sid}", "DELETE"))
print("ALL PASS" if user_msg.get("images") and done["message_id"] else "CHECK FAILED")
