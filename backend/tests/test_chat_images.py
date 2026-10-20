"""问答图片服务 — 路径穿越 / 幻数校验 / 数量与大小上限 / 落盘与转换

chat_images 是唯一处理「用户上传二进制」的地方，安全边界最敏感，
历史上覆盖率仅 32%，且四道防线（路径穿越、幻数、数量、体积）
全部可以改坏而测试全绿。
"""
import base64
import os

import pytest

from app.services import chat_images

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


@pytest.fixture
def img_dir(tmp_path, monkeypatch):
    """把落盘目录指向 tmp_path，避免污染真实 data/uploads"""
    d = tmp_path / "chat_images"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(chat_images, "CHAT_IMAGE_DIR", d)
    return d


def _data_url(mime: str, blob: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"


# ---------- image_path：路径穿越防线 ----------

@pytest.mark.parametrize(
    "name",
    [
        "../../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "not-a-uuid.png",
        "0123456789abcdef0123456789abcdeg.png",  # 33 位，非法
        "0123456789abcdef0123456789abcde.exe",  # 扩展名不在白名单
        "",
    ],
)
def test_image_path_rejects_unsafe_names(name, img_dir):
    """非法文件名一律返回 None（防路径穿越 / 任意文件读取）"""
    assert chat_images.image_path(name) is None


def test_image_path_returns_existing_file(img_dir):
    """合法且存在的文件返回绝对路径"""
    (img_dir / ("a" * 32 + ".png")).write_bytes(PNG_MAGIC)
    p = chat_images.image_path("a" * 32 + ".png")
    assert p is not None and p.endswith(".png")


def test_image_path_missing_file_returns_none(img_dir):
    """合法命名但文件不存在 → None"""
    assert chat_images.image_path("b" * 32 + ".png") is None


def test_image_path_rejects_traversal_to_existing_file(tmp_path, monkeypatch):
    """路径穿越到**真实存在**的文件也必须被拒（防任意文件读取）

    这是安全回归的关键：仅"文件不存在"不足以证明防护有效——
    攻击者只需先让目标文件存在。测试在这里放一个真实文件，
    移除白名单校验后 image_path 就会返回它。
    """
    d = tmp_path / "chat_images"
    d.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG_MAGIC)
    monkeypatch.setattr(chat_images, "CHAT_IMAGE_DIR", d)

    traversal = os.path.relpath(outside, d).replace("\\", "/")
    assert outside.is_file()  # 前提：目标真实存在
    assert chat_images.image_path(traversal) is None


# ---------- save_images：四道防线 ----------

def test_save_images_empty_list_returns_empty(img_dir):
    """无图片 → 空列表"""
    assert chat_images.save_images([]) == []


def test_save_images_persists_valid_png(img_dir):
    """合法 PNG：落盘并返回站内 URL"""
    urls = chat_images.save_images([_data_url("image/png", PNG_MAGIC + b"body")])
    assert len(urls) == 1
    assert urls[0].startswith(chat_images.CHAT_IMAGE_URL_PREFIX)
    name = urls[0].removeprefix(chat_images.CHAT_IMAGE_URL_PREFIX)
    assert (img_dir / name).is_file()


def test_save_images_rejects_mime_content_mismatch(img_dir):
    """幻数校验：声明 png 但内容不是 png → 拒绝"""
    with pytest.raises(ValueError, match="内容与声明格式不符"):
        chat_images.save_images([_data_url("image/png", b"GIF89a" + b"x" * 50)])


def test_save_images_rejects_unsupported_format(img_dir):
    """非白名单 MIME 直接拒绝"""
    with pytest.raises(ValueError, match="格式不支持"):
        chat_images.save_images([_data_url("image/svg+xml", b"<svg/>")])


def test_save_images_rejects_bad_base64(img_dir):
    """base64 非法 → 拒绝"""
    with pytest.raises(ValueError, match="解码失败"):
        chat_images.save_images(["data:image/png;base64,!!!not-base64!!!"])


def test_save_images_enforces_count_limit(img_dir, monkeypatch):
    """单条消息图片数量上限（默认 4 张）"""
    monkeypatch.setattr(chat_images.settings, "chat_image_max_count", 2)
    urls = [_data_url("image/png", PNG_MAGIC + bytes([i])) for i in range(3)]
    with pytest.raises(ValueError, match="最多附带"):
        chat_images.save_images(urls)


def test_save_images_enforces_size_limit(img_dir, monkeypatch):
    """单张图片体积上限"""
    monkeypatch.setattr(chat_images.settings, "chat_image_max_bytes", 10)
    with pytest.raises(ValueError, match="不能超过"):
        chat_images.save_images([_data_url("image/png", PNG_MAGIC + b"x" * 100)])


def test_save_images_reuses_existing_site_url(img_dir):
    """站内 URL（重答场景）→ 校验后复用，不重复落盘"""
    name = "c" * 32 + ".jpg"
    (img_dir / name).write_bytes(JPEG_MAGIC)
    url = chat_images.CHAT_IMAGE_URL_PREFIX + name
    assert chat_images.save_images([url]) == [url]


def test_save_images_rejects_stale_site_url(img_dir):
    """站内 URL 指向不存在的文件 → 拒绝"""
    url = chat_images.CHAT_IMAGE_URL_PREFIX + ("d" * 32 + ".png")
    with pytest.raises(ValueError, match="图片引用无效"):
        chat_images.save_images([url])


# ---------- to_data_urls ----------

def test_to_data_urls_converts_existing_files(img_dir):
    """站内 URL → base64 data URL（喂给视觉模型）"""
    name = "e" * 32 + ".png"
    (img_dir / name).write_bytes(PNG_MAGIC + b"body")
    out = chat_images.to_data_urls([chat_images.CHAT_IMAGE_URL_PREFIX + name])
    assert len(out) == 1
    assert out[0].startswith("data:image/png;base64,")
    assert base64.b64decode(out[0].split(",", 1)[1]) == PNG_MAGIC + b"body"


def test_to_data_urls_skips_missing_files(img_dir):
    """文件缺失的图片被跳过（不抛异常）"""
    assert chat_images.to_data_urls([chat_images.CHAT_IMAGE_URL_PREFIX + "f" * 32 + ".png"]) == []


def test_to_data_urls_handles_empty_and_plain_input(img_dir):
    """空输入 / 非站内 URL 前缀都不应崩"""
    assert chat_images.to_data_urls([]) == []
    assert chat_images.to_data_urls(None) == []
    assert chat_images.to_data_urls(["not-a-url"]) == []


def test_to_data_urls_accepts_bare_filename(img_dir):
    """裸文件名（无 URL 前缀）也能定位"""
    name = "9" * 32 + ".png"
    (img_dir / name).write_bytes(PNG_MAGIC)
    out = chat_images.to_data_urls([name])
    assert len(out) == 1 and out[0].startswith("data:image/png;base64,")


# ---------- 常量契约 ----------

def test_ext_mime_covers_all_allowed_types():
    """MIME ↔ 扩展名映射双向一致"""
    assert set(chat_images.EXT_MIME) == set(chat_images.ALLOWED_MIME.values())
    assert chat_images.EXT_MIME["png"] == "image/png"
    assert chat_images.EXT_MIME["jpg"] == "image/jpeg"
    assert chat_images.EXT_MIME["webp"] == "image/webp"
    assert chat_images.EXT_MIME["gif"] == "image/gif"
