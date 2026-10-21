"""Document parsing — md / txt are read directly (heading levels preserved), pdf via pypdf,
docx via python-docx.

The output is a uniform list of [(section_path, text), ...] blocks for the chunker to merge.
"""
import re
from pathlib import Path

HEADING_PATTERNS = [
    re.compile(r"^第[一二三四五六七八九十百千0-9]+[章节篇部分]"),  # Chinese chapter headings, e.g. 第一章 / 第3节
    re.compile(r"^[一二三四五六七八九十]+[、.．]"),  # Chinese numbered items, e.g. 一、
    re.compile(r"^\d+(\.\d+)*[、.\s]"),  # 1. / 2.1.3
    re.compile(r"^#{1,6}\s"),  # Markdown heading
]


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 60:
        return False
    return any(p.match(s) for p in HEADING_PATTERNS)


def _clean_heading(line: str) -> str:
    return line.strip().lstrip("#").strip()


def parse_plain_blocks(text: str) -> list[tuple[str, str]]:
    """Plain text / txt: detect levels with the chapter-heading regexes and accumulate
    paragraphs into blocks."""
    blocks: list[tuple[str, str]] = []
    section = ""
    buf: list[str] = []
    for line in text.splitlines():
        if _is_heading(line):
            if buf:
                blocks.append((section, "\n".join(buf).strip()))
                buf = []
            section = _clean_heading(line)
            buf = [section]
        else:
            s = line.strip()
            if s:
                buf.append(s)
            elif buf:
                blocks.append((section, "\n".join(buf).strip()))
                buf = []
    if buf:
        blocks.append((section, "\n".join(buf).strip()))
    return [(s, t) for s, t in blocks if t]


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def parse_markdown_blocks(text: str) -> list[tuple[str, str]]:
    """Markdown: the # hierarchy maintains a heading path stack."""
    blocks: list[tuple[str, str]] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    buf: list[str] = []

    def flush() -> None:
        if buf:
            path = "/".join(t for _, t in stack)
            blocks.append((path, "\n".join(buf).strip()))
            buf.clear()

    for line in text.splitlines():
        m = _MD_HEADING.match(line.strip())
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            buf = [title]
        else:
            s = line.rstrip()
            if s.strip():
                buf.append(s.strip())
            elif buf:
                flush()
    flush()
    return [(s, t) for s, t in blocks if t]


_CHAPTER_LINE_RE = re.compile(r"^第[一二三四五六七八九十百千0-9]+[章节篇部分]")


def parse_pdf_blocks(path: Path) -> list[tuple[str, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = [(p.extract_text() or "") for p in reader.pages]
    # PDFs carry no heading metadata: one block per page, tracking the 第X章 context across pages
    # so a subsection path hangs under its chapter
    blocks: list[tuple[str, str]] = []
    chapter = ""
    for i, page in enumerate(pages, 1):
        for section, text in parse_plain_blocks(page):
            if section and _CHAPTER_LINE_RE.match(section):
                chapter = section
                blocks.append((section, text))
            elif chapter and section:
                blocks.append((f"{chapter}/{section}", text))
            else:
                blocks.append((section or chapter or f"第{i}页", text))
    return blocks


def parse_docx_blocks(path: Path) -> list[tuple[str, str]]:
    from docx import Document

    doc = Document(str(path))
    blocks: list[tuple[str, str]] = []
    section = ""
    buf: list[str] = []

    def flush() -> None:
        if buf:
            blocks.append((section, "\n".join(buf).strip()))
            buf.clear()

    for para in doc.paragraphs:
        style = (para.style.name or "").lower()
        text = para.text.strip()
        if not text:
            flush()
            continue
        if "heading" in style or _is_heading(text):
            flush()
            section = text
            buf.append(text)
        else:
            buf.append(text)
    flush()
    return [(s, t) for s, t in blocks if t]


def parse_file(path: Path, file_type: str) -> list[tuple[str, str]]:
    """Parse by type into [(section_path, text), ...]."""
    if file_type == "md":
        return parse_markdown_blocks(path.read_text(encoding="utf-8", errors="replace"))
    if file_type == "txt":
        return parse_plain_blocks(path.read_text(encoding="utf-8", errors="replace"))
    if file_type == "pdf":
        return parse_pdf_blocks(path)
    if file_type == "docx":
        return parse_docx_blocks(path)
    raise ValueError(f"不支持的文件类型：{file_type}")
