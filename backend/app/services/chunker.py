"""切片器 — 整章优先：顶级章节聚合为单片（+20% 容差），超限章按句子边界带重叠切分"""
import re

from ..config import settings

# 章级标题：第X章/节/篇/部分（结构可信）；一、二、……须为短标题且不含句内标点（排除「一、上午工作时间：9:00…」类条目）
_CH_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]+[章节篇部分]")
_CN_NUM_RE = re.compile(r"^[一二三四五六七八九十]+[、.．]")
# 句子边界：中英文句末标点或换行
_SENTENCE_ENDS = "。！？；!?;\n"


def _is_chapter_title(section: str) -> bool:
    head = section.strip()
    if _CH_RE.match(head):
        return len(head) <= 30
    if _CN_NUM_RE.match(head):
        return len(head) <= 24 and not any(c in head for c in "。！？：；")
    return False


def _block_key(section: str, prev_key: str | None) -> str | None:
    """块 → 章键：多段路径在前缀中找第一个章级标题段（md「标题/章/…」、pdf「章/小节」均适用），
    无章级标记时退回第二段（md 文档标题后的第一段）；单段路径顶级标题开新章，其余沿用当前章"""
    parts = [p for p in section.split("/") if p]
    if len(parts) >= 2:
        for p in parts[:-1]:
            if _is_chapter_title(p):
                return p
        return parts[1]
    head = parts[0] if parts else ""
    if head and _is_chapter_title(head):
        return head
    return prev_key


def _find_cut(text: str, chunk_size: int) -> int:
    """切点：chunk_size 窗口内最靠后的句子边界（含标点），过半即可用，否则硬切"""
    window = text[:chunk_size]
    best = max(window.rfind(c) for c in _SENTENCE_ENDS)
    if best >= chunk_size // 2:
        return best + 1
    return chunk_size


def chunk_blocks(
    blocks: list[tuple[str, str]],
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> list[dict]:
    """整章优先切片：同章小节全部聚合；总长 ≤ 上限（chunk_size×1.2）整章一片，超限章按句子边界切分并带重叠"""
    chunk_size = chunk_size or settings.chunk_size
    overlap = min(overlap if overlap else settings.chunk_overlap, chunk_size // 2)
    max_keep = chunk_size + chunk_size // 5  # 整章单片上限（20% 容差，避免 505 字的章被切成两片）

    # 1) 按章聚合：文首导语（标题/编号/日期）并入首章；识别不出章节的文档整体归为一组
    chapters: list[list] = []  # [章级 section, [text, ...]]
    preamble: list[str] = []
    key: str | None = None
    for section, text in blocks:
        k = _block_key(section, key)
        if k is None:
            preamble.append(text)
            continue
        if k != key:
            chapters.append([section[:500], preamble + [text]])
            preamble = []
            key = k
        else:
            chapters[-1][1].append(text)
    if not chapters:
        if not preamble:
            return []
        chapters = [[blocks[0][0][:500], preamble]]

    # 2) 逐章产出：整章单片或按句子边界切分
    chunks: list[dict] = []
    for section, texts in chapters:
        cur = "\n".join(texts).strip()
        while len(cur) > max_keep:
            cut = _find_cut(cur, chunk_size)
            piece = cur[:cut].strip()
            if piece:
                chunks.append(
                    {
                        "chunk_no": len(chunks) + 1,
                        "section_path": section,
                        "content": piece,
                        "token_count": max(1, round(len(piece) * 0.62)),
                    }
                )
            cur = cur[max(0, cut - overlap):].strip()
        if cur:
            chunks.append(
                {
                    "chunk_no": len(chunks) + 1,
                    "section_path": section,
                    "content": cur,
                    "token_count": max(1, round(len(cur) * 0.62)),
                }
            )
    return chunks
