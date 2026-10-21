"""Chunker — whole-chapter first: top-level chapters are aggregated into a single chunk (with a
20% tolerance), and oversized chapters are split on sentence boundaries with overlap."""
import re

from ..config import settings

# Chapter-level headings: 第X章/节/篇/部分 (trustworthy structure); 一、二、... must be short titles
# without in-sentence punctuation (this excludes entries such as 「一、上午工作时间：9:00…」)
_CH_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]+[章节篇部分]")
_CN_NUM_RE = re.compile(r"^[一二三四五六七八九十]+[、.．]")
# Sentence boundaries: Chinese and English end-of-sentence punctuation, plus newlines
_SENTENCE_ENDS = "。！？；!?;\n"


def _is_chapter_title(section: str) -> bool:
    head = section.strip()
    if _CH_RE.match(head):
        return len(head) <= 30
    if _CN_NUM_RE.match(head):
        return len(head) <= 24 and not any(c in head for c in "。！？：；")
    return False


def _block_key(section: str, prev_key: str | None) -> str | None:
    """Block -> chapter key: for multi-segment paths, find the first chapter-level heading segment
    in the prefix (works for both md "title/chapter/..." and pdf "chapter/section"); without a
    chapter marker fall back to the second segment (the first one after an md document title).
    A single-segment path starts a new chapter when it is a top-level title, otherwise it keeps
    the current chapter."""
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
    """Cut point: the last sentence boundary inside the chunk_size window (punctuation included);
    it is usable past the halfway point, otherwise the text is cut hard."""
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
    """Whole-chapter-first chunking: all subsections of a chapter are aggregated; when the total
    stays within the limit (chunk_size x 1.2) the chapter becomes one chunk, otherwise it is split
    on sentence boundaries with overlap."""
    chunk_size = chunk_size or settings.chunk_size
    overlap = min(overlap if overlap else settings.chunk_overlap, chunk_size // 2)
    max_keep = chunk_size + chunk_size // 5  # whole-chapter limit (20% tolerance so a 505-char chapter is not split)

    # 1) Aggregate by chapter: the leading preamble (title/number/date) joins the first chapter;
    #    a document with no detectable chapters becomes a single group
    chapters: list[list] = []  # [chapter-level section, [text, ...]]
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

    # 2) Emit chapter by chapter: one whole chunk or a split on sentence boundaries
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
