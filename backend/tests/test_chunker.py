"""切片器 — 整章优先聚合 / 句子边界切分 / 重叠 / 20% 容差

chunk_blocks 决定检索粒度，历史上完全没有测试（覆盖率 15%）：
可以改坏去重边界、可以改坏重叠、可以改坏切点而测试全绿。
"""
from app.services.chunker import _block_key, _find_cut, _is_chapter_title, chunk_blocks

# ---------- Heading detection ----------

def test_is_chapter_title_recognizes_chinese_chapters():
    """第X章/节/篇/部分 headings count as chapter level."""
    assert _is_chapter_title("第一章 总则")
    assert _is_chapter_title("第3节 适用范围")
    assert _is_chapter_title("第二篇 附则")


def test_is_chapter_title_rejects_ordinary_sentences():
    """An ordinary sentence is not a chapter heading."""
    assert not _is_chapter_title("迟到是怎么认定的？")
    assert not _is_chapter_title("")
    assert not _is_chapter_title("第" + "一" * 40 + "章")


def test_is_chapter_title_rejects_long_numbered_item():
    """An over-long numbered entry is not a chapter heading (so 「一、上午工作时间：9:00…」 is not
    mistaken for one)."""
    assert not _is_chapter_title("一、" + "很长" * 30)
    assert not _is_chapter_title("一、上午工作时间：9:00-18:00")


# ---------- Block -> chapter key ----------

def test_block_key_picks_chapter_segment():
    """A multi-segment path prefers the chapter-level heading segment."""
    assert _block_key("第一章 总则/第一条/正文", None) == "第一章 总则"


def test_block_key_single_chapter_heading():
    """A single segment that is a chapter heading becomes its own chapter key."""
    assert _block_key("第一章", None) == "第一章"


def test_block_key_falls_back_to_prev_key():
    """No chapter detectable -> keep the previous block's chapter key."""
    assert _block_key("普通段落", "第一章") == "第一章"
    assert _block_key("普通段落", None) is None


def test_block_key_uses_second_segment_when_no_chapter_marker():
    """A multi-segment path without a chapter marker takes the second segment (the first one after an
    md document title)."""
    assert _block_key("文档标题/1.1 节", None) == "1.1 节"


# ---------- Cut points ----------

def test_find_cut_prefers_sentence_boundary():
    """The cut lands on the last sentence boundary inside the window, provided it is past the halfway
    point."""
    text = "第一句内容在这里。" + "填充内容。" * 5 + "最后一句在这里。"
    cut = _find_cut(text, 60)
    assert cut == text.rindex("。") + 1
    assert cut > 30  # in the second half of the window


def test_find_cut_takes_last_boundary_not_first():
    """Several full stops in one window -> take the last one so the content stays as complete as possible."""
    text = "甲句。" + "填充。" * 8 + "乙句。"
    size = 20
    window = text[:size]
    cut = _find_cut(text, size)
    assert cut == window.rindex("。") + 1
    assert cut != window.index("。") + 1


def test_find_cut_falls_back_to_hard_cut():
    """No full stop in the first half -> cut hard at chunk_size."""
    text = "没有句号的连续文本" * 20
    cut = _find_cut(text, 50)
    assert cut == 50


def test_find_cut_ignores_boundary_in_first_half():
    """A full stop in the first half (before the halfway point) is unusable, so the text is cut hard."""
    text = "短句。" + "长" * 100
    cut = _find_cut(text, 100)
    assert cut == 100


# ---------- chunk_blocks ----------

def test_chunk_blocks_empty_input():
    """Empty input -> empty result."""
    assert chunk_blocks([]) == []


def test_chunk_blocks_single_short_block():
    """A single small block -> one chunk."""
    chunks = chunk_blocks([("第一章", "很短的正文。")], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    c = chunks[0]
    assert c["chunk_no"] == 1
    assert c["section_path"] == "第一章"
    assert "很短的正文" in c["content"]
    assert c["token_count"] >= 1


def test_chunk_blocks_aggregates_same_chapter_sections():
    """Several subsections of one chapter merge into a single chunk (whole chapter first)."""
    chunks = chunk_blocks([
        ("第一章 总则", "第一条 内容甲。"),
        ("第一章 总则/第二条", "第二条 内容乙。"),
    ], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert "内容甲" in chunks[0]["content"]
    assert "内容乙" in chunks[0]["content"]


def test_chunk_blocks_separates_different_chapters():
    """Different chapters -> different chunks."""
    chunks = chunk_blocks([
        ("第一章 总则", "甲章正文。"),
        ("第二章 职责", "乙章正文。"),
    ], chunk_size=500, overlap=50)
    assert len(chunks) == 2
    assert chunks[0]["section_path"] != chunks[1]["section_path"]
    assert [c["chunk_no"] for c in chunks] == [1, 2]


def test_chunk_blocks_keeps_whole_chapter_within_20pct_tolerance():
    """A chapter slightly over chunk_size but within the 20% tolerance stays one chunk (no hard cut)."""
    body = "字" * 550  # chunk_size=500，max_keep=600
    chunks = chunk_blocks([("第一章", body)], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert len(chunks[0]["content"]) == 550


def test_chunk_blocks_splits_long_chapter_with_overlap():
    """An oversized chapter splits into several chunks on sentence boundaries, with overlap between
    neighbours so semantics are not severed.

    The body deliberately uses **non-periodic** content: with a repeated template per sentence, a
    no-overlap variant would match by accident and the test could not tell whether overlap really
    applies.
    """
    body = "".join(f"第{i:02d}段内容编号{i:02d}各不相同。" for i in range(40))
    chunks = chunk_blocks([("第一章", body)], chunk_size=200, overlap=50)
    assert len(chunks) > 1
    assert [c["chunk_no"] for c in chunks] == list(range(1, len(chunks) + 1))
    # The opening text of each following chunk must appear in the previous one (that is what overlap does)
    for i in range(len(chunks) - 1):
        head = chunks[i + 1]["content"][:20]
        assert head in chunks[i]["content"], f"第 {i + 1} 片与第 {i + 2} 片之间没有重叠"



def test_chunk_blocks_respects_overlap_capped_at_half_chunk_size():
    """Overlap is capped at half of chunk_size (an oversized value is clamped)."""
    body = "句子内容用于测试重叠上限行为。" * 30
    chunks = chunk_blocks([("第一章", body)], chunk_size=200, overlap=999)
    assert len(chunks) > 1
    # overlapping back at most chunk_size//2 = 100 chars from the cut
    assert len(chunks[0]["content"]) <= 200


def test_chunk_blocks_token_count_estimated():
    """token_count is estimated as chars x 0.62 with a floor of 1."""
    chunks = chunk_blocks([("第一章", "短")], chunk_size=500, overlap=50)
    assert chunks[0]["token_count"] == max(1, round(len(chunks[0]["content"]) * 0.62))


def test_chunk_blocks_preamble_merges_into_first_chapter():
    """The leading preamble (no chapter detected) joins the first chapter instead of forming its own chunk."""
    chunks = chunk_blocks([
        ("文档标题", "这是导语部分。"),
        ("第一章 总则", "第一章正文。"),
    ], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert "导语部分" in chunks[0]["content"]
    assert "第一章正文" in chunks[0]["content"]


def test_chunk_blocks_no_chapter_marker_keeps_single_chunk():
    """A document with no detectable chapters becomes a single group."""
    chunks = chunk_blocks([
        ("普通段落一", "内容甲。"),
        ("普通段落二", "内容乙。"),
    ], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert "内容甲" in chunks[0]["content"]
    assert "内容乙" in chunks[0]["content"]


def test_chunk_blocks_empty_text_blocks_produce_nothing():
    """An empty block text produces no chunk."""
    assert chunk_blocks([("第一章", "")], chunk_size=500, overlap=50) == []

