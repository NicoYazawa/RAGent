"""文档解析 — 纯文本 / Markdown / PDF / DOCX 块提取

parse_file 是入库流水线的第一道工序，历史上覆盖率仅 11%。
用真实样本（test_docs 下的 pdf/docx）验证，避免"只在合成输入上正确"。
"""
from pathlib import Path

import pytest

from app.services.parsers import (
    parse_docx_blocks,
    parse_file,
    parse_markdown_blocks,
    parse_pdf_blocks,
    parse_plain_blocks,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEST_DOCS = REPO_ROOT / "test_docs"


# ---------- Plain text ----------

def test_parse_plain_blocks_detects_chinese_chapters():
    """Chinese chapter headings are detected and blocks are split per chapter."""
    text = "第一章 总则\n本制度适用于全体员工。\n\n第二章 考勤管理\n迟到应提前报备。"
    blocks = parse_plain_blocks(text)
    assert len(blocks) == 2
    assert blocks[0][0] == "第一章 总则"
    assert "本制度适用于全体员工" in blocks[0][1]
    assert blocks[1][0] == "第二章 考勤管理"


def test_parse_plain_blocks_heading_text_included_in_content():
    """The heading itself joins the block body (chapter semantics survive the split)."""
    blocks = parse_plain_blocks("第一章 总则\n正文。")
    assert blocks[0][1].startswith("第一章 总则")


def test_parse_plain_blocks_preamble_before_first_heading():
    """The preamble before the first heading becomes its own block with an empty section."""
    blocks = parse_plain_blocks("这是导语。\n\n第一章 总则\n正文。")
    assert blocks[0][0] == ""
    assert "导语" in blocks[0][1]
    assert blocks[1][0] == "第一章 总则"


def test_parse_plain_blocks_detects_numbered_headings():
    """Numeric headings (1. / 2.1.) are detected as well."""
    blocks = parse_plain_blocks("1. 概述\n内容甲。\n2. 细则\n内容乙。")
    assert [b[0] for b in blocks] == ["1. 概述", "2. 细则"]


def test_parse_plain_blocks_empty_text():
    """Empty text -> empty block list."""
    assert parse_plain_blocks("") == []
    assert parse_plain_blocks("\n\n\n") == []


# ---------- Markdown ----------

def test_parse_markdown_blocks_builds_heading_path():
    """Markdown heading levels -> a section_path stack (title/subtitle)."""
    text = "# 员工手册\n内容甲。\n\n## 考勤管理\n内容乙。"
    blocks = parse_markdown_blocks(text)
    assert len(blocks) == 2
    assert blocks[0][0] == "员工手册"
    assert blocks[1][0] == "考勤管理/员工手册" or blocks[1][0] == "员工手册/考勤管理"


def test_parse_markdown_blocks_pop_level_stack():
    """A sibling heading pops the stack (siblings do not inherit each other's path)."""
    text = "# A\n甲。\n## A1\n甲一。\n## A2\n甲二。"
    blocks = parse_markdown_blocks(text)
    paths = [b[0] for b in blocks]
    assert paths[0] == "A"
    assert paths[1] != paths[2]  # A1 and A2 are siblings and do not nest


def test_parse_markdown_blocks_ignores_non_headings():
    """An ordinary line joins the current heading block."""
    blocks = parse_markdown_blocks("# T\n第一行\n第二行")
    assert len(blocks) == 1
    assert "第一行" in blocks[0][1] and "第二行" in blocks[0][1]


def test_parse_markdown_blocks_empty():
    """An empty document -> empty block list."""
    assert parse_markdown_blocks("") == []


# ---------- DOCX (real file) ----------

def _make_docx(path: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_heading("第一章 总则", level=1)
    doc.add_paragraph("本制度适用于全体员工。")
    doc.add_paragraph("自发布之日起施行。")
    doc.add_heading("第二章 考勤管理", level=1)
    doc.add_paragraph("迟到应提前报备。")
    doc.save(str(path))


def test_parse_docx_blocks_extracts_headings(tmp_path):
    """DOCX: Heading styles are treated as chapters and body paragraphs join the block."""
    p = tmp_path / "a.docx"
    _make_docx(p)
    blocks = parse_docx_blocks(p)
    assert len(blocks) >= 2
    assert blocks[0][0] == "第一章 总则"
    assert "本制度适用于全体员工" in blocks[0][1]
    assert any(b[0] == "第二章 考勤管理" for b in blocks)


def test_parse_docx_blocks_handles_empty_document(tmp_path):
    """An empty DOCX -> empty block list."""
    from docx import Document

    p = tmp_path / "empty.docx"
    Document().save(str(p))
    assert parse_docx_blocks(p) == []


def test_parse_docx_blocks_flushes_on_empty_paragraph(tmp_path):
    """A blank paragraph triggers a flush (a blank line inside a chapter loses nothing)."""
    from docx import Document

    doc = Document()
    doc.add_heading("第一章", level=1)
    doc.add_paragraph("甲段。")
    doc.add_paragraph("")  # blank paragraph -> flush
    doc.add_paragraph("乙段。")
    p = tmp_path / "gaps.docx"
    doc.save(str(p))

    blocks = parse_docx_blocks(p)
    assert len(blocks) == 2
    assert "甲段" in blocks[0][1]
    assert "乙段" in blocks[1][1]


# ---------- PDF (real sample) ----------

_REAL_PDF = TEST_DOCS / "01-企业行政制度库" / "员工手册-入职与试用期指引.pdf"


@pytest.mark.skipif(not _REAL_PDF.is_file(), reason="仓库未包含 test_docs 真实样本")
def test_parse_pdf_blocks_extracts_text():
    """A real PDF: non-empty text blocks are extracted."""
    blocks = parse_pdf_blocks(_REAL_PDF)
    assert blocks
    assert all(isinstance(s, str) and isinstance(t, str) for s, t in blocks)
    assert any(t.strip() for _, t in blocks)


@pytest.mark.skipif(not _REAL_PDF.is_file(), reason="仓库未包含 test_docs 真实样本")
def test_parse_file_dispatches_pdf():
    """parse_file dispatches to the PDF parser by type."""
    blocks = parse_file(_REAL_PDF, "pdf")
    assert blocks


# ---------- parse_file dispatch ----------

def test_parse_file_dispatches_markdown(tmp_path):
    """md -> Markdown parsing."""
    p = tmp_path / "a.md"
    p.write_text("# 标题\n内容。", encoding="utf-8")
    blocks = parse_file(p, "md")
    assert blocks and blocks[0][0] == "标题"


def test_parse_file_dispatches_txt(tmp_path):
    """txt -> plain-text parsing."""
    p = tmp_path / "a.txt"
    p.write_text("第一章 总则\n内容。", encoding="utf-8")
    blocks = parse_file(p, "txt")
    assert blocks and blocks[0][0] == "第一章 总则"


def test_parse_file_dispatches_docx(tmp_path):
    """docx -> DOCX parsing."""
    p = tmp_path / "a.docx"
    _make_docx(p)
    assert parse_file(p, "docx")


def test_parse_file_rejects_unsupported_type(tmp_path):
    """An unsupported type raises a clear error (never swallowed silently)."""
    p = tmp_path / "a.exe"
    p.write_bytes(b"MZ")
    with pytest.raises(ValueError, match="不支持的文件类型"):
        parse_file(p, "exe")
