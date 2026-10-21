"""Extract Chinese UI strings from the frontend and backend into a translation candidate list
(step 2 of the i18n workflow).

Scope:
- template text, attribute values and string literals in .vue/.ts/.js under frontend/src
- user-visible backend strings (full literals, f-string placeholders normalized to {0}/{1}...):
  - app/agent/orchestrator.py: SSE decision-chain text plus generation-side notices
  - app/routers/*.py: HTTPException error messages
  - app/agent/prompts.py: LLM prompt templates (English questions need English prompts; kind=prompt)

Output: frontend/src/i18n/candidates/strings.json
  [{ "zh": "...", "kinds": ["text"|"attr"|"literal"|"sse"|"api"|"prompt"], "files": [...], "count": 3 }]

Filtering: strings without CJK, pure ASCII/digit strings, and log or debug strings
(literals on the same line as console./logger.).
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
ROOT = BACKEND.parent
FRONTEND_SRC = ROOT / "frontend" / "src"
OUT = FRONTEND_SRC / "i18n" / "candidates" / "strings.json"

_CJK_RE = re.compile("[\u4e00-\u9fff]")


def _clean(s: str) -> str:
    return s.strip().strip("，,。.；;：:！!？?、 ").strip()


def _keep(s: str) -> bool:
    if len(s) < 2 or not _CJK_RE.search(s):
        return False
    if s.startswith(("#", ".", "/", "http", "{", "$", "@")):
        return False
    return True


# ---------- Frontend ----------

def extract_frontend() -> list[tuple[str, str, str]]:
    """Return (string, kind, file) triples."""
    out = []
    for f in sorted(FRONTEND_SRC.rglob("*")):
        if f.suffix not in {".vue", ".ts", ".js"} or "i18n/candidates" in str(f):
            continue
        rel = str(f.relative_to(FRONTEND_SRC))
        for line in f.read_text(encoding="utf-8").split("\n"):
            is_log = ("console." in line) or ("logger." in line)
            for m in re.finditer(r'=\s*"([^"<>]*[\u4e00-\u9fff][^"<>]*)"', line):
                s = _clean(m.group(1))
                if _keep(s) and not is_log:
                    out.append((s, "attr", rel))
            for m in re.finditer(r"=\s*'([^'<>]*[\u4e00-\u9fff][^'<>]*)'", line):
                s = _clean(m.group(1))
                if _keep(s) and not is_log:
                    out.append((s, "attr", rel))
            if is_log:
                continue
            for pat in (
                r"'([^'\\\n]*[\u4e00-\u9fff][^'\\\n]*)'",
                r'"([^"\\\n]*[\u4e00-\u9fff][^"\\\n]*)"',
                r"`([^`\\]*[\u4e00-\u9fff][^`\\]*)`",
            ):
                for m in re.finditer(pat, line):
                    s = _clean(m.group(1))
                    if _keep(s):
                        out.append((s, "literal", rel))
            for m in re.finditer(r">\s*([^<>{}]*[\u4e00-\u9fff][^<>{}]*?)\s*<", line):
                s = _clean(m.group(1))
                if _keep(s):
                    out.append((s, "text", rel))
    return out


# ---------- Backend (full literals) ----------

def _strip_docstrings(text: str) -> str:
    """Remove triple-quoted docstring blocks so comments are not collected as UI copy."""
    return re.sub(r'""".*?"""', '""', text, flags=re.DOTALL)


def _normalize_placeholders(s: str) -> str:
    """f-string 表达式 {expr} → {0}/{1}…，保证翻译时占位符不丢"""
    idx = 0

    def repl(_m):
        nonlocal idx
        ph = "{%d}" % idx
        idx += 1
        return ph

    return re.sub(r"\{[^{}]*\}", repl, s)


def extract_backend_literals(path: Path, kind: str, rel: str) -> list[tuple[str, str, str]]:
    """Extract Chinese string literals from a py file (docstrings removed, log-only strings skipped)."""
    text = _strip_docstrings(path.read_text(encoding="utf-8"))
    lines = text.split("\n")
    out = []
    pat = re.compile(r'(?:[fr]?)(?:"((?:[^"\\]|\\.)*)"|\'((?:[^\'\\]|\\.)*)\')')
    for m in pat.finditer(text):
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        if not _CJK_RE.search(raw):
            continue
        line = lines[text.count("\n", 0, m.start())]
        if "logger." in line or "logging." in line or "_print_block" in line:
            continue
        s = _normalize_placeholders(raw)
        s = _clean(s)
        if _keep(s) and len(s) >= 4:
            out.append((s, kind, rel))
    return out


def extract_backend() -> list[tuple[str, str, str]]:
    out = []
    out += extract_backend_literals(BACKEND / "app" / "agent" / "orchestrator.py", "sse", "orchestrator.py")
    for rf in sorted((BACKEND / "app" / "routers").glob("*.py")):
        out += extract_backend_literals(rf, "api", rf.name)
    out += extract_backend_literals(BACKEND / "app" / "agent" / "prompts.py", "prompt", "prompts.py")
    return out


def main() -> None:
    merged: dict[str, dict] = {}
    for zh, kind, fname in extract_frontend() + extract_backend():
        slot = merged.setdefault(zh, {"zh": zh, "kinds": set(), "files": set(), "count": 0})
        slot["kinds"].add(kind)
        slot["files"].add(fname)
        slot["count"] += 1
    items = [
        {"zh": v["zh"], "kinds": sorted(v["kinds"]), "files": sorted(v["files"]), "count": v["count"]}
        for v in sorted(merged.values(), key=lambda x: (-x["count"], x["zh"]))
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    by_kind: dict[str, int] = {}
    for it in items:
        for k in it["kinds"]:
            by_kind[k] = by_kind.get(k, 0) + 1
    print(f"候选字符串：{len(items)} 条（去重后）")
    print(f"按类型：{by_kind}")
    print(f"输出：{OUT}")


if __name__ == "__main__":
    main()
