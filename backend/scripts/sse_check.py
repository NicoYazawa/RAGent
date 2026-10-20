"""SSE 问答链路验证脚本 — 依次跑六条演示链路并输出事件摘要

用法：python scripts/sse_check.py [base_url]
输出：backend/sse_check_result.txt
"""
import io
import json
import sys
import time
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = io.StringIO()

CASES = [
    ("chitchat", "你好，简单介绍下你自己"),
    ("kb_qa 正常路径", "ES 的向量检索和关键词检索怎么配合？"),
    ("data_query NL2SQL", "上季度哪个产品卖得最好？"),
    ("summarize 总结", "帮我总结知识库里的信息安全制度要点"),
    ("CRAG 冷门问题", "量子拓扑纠错码的编译原理是什么？"),
    ("Self-RAG 对比类", "对比一下向量检索和关键词检索的区别和适用场景"),
]


def log(s: str = "") -> None:
    OUT.write(s + "\n")


def post_json(path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def ask_stream(sid: int, question: str) -> list[dict]:
    data = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/api/chat/sessions/{sid}/ask",
        data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    events: list[dict] = []
    buf = b""
    with urllib.request.urlopen(req, timeout=200) as r:
        while True:
            chunk = r.read(2048)
            if not chunk:
                break
            buf += chunk
            while b"\n\n" in buf:
                block, buf = buf.split(b"\n\n", 1)
                etype, data_lines = "message", []
                for line in block.decode("utf-8", "replace").split("\n"):
                    if line.startswith("event:"):
                        etype = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].strip())
                if not data_lines:
                    continue
                try:
                    ev = {"type": etype, **json.loads("\n".join(data_lines))}
                except ValueError:
                    continue
                events.append(ev)
    return events


def main() -> None:
    log(f"SSE 链路验证 @ {time.strftime('%Y-%m-%d %H:%M:%S')}  base={BASE}")
    for label, question in CASES:
        sess = post_json("/api/chat/sessions")
        sid = sess["id"]
        log("")
        log("=" * 72)
        log(f"[{label}] session={sid}  Q: {question}")
        log("=" * 72)
        t0 = time.time()
        try:
            events = ask_stream(sid, question)
        except Exception as e:  # noqa: BLE001
            log(f"  !! 异常：{e}")
            continue
        gen_chars = 0
        for ev in events:
            t = ev["type"]
            if t == "generate":
                gen_chars += len(ev.get("delta", ""))
                continue
            extras = []
            for key in ("intent", "confidence", "hit_count", "score", "verdict", "action", "round", "result", "message_id", "elapsed_ms", "code"):
                if key in ev:
                    extras.append(f"{key}={ev[key]}")
            if t == "citation":
                extras.append(f"cites={len(ev.get('citations', []))}")
            if t == "done":
                extras.append(f"tokens={ev.get('token_usage')}")
            detail = ev.get("detail", "")
            log(f"  [{t:<9}] {detail}   {' '.join(extras)}")
        log(f"  [generate] 共 {gen_chars} 字")
        log(f"  总耗时 {time.time() - t0:.1f}s，事件数 {len(events)}")
    with open("sse_check_result.txt", "w", encoding="utf-8") as f:
        f.write(OUT.getvalue())
    print("done -> sse_check_result.txt")


if __name__ == "__main__":
    main()
