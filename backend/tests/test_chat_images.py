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
    """Point the storage directory at tmp_path so the real data/uploads is never touched."""
    d = tmp_path / "chat_images"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(chat_images, "CHAT_IMAGE_DIR", d)
    return d


def _data_url(mime: str, blob: bytes) -> str:
    return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"


# ---------- image_path: path traversal defenses ----------

@pytest.mark.parametrize(
    "name",
    [
        "../../../etc/passwd",
        "..%2f..%2fetc%2fpasswd",
        "not-a-uuid.png",
        "0123456789abcdef0123456789abcdeg.png",  # 33 hex chars, invalid
        "0123456789abcdef0123456789abcde.exe",  # extension not on the allowlist
        "",
    ],
)
def test_image_path_rejects_unsafe_names(name, img_dir):
    """Any illegal file name returns None (blocks path traversal and arbitrary file reads)."""
    assert chat_images.image_path(name) is None


def test_image_path_returns_existing_file(img_dir):
    """A legal, existing file returns its absolute path."""
    (img_dir / ("a" * 32 + ".png")).write_bytes(PNG_MAGIC)
    p = chat_images.image_path("a" * 32 + ".png")
    assert p is not None and p.endswith(".png")


def test_image_path_missing_file_returns_none(img_dir):
    """Legal name but missing file -> None."""
    assert chat_images.image_path("b" * 32 + ".png") is None


def test_image_path_rejects_traversal_to_existing_file(tmp_path, monkeypatch):
    """Traversal to a file that **actually exists** must still be rejected (blocks arbitrary file reads).

    This is the core of the security regression: "the file does not exist" alone does not prove
    the defense works — an attacker only has to create the target file first. This test places a
    real file there, and image_path would return it once the allowlist check is removed.
    """
    d = tmp_path / "chat_images"
    d.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG_MAGIC)
    monkeypatch.setattr(chat_images, "CHAT_IMAGE_DIR", d)

    traversal = os.path.relpath(outside, d).replace("\\", "/")
    assert outside.is_file()  # Precondition: the target really exists
    assert chat_images.image_path(traversal) is None


# ---------- save_images: four defenses ----------

def test_save_images_empty_list_returns_empty(img_dir):
    """No images -> empty list."""
    assert chat_images.save_images([]) == []


def test_save_images_persists_valid_png(img_dir):
    """A valid PNG is stored and returned as an in-app URL."""
    urls = chat_images.save_images([_data_url("image/png", PNG_MAGIC + b"body")])
    assert len(urls) == 1
    assert urls[0].startswith(chat_images.CHAT_IMAGE_URL_PREFIX)
    name = urls[0].removeprefix(chat_images.CHAT_IMAGE_URL_PREFIX)
    assert (img_dir / name).is_file()


def test_save_images_rejects_mime_content_mismatch(img_dir):
    """Magic-number check: declared png but the bytes are not png -> rejected."""
    with pytest.raises(ValueError, match="内容与声明格式不符"):
        chat_images.save_images([_data_url("image/png", b"GIF89a" + b"x" * 50)])


def test_save_images_rejects_unsupported_format(img_dir):
    """A MIME type outside the allowlist is rejected outright."""
    with pytest.raises(ValueError, match="格式不支持"):
        chat_images.save_images([_data_url("image/svg+xml", b"<svg/>")])


def test_save_images_rejects_bad_base64(img_dir):
    """Invalid base64 -> rejected."""
    with pytest.raises(ValueError, match="解码失败"):
        chat_images.save_images(["data:image/png;base64,!!!not-base64!!!"])


def test_save_images_enforces_count_limit(img_dir, monkeypatch):
    """Per-message image count limit (4 by default)."""
    monkeypatch.setattr(chat_images.settings, "chat_image_max_count", 2)
    urls = [_data_url("image/png", PNG_MAGIC + bytes([i])) for i in range(3)]
    with pytest.raises(ValueError, match="最多附带"):
        chat_images.save_images(urls)


def test_save_images_enforces_size_limit(img_dir, monkeypatch):
    """Per-image size limit."""
    monkeypatch.setattr(chat_images.settings, "chat_image_max_bytes", 10)
    with pytest.raises(ValueError, match="不能超过"):
        chat_images.save_images([_data_url("image/png", PNG_MAGIC + b"x" * 100)])


def test_save_images_reuses_existing_site_url(img_dir):
    """An in-app URL (regeneration) is validated and reused instead of being stored again."""
    name = "c" * 32 + ".jpg"
    (img_dir / name).write_bytes(JPEG_MAGIC)
    url = chat_images.CHAT_IMAGE_URL_PREFIX + name
    assert chat_images.save_images([url]) == [url]


def test_save_images_rejects_stale_site_url(img_dir):
    """An in-app URL pointing at a missing file -> rejected."""
    url = chat_images.CHAT_IMAGE_URL_PREFIX + ("d" * 32 + ".png")
    with pytest.raises(ValueError, match="图片引用无效"):
        chat_images.save_images([url])


# ---------- to_data_urls ----------

def test_to_data_urls_converts_existing_files(img_dir):
    """In-app URL -> base64 data URL (fed to the vision model)."""
    name = "e" * 32 + ".png"
    (img_dir / name).write_bytes(PNG_MAGIC + b"body")
    out = chat_images.to_data_urls([chat_images.CHAT_IMAGE_URL_PREFIX + name])
    assert len(out) == 1
    assert out[0].startswith("data:image/png;base64,")
    assert base64.b64decode(out[0].split(",", 1)[1]) == PNG_MAGIC + b"body"


def test_to_data_urls_skips_missing_files(img_dir):
    """Images whose file is missing are skipped without raising."""
    assert chat_images.to_data_urls([chat_images.CHAT_IMAGE_URL_PREFIX + "f" * 32 + ".png"]) == []


def test_to_data_urls_handles_empty_and_plain_input(img_dir):
    """Empty input and values without the in-app prefix must not crash."""
    assert chat_images.to_data_urls([]) == []
    assert chat_images.to_data_urls(None) == []
    assert chat_images.to_data_urls(["not-a-url"]) == []


def test_to_data_urls_accepts_bare_filename(img_dir):
    """A bare file name without the URL prefix still resolves."""
    name = "9" * 32 + ".png"
    (img_dir / name).write_bytes(PNG_MAGIC)
    out = chat_images.to_data_urls([name])
    assert len(out) == 1 and out[0].startswith("data:image/png;base64,")


# ---------- Constant contracts ----------

def test_ext_mime_covers_all_allowed_types():
    """The MIME <-> extension mapping is consistent in both directions."""
    assert set(chat_images.EXT_MIME) == set(chat_images.ALLOWED_MIME.values())
    assert chat_images.EXT_MIME["png"] == "image/png"
    assert chat_images.EXT_MIME["jpg"] == "image/jpeg"
    assert chat_images.EXT_MIME["webp"] == "image/webp"
    assert chat_images.EXT_MIME["gif"] == "image/gif"
