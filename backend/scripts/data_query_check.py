"""data_query 单链路验证（含 NL2SQL 反思回流补查）"""
import json
import sys
import urllib.request

sys.path.insert(0, ".")
from scripts.sse_check import ask_stream, post_json, log, OUT  # noqa: E402


def main() -> None:
    sess = post_json("/api/chat/sessions")
    events = ask_stream(sess["id"], "上季度哪个产品卖得最好？")
    gen = 0
    for ev in events:
        if ev["type"] == "generate":
            gen += len(ev.get("delta", ""))
            continue
        extras = {k: ev[k] for k in ("source", "hit_count", "score", "verdict", "result", "citations", "elapsed_ms") if k in ev}
        log(f"[{ev['type']}] {ev.get('detail', '')[:90]}  {extras}")
    log(f"generate {gen} chars, events={len(events)}")
    with open("data_query_check.txt", "w", encoding="utf-8") as f:
        f.write(OUT.getvalue())
    print("done")


if __name__ == "__main__":
    main()
