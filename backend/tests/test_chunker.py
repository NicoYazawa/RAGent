"""切片器 — 整章优先聚合 / 句子边界切分 / 重叠 / 20% 容差

chunk_blocks 决定检索粒度，历史上完全没有测试（覆盖率 15%）：
可以改坏去重边界、可以改坏重叠、可以改坏切点而测试全绿。
"""
from app.services.chunker import _block_key, _find_cut, _is_chapter_title, chunk_blocks

# ---------- 标题识别 ----------

def test_is_chapter_title_recognizes_chinese_chapters():
    """第X章/节/篇/部分 是章级标题"""
    assert _is_chapter_title("第一章 总则")
    assert _is_chapter_title("第3节 适用范围")
    assert _is_chapter_title("第二篇 附则")


def test_is_chapter_title_rejects_ordinary_sentences():
    """普通句子不是章标题"""
    assert not _is_chapter_title("迟到是怎么认定的？")
    assert not _is_chapter_title("")
    assert not _is_chapter_title("第" + "一" * 40 + "章")


def test_is_chapter_title_rejects_long_numbered_item():
    """过长的编号条目不当作章标题（避免「一、上午工作时间：9:00…」被误判）"""
    assert not _is_chapter_title("一、" + "很长" * 30)
    assert not _is_chapter_title("一、上午工作时间：9:00-18:00")


# ---------- 块 → 章键 ----------

def test_block_key_picks_chapter_segment():
    """多段路径优先取章级标题段"""
    assert _block_key("第一章 总则/第一条/正文", None) == "第一章 总则"


def test_block_key_single_chapter_heading():
    """单段且是章标题 → 自身为章键"""
    assert _block_key("第一章", None) == "第一章"


def test_block_key_falls_back_to_prev_key():
    """无法识别章节 → 沿用上一块的章键"""
    assert _block_key("普通段落", "第一章") == "第一章"
    assert _block_key("普通段落", None) is None


def test_block_key_uses_second_segment_when_no_chapter_marker():
    """无章标记的多段路径 → 取第二段（md 文档标题后的第一段）"""
    assert _block_key("文档标题/1.1 节", None) == "1.1 节"


# ---------- 切点 ----------

def test_find_cut_prefers_sentence_boundary():
    """切点落在窗口内最靠后的句子边界（且该边界在窗口后半段）"""
    text = "第一句内容在这里。" + "填充内容。" * 5 + "最后一句在这里。"
    cut = _find_cut(text, 60)
    assert cut == text.rindex("。") + 1
    assert cut > 30  # 位于窗口后半段


def test_find_cut_takes_last_boundary_not_first():
    """同窗口内多个句号 → 取窗口内最靠后的那个（内容尽量完整）"""
    text = "甲句。" + "填充。" * 8 + "乙句。"
    size = 20
    window = text[:size]
    cut = _find_cut(text, size)
    assert cut == window.rindex("。") + 1
    assert cut != window.index("。") + 1


def test_find_cut_falls_back_to_hard_cut():
    """窗口前半段找不到句号 → 硬切到 chunk_size"""
    text = "没有句号的连续文本" * 20
    cut = _find_cut(text, 50)
    assert cut == 50


def test_find_cut_ignores_boundary_in_first_half():
    """句号出现在窗口前半段（不足半）→ 视为不可用，硬切"""
    text = "短句。" + "长" * 100
    cut = _find_cut(text, 100)
    assert cut == 100


# ---------- chunk_blocks ----------

def test_chunk_blocks_empty_input():
    """空输入 → 空结果"""
    assert chunk_blocks([]) == []


def test_chunk_blocks_single_short_block():
    """单个小块 → 一片"""
    chunks = chunk_blocks([("第一章", "很短的正文。")], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    c = chunks[0]
    assert c["chunk_no"] == 1
    assert c["section_path"] == "第一章"
    assert "很短的正文" in c["content"]
    assert c["token_count"] >= 1


def test_chunk_blocks_aggregates_same_chapter_sections():
    """同一章的多个小节聚合为一片（整章优先）"""
    chunks = chunk_blocks([
        ("第一章 总则", "第一条 内容甲。"),
        ("第一章 总则/第二条", "第二条 内容乙。"),
    ], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert "内容甲" in chunks[0]["content"]
    assert "内容乙" in chunks[0]["content"]


def test_chunk_blocks_separates_different_chapters():
    """不同章 → 不同切片"""
    chunks = chunk_blocks([
        ("第一章 总则", "甲章正文。"),
        ("第二章 职责", "乙章正文。"),
    ], chunk_size=500, overlap=50)
    assert len(chunks) == 2
    assert chunks[0]["section_path"] != chunks[1]["section_path"]
    assert [c["chunk_no"] for c in chunks] == [1, 2]


def test_chunk_blocks_keeps_whole_chapter_within_20pct_tolerance():
    """略超 chunk_size 但在 20% 容差内的章 → 仍为整章一片（不硬切）"""
    body = "字" * 550  # chunk_size=500，max_keep=600
    chunks = chunk_blocks([("第一章", body)], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert len(chunks[0]["content"]) == 550


def test_chunk_blocks_splits_long_chapter_with_overlap():
    """超长章按句子边界切分多片，且相邻片有重叠（避免语义割裂）

    正文刻意用**非周期**内容：若各句重复同一模板，
    无重叠时也能"偶然"匹配上，测不出重叠是否真的生效。
    """
    body = "".join(f"第{i:02d}段内容编号{i:02d}各不相同。" for i in range(40))
    chunks = chunk_blocks([("第一章", body)], chunk_size=200, overlap=50)
    assert len(chunks) > 1
    assert [c["chunk_no"] for c in chunks] == list(range(1, len(chunks) + 1))
    # 相邻两片头部文本必须出现在前一片中（这正是 overlap 的作用）
    for i in range(len(chunks) - 1):
        head = chunks[i + 1]["content"][:20]
        assert head in chunks[i]["content"], f"第 {i + 1} 片与第 {i + 2} 片之间没有重叠"



def test_chunk_blocks_respects_overlap_capped_at_half_chunk_size():
    """overlap 上限为 chunk_size 的一半（传入超大 overlap 也被压住）"""
    body = "句子内容用于测试重叠上限行为。" * 30
    chunks = chunk_blocks([("第一章", body)], chunk_size=200, overlap=999)
    assert len(chunks) > 1
    # 切点之后最多回退 chunk_size//2 = 100 字符
    assert len(chunks[0]["content"]) <= 200


def test_chunk_blocks_token_count_estimated():
    """token_count 按字符数 ×0.62 估算且至少为 1"""
    chunks = chunk_blocks([("第一章", "短")], chunk_size=500, overlap=50)
    assert chunks[0]["token_count"] == max(1, round(len(chunks[0]["content"]) * 0.62))


def test_chunk_blocks_preamble_merges_into_first_chapter():
    """文首导语（识别不出章节）并入第一章，不单独成片"""
    chunks = chunk_blocks([
        ("文档标题", "这是导语部分。"),
        ("第一章 总则", "第一章正文。"),
    ], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert "导语部分" in chunks[0]["content"]
    assert "第一章正文" in chunks[0]["content"]


def test_chunk_blocks_no_chapter_marker_keeps_single_chunk():
    """完全识别不出章节的文档整体归为一组"""
    chunks = chunk_blocks([
        ("普通段落一", "内容甲。"),
        ("普通段落二", "内容乙。"),
    ], chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert "内容甲" in chunks[0]["content"]
    assert "内容乙" in chunks[0]["content"]


def test_chunk_blocks_empty_text_blocks_produce_nothing():
    """块文本为空 → 不产出切片"""
    assert chunk_blocks([("第一章", "")], chunk_size=500, overlap=50) == []

