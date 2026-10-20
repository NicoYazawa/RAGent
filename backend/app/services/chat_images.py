"""问答图片服务 — 多模态消息图片的解析、落盘、读取与 data URL 转换

图片统一存于 data/uploads/chat_images/{uuid}.{ext}，chat_message.images 存站内 URL 数组；
AskRequest.images 接受两种形式：
- data URL：data:image/png;base64,…（新上传，前端已压缩）
- 站内 URL：/api/chat/images/{name}（重新生成场景复用已落盘图片）
"""
import base64
import binascii
import re
import uuid
from pathlib import Path

from ..config import UPLOAD_DIR, settings

CHAT_IMAGE_DIR = UPLOAD_DIR / "chat_images"
CHAT_IMAGE_URL_PREFIX = "/api/chat/images/"

# MIME 白名单 → 落盘扩展名
ALLOWED_MIME: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
# 扩展名 → MIME（静态服务响应头用）
EXT_MIME = {ext: mime for mime, ext in ALLOWED_MIME.items()}

# 各格式文件头（幻数校验，防伪造 MIME 上传非图片内容）
_MAGIC: dict[str, bytes] = {
    "image/png": b"\x89PNG",
    "image/jpeg": b"\xff\xd8",
    "image/gif": b"GIF8",
    "image/webp": b"RIFF",
}

_DATA_URL_RE = re.compile(r"^data:(image/(?:png|jpeg|webp|gif));base64,(.+)$", re.DOTALL)
_SAFE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(png|jpg|webp|gif)$")


def image_path(name: str) -> str | None:
    """站内文件名 → 落盘路径（非法名或不存在返回 None，防路径穿越）"""
    if not _SAFE_NAME_RE.match(name):
        return None
    path = CHAT_IMAGE_DIR / name
    return str(path) if path.is_file() else None


def save_images(items: list[str]) -> list[str]:
    """解析前端提交的图片引用 → 落盘 → 返回站内 URL 列表"""
    if not items:
        return []
    if len(items) > settings.chat_image_max_count:
        raise ValueError(f"单条消息最多附带 {settings.chat_image_max_count} 张图片")
    urls: list[str] = []
    for it in items:
        if it.startswith(CHAT_IMAGE_URL_PREFIX):
            # 已落盘图片（重答场景）：校验后直接复用，不重复保存
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
    """站内 URL 列表 → base64 data URL 列表（发给视觉模型；缺失文件跳过）"""
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
