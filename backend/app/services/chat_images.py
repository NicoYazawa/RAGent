"""Q&A image service — parse, store, read and convert multimodal message images.

Images live under data/uploads/chat_images/{uuid}.{ext} and chat_message.images holds an
array of in-app URLs. AskRequest.images accepts two forms:
- data URL: data:image/png;base64,... (fresh upload, compressed by the frontend)
- in-app URL: /api/chat/images/{name} (regeneration reuses an image already on disk)
"""
import base64
import binascii
import re
import uuid
from pathlib import Path

from ..config import UPLOAD_DIR, settings

CHAT_IMAGE_DIR = UPLOAD_DIR / "chat_images"
CHAT_IMAGE_URL_PREFIX = "/api/chat/images/"

# MIME allowlist -> stored extension
ALLOWED_MIME: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
# Extension -> MIME (used for the static endpoint's response header)
EXT_MIME = {ext: mime for mime, ext in ALLOWED_MIME.items()}

# File headers per format (magic-number check, so a forged MIME cannot upload non-image data)
_MAGIC: dict[str, bytes] = {
    "image/png": b"\x89PNG",
    "image/jpeg": b"\xff\xd8",
    "image/gif": b"GIF8",
    "image/webp": b"RIFF",
}

_DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg|webp|gif));base64,(.+)$", re.DOTALL)
_SAFE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")


def image_path(name: str) -> str | None:
    """In-app file name -> path on disk (None for an illegal name or a missing file, which
    also blocks path traversal)."""
    if not _SAFE_NAME_RE.match(name):
        return None
    path = CHAT_IMAGE_DIR / name
    return str(path) if path.is_file() else None


def save_images(items: list[str]) -> list[str]:
    """Parse the image references submitted by the frontend -> store them -> return in-app URLs."""
    if not items:
        return []
    if len(items) > settings.chat_image_max_count:
        raise ValueError(f"单条消息最多附带 {settings.chat_image_max_count} 张图片")
    urls: list[str] = []
    for it in items:
        if it.startswith(CHAT_IMAGE_URL_PREFIX):
            # Already stored (regeneration): validate and reuse instead of saving again
            name = it[len(CHAT_IMAGE_URL_PREFIX):]
            if image_path(name) is None:
                raise ValueError("图片引用无效或已失效")
            urls.append(CHAT_IMAGE_URL_PREFIX + name)
            continue
        m = _DATA_URL_RE.match(it.strip())
        if not m:
            raise ValueError("图片格式不支持（允许：png / jpeg / webp / gif）")
        mime, b64 = m.group(1), m.group(2)
        try:
            blob = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError) as e:
            raise ValueError("图片数据解码失败") from e
        if len(blob) > settings.chat_image_max_bytes:
            raise ValueError(f"单张图片不能超过 {settings.chat_image_max_bytes // (1024 * 1024)}MB")
        if not blob.startswith(_MAGIC[mime]):
            raise ValueError("图片内容与声明格式不符")
        CHAT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.{ALLOWED_MIME[mime]}"
        (CHAT_IMAGE_DIR / name).write_bytes(blob)
        urls.append(CHAT_IMAGE_URL_PREFIX + name)
    return urls


def to_data_urls(urls: list[str]) -> list[str]:
    """In-app URL list -> base64 data URL list (sent to the vision model; missing files are skipped)."""
    out: list[str] = []
    for u in urls or []:
        name = u[len(CHAT_IMAGE_URL_PREFIX):] if u.startswith(CHAT_IMAGE_URL_PREFIX) else u
        path = image_path(name)
        if path is None:
            continue
        blob = Path(path).read_bytes()
        ext = name.rsplit(".", 1)[-1]
        out.append(f"data:{EXT_MIME[ext]};base64,{base64.b64encode(blob).decode('ascii')}")
    return out
