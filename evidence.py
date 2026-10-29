"""File bằng chứng của yêu cầu loại trừ: kiểm tra (số lượng, dung lượng, loại file theo NỘI DUNG) và lưu trên đĩa.

Lưu tại settings.EVIDENCE_DIR/<request_id>/<tên ngẫu nhiên><đuôi chuẩn>; tên gốc chỉ lưu trong DB để hiển thị,
không bao giờ dùng làm đường dẫn. Chỉ nhận ảnh JPG / PNG / GIF / WEBP và PDF.
"""
import secrets
from pathlib import Path
from typing import NamedTuple

from config import settings

# content type -> đuôi file lưu trên đĩa
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
ACCEPT_ATTR = ".jpg,.jpeg,.png,.gif,.webp,.pdf,image/jpeg,image/png,image/gif,image/webp,application/pdf"


class EvidenceFile(NamedTuple):
    """Một file đã kiểm tra hợp lệ, sẵn sàng lưu."""
    file_name: str
    content_type: str
    data: bytes


def max_bytes() -> int:
    return settings.EVIDENCE_MAX_MB * 1024 * 1024


def sniff_type(data: bytes) -> str | None:
    """Loại file theo chữ ký đầu file (magic bytes); None nếu không thuộc loại được nhận."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def safe_name(name: str) -> str:
    """Tên gốc để hiển thị: bỏ phần thư mục, ký tự điều khiển; tối đa 255 ký tự."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '<>:"|?*').strip() or "file"
    return base[-255:]


def check_files(files: list[tuple[str, bytes]]) -> list[EvidenceFile] | str:
    """files: (tên gốc, nội dung - đọc tối đa max_bytes()+1 byte). Trả danh sách hợp lệ hoặc chuỗi lý do lỗi."""
    if len(files) > settings.EVIDENCE_MAX_FILES:
        return f"tối đa {settings.EVIDENCE_MAX_FILES} file bằng chứng mỗi dòng (đang chọn {len(files)})"
    checked = []
    for name, data in files:
        shown = safe_name(name)
        if not data:
            return f"file '{shown}' rỗng"
        if len(data) > max_bytes():
            return f"file '{shown}' vượt quá {settings.EVIDENCE_MAX_MB} MB"
        content_type = sniff_type(data)
        if content_type is None:
            return f"file '{shown}' không phải ảnh (JPG, PNG, GIF, WEBP) hoặc PDF"
        checked.append(EvidenceFile(shown, content_type, data))
    return checked


def new_stored_name(content_type: str) -> str:
    return secrets.token_hex(16) + ALLOWED_TYPES[content_type]


def path_for(request_id: int, stored_name: str) -> Path:
    # stored_name do app sinh (hex + đuôi chuẩn), không chứa đường dẫn
    return settings.EVIDENCE_DIR / str(int(request_id)) / Path(stored_name).name


def save(request_id: int, stored_name: str, data: bytes) -> Path:
    path = path_for(request_id, stored_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def remove(paths: list[Path]) -> None:
    """Dọn file đã ghi khi giao dịch DB thất bại."""
    for path in paths:
        path.unlink(missing_ok=True)
