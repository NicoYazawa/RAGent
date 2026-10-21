# -*- coding: utf-8 -*-
"""End-to-end check: image ask -> SSE stream -> image stored on disk -> message images field
-> static route."""
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
    """Build an image with a Chinese question via Pillow (reproducing the user scenario where the
    semantics live in the image and the text is only "回答这个问题")."""
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


# 1. Create a session
sess = json.loads(req("/api/chat/sessions", "POST"))
sid = sess["id"]
print("session:", sid)

# 2. Ask with an image (SSE stream)
raw = req(
    f"/api/chat/sessions/{sid}/ask",
    "POST",
    {"question": "回答这个问题", "images": [f"data:image/png;base64,{make_png_b64()}"]},
)

# Parse SSE blocks: the event: line sets the type and the following data: line is JSON
# (type is not part of the payload)
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

# 3. Verify the persisted message
msgs = json.loads(req(f"/api/chat/sessions/{sid}/messages"))
user_msg = next(m for m in msgs if m["role"] == "user")
print("user images persisted:", user_msg.get("images"))

# 4. Static image route
img_url = user_msg["images"][0]
with urllib.request.urlopen(BASE + img_url, timeout=10) as resp:
    print("image route:", resp.status, resp.headers["Content-Type"], len(resp.read()), "bytes")

# 5. Clean up the test session
print("cleanup:", req(f"/api/chat/sessions/{sid}", "DELETE"))
print("ALL PASS" if user_msg.get("images") and done["message_id"] else "CHECK FAILED")
