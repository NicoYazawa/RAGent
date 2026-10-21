#!/usr/bin/env python
"""End-to-end i18n self-check (no running service required).

Checks:
1. every backend MESSAGES entry has both zh and en, non-empty
2. key SSE/API copy renders in both languages (the English one contains no Chinese)
3. the LLM prompt bundles match and the English prompts contain no Chinese
4. detect_lang language detection
5. the zh-CN / en-US key trees match exactly (node parses the TS bundles)

Exit code: 0 when everything passes; 1 when something fails.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
sys.path.insert(0, str(BACKEND))

from app.agent.llm import detect_lang  # noqa: E402
from app.agent.prompts import PROMPTS  # noqa: E402
from app.i18n import MESSAGES, resolve_locale, t  # noqa: E402

CJK = re.compile(r"[\u4e00-\u9fff]")
failures: list[str] = []


def check(cond: bool, msg: str) -> None:
    if not cond:
        failures.append(msg)


# 1) Backend catalog: both zh and en present and non-empty
for key, entry in MESSAGES.items():
    if key.startswith("test."):
        continue
    check(set(entry) == {"zh-CN", "en-US"}, f"MESSAGES[{key}] 语言不全：{set(entry)}")
    for loc in ("zh-CN", "en-US"):
        check(bool(entry.get(loc, "").strip()), f"MESSAGES[{key}][{loc}] 为空")

# 2) Key copy renders in both languages
SAMPLES = {
    "sse.router.judging": {"intent": "Knowledge-Base Q&A"},
    "sse.grade.score": {"score": 9.0, "icon": "✓", "suffix": ""},
    "sse.retrieve.hits": {"prefix": "", "label": "Vector retrieval", "n": 3},
    "disclaimer.give_up_base": {},
    "api.session_not_found": {},
}
for key, params in SAMPLES.items():
    zh = t(key, "zh-CN", **params)
    en = t(key, "en-US", **params)
    check(bool(zh) and bool(en), f"渲染为空：{key}")
    check(zh != en, f"zh/en 渲染相同（可能漏译）：{key}")
    check(not CJK.search(en), f"英文渲染仍含中文：{key} -> {en!r}")

# 3) LLM prompt bundles
check(set(PROMPTS["zh-CN"]) == set(PROMPTS["en-US"]), "PROMPTS zh/en key 不一致")
for k, v in PROMPTS["en-US"].items():
    check(not CJK.search(v), f"en-US 提示词 {k} 仍含中文")

# 4) detect_lang
check(detect_lang("迟到是怎么认定和处罚的？") == "zh-CN", "detect_lang 中文探测失败")
check(detect_lang("How is lateness handled?") == "en-US", "detect_lang 英文探测失败")
check(detect_lang("") == "zh-CN", "detect_lang 空串未回落 zh-CN")

# 5) Accept-Language parsing
check(resolve_locale("en-US,en;q=0.9") == "en-US", "resolve_locale en 失败")
check(resolve_locale("zh-CN,zh;q=0.9") == "zh-CN", "resolve_locale zh 失败")
check(resolve_locale("fr-FR") == "zh-CN", "resolve_locale 未回落默认")

# 6) Frontend key-tree parity (node parses the TS bundles)
NODE_JS = r"""
const fs=require('fs');
function load(p){return new Function(fs.readFileSync(p,'utf-8').replace('export default','return').replace('as const',''))();}
function keys(o,pre=''){if(typeof o!=='object'||o===null)return[pre];return Object.entries(o).flatMap(([k,v])=>keys(v,pre?pre+'.'+k:k));}
const zh=keys(load('src/i18n/locales/zh-CN.ts')).sort();
const en=keys(load('src/i18n/locales/en-US.ts')).sort();
const missEn=zh.filter(k=>!en.includes(k));
const missZh=en.filter(k=>!zh.includes(k));
console.log('zh='+zh.length+' en='+en.length+' missEn='+missEn.length+' missZh='+missZh.length);
console.log((missEn.length===0&&missZh.length===0)?'PARITY OK':'PARITY MISMATCH '+JSON.stringify({missEn,missZh}));
"""
res = subprocess.run(["node", "-e", NODE_JS], cwd=str(FRONTEND), capture_output=True, text=True)
check(res.returncode == 0 and "PARITY OK" in res.stdout, f"前端 key 树不一致：{res.stdout.strip()} {res.stderr.strip()}")

# Summary
print("=" * 56)
print(f"后端 MESSAGES keys : {len([k for k in MESSAGES if not k.startswith('test.')])}")
print(f"提示词 bundle keys : {len(PROMPTS['zh-CN'])}")
print(f"前端 key 树       : {res.stdout.strip().splitlines()[0] if res.stdout.strip() else '(node 未输出)'}")
print("=" * 56)
if failures:
    print(f"[FAIL] 自检失败 {len(failures)} 项：")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("[OK] i18n 自检全部通过")
