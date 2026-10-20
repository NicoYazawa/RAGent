"""DeepSeek 批量翻译 i18n 候选字符串（术语表强制，i18n 工作流第 3 步）

输入：frontend/src/i18n/candidates/strings.json（i18n_extract_strings.py 产物）
      docs/i18n/glossary.tsv（核心术语表，注入 system prompt 强制套用）
输出：frontend/src/i18n/candidates/translations.json  { "中文": "English", ... }
      frontend/src/i18n/candidates/review.csv        （人工评审用：zh, en, kinds, files）

规则：
- 占位符 {0}/{1}…、%s/%d、[n] 引用序号必须原样保留且数量一致
- 术语表优先于模型自由发挥
- UI 文案风格：按钮/标签用祈使句或名词短语，简洁；Toast/错误消息完整句子
- LLM 提示词（kind=prompt）按"系统指令语气"翻译，保持 Markdown 结构

用法（backend 目录，.env 密钥有效）：
  python scripts/i18n_translate.py            # 全量
  python scripts/i18n_translate.py --limit 20 # 试跑 20 条
"""
import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent


def _find_root() -> Path:
    """定位项目根：含 frontend/src/i18n/candidates 的目录（兼容容器内 /app 布局）"""
    for cand in (BACKEND.parent, BACKEND):
        if (cand / "frontend" / "src" / "i18n" / "candidates").is_dir():
            return cand
    return BACKEND.parent


ROOT = _find_root()
CANDIDATES = ROOT / "frontend" / "src" / "i18n" / "candidates"
GLOSSARY = ROOT / "docs" / "i18n" / "glossary.tsv"
OUT_JSON = CANDIDATES / "translations.json"
OUT_CSV = CANDIDATES / "review.csv"

sys.path.insert(0, str(BACKEND))

_PLACEHOLDER_RE = re.compile(r"\{\d+\}|%[sd]|\[\d+\]")
_BATCH_BUDGET = 4000  # 每批字符预算（中英混合）
_MAX_BATCH = 40

SYS_TEMPLATE = """你是企业软件本地化译者，把中文 UI 字符串翻译成英文。输出 json。

硬性规则：
1. 占位符 {0} {1} 等、%s %d、[n] 引用序号必须原样保留，数量与位置一致
2. 术语表强制套用（左边中文 → 右边英文），不得自行发挥：
__GLOSSARY__
3. 风格：按钮/标签/菜单简洁（祈使句或名词短语）；Toast 与错误消息用完整句子；
   面向开发者的技术词保留惯例写法（HyDE / RRF / CRAG / BM25 / kNN / SSE / NL2SQL 不翻译）
4. kind=prompt 的条目是 LLM 系统指令，按指令语气翻译，保留 Markdown 结构与换行
5. 只输出 json：{"translations": [{"zh": "原中文", "en": "译文"}, ...]}，覆盖输入全部条目，顺序一致

待译条目（json 数组）：
"""


def load_glossary() -> str:
    if not GLOSSARY.exists():
        return "（无术语表）"
    pairs = [ln.split("\t") for ln in GLOSSARY.read_text(encoding="utf-8").split("\n") if "\t" in ln]
    return "\n".join(f"{zh} → {en}" for zh, en in pairs)


def placeholders(s: str) -> list[str]:
    return sorted(_PLACEHOLDER_RE.findall(s))


def make_batches(items: list[dict]) -> list[list[dict]]:
    """按字符预算分批，长 prompt 单独成批"""
    batches, cur, budget = [], [], 0
    for it in items:
        cost = len(it["zh"])
        if cur and (budget + cost > _BATCH_BUDGET or len(cur) >= _MAX_BATCH):
            batches.append(cur)
            cur, budget = [], 0
        cur.append(it)
        budget += cost
    if cur:
        batches.append(cur)
    return batches


async def translate_batch(provider, batch: list[dict], glossary: str) -> dict[str, str]:
    payload = json.dumps([{"zh": it["zh"], "kind": it["kinds"][0]} for it in batch], ensure_ascii=False)
    system = SYS_TEMPLATE.replace("__GLOSSARY__", glossary)
    text, _usage = await provider.ainvoke(
        [{"role": "system", "content": system}, {"role": "user", "content": payload}],
        temperature=0.3,
        json_mode=True,
    )
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise ValueError(f"模型未返回 JSON：{text[:200]}")
    data = json.loads(m.group(0))
    out = {}
    for row in data.get("translations", []):
        zh, en = (row.get("zh") or "").strip(), (row.get("en") or "").strip()
        if zh and en:
            out[zh] = en
    return out


def validate(batch: list[dict], result: dict[str, str]) -> list[str]:
    problems = []
    for it in batch:
        zh = it["zh"]
        en = result.get(zh)
        if not en:
            problems.append(f"缺失译文：{zh[:40]}")
            continue
        if placeholders(zh) != placeholders(en):
            problems.append(f"占位符不一致：{zh[:30]} → {en[:30]}")
    return problems


async def main() -> None:
    parser = argparse.ArgumentParser(description="DeepSeek 批量翻译 i18n 候选")
    parser.add_argument("--limit", type=int, default=0, help="只译前 N 条（试跑）")
    args = parser.parse_args()

    items = json.loads((CANDIDATES / "strings.json").read_text(encoding="utf-8"))
    if args.limit:
        items = items[: args.limit]
    glossary = load_glossary()

    from app.providers import get_llm

    provider = get_llm()
    print(f"供应商：{provider.name} / {provider.model}｜待译 {len(items)} 条｜术语 {glossary.count(chr(10)) + 1} 对")

    translations: dict[str, str] = {}
    batches = make_batches(items)
    for i, batch in enumerate(batches, 1):
        ok = False
        for attempt in range(3):
            try:
                result = await translate_batch(provider, batch, glossary)
                problems = validate(batch, result)
                if not problems:
                    translations.update(result)
                    ok = True
                    break
                print(f"  [批次 {i}/{len(batches)}] 第 {attempt + 1} 次校验失败：{problems[:2]}")
            except Exception as e:  # noqa: BLE001
                print(f"  [批次 {i}/{len(batches)}] 第 {attempt + 1} 次调用失败：{type(e).__name__}: {e}")
        if not ok:
            print(f"  [批次 {i}/{len(batches)}] 放弃，{len(batch)} 条未译（详见上方）")
        else:
            print(f"  [批次 {i}/{len(batches)}] ✓ {len(batch)} 条")

    OUT_JSON.write_text(json.dumps(translations, ensure_ascii=False, indent=1), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["zh", "en", "kinds", "files"])
        for it in items:
            if it["zh"] in translations:
                w.writerow([it["zh"], translations[it["zh"]], "|".join(it["kinds"]), "|".join(it["files"])])

    print(f"\n完成：{len(translations)}/{len(items)} 条")
    print(f"输出：{OUT_JSON}")
    print(f"评审：{OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
