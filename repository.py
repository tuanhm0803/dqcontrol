"""Truy vấn đọc dùng chung: tìm theo từ khóa, danh mục chi nhánh (bảng lỗi DQ) và mã quy tắc (dq_rules)."""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from models import DQError, DQRule


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def keyword_condition(keyword: str, *columns):
    pattern = f"%{escape_like(keyword)}%"
    return or_(*(col.ilike(pattern, escape="\\") for col in columns))


def list_branches(db: Session) -> list[tuple[str, str]]:
    """Danh mục (mã, tên) chi nhánh = các chi nhánh xuất hiện trong bảng lỗi DQ."""
    rows = db.execute(select(DQError.branch_code, DQError.branch_name).distinct().order_by(DQError.branch_code))
    return [tuple(r) for r in rows]


def list_rules(db: Session, active_only: bool = True) -> list[tuple[str, str]]:
    """Danh mục (mã, tên) quy tắc DQ do admin quản lý (bảng dq_rules). Mặc định chỉ mã đang dùng:
    dùng cho form, file mẫu và kiểm tra yêu cầu loại trừ mới."""
    stmt = select(DQRule.rule_code, DQRule.rule_name).order_by(DQRule.rule_code)
    if active_only:
        stmt = stmt.where(DQRule.is_active.is_(True))
    return [tuple(r) for r in db.execute(stmt)]


def rule_names(db: Session) -> dict[str, str]:
    """Mã -> tên của mọi quy tắc (kể cả ngừng dùng) để hiển thị yêu cầu cũ."""
    return dict(list_rules(db, active_only=False))
