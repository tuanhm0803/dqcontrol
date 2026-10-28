"""Truy vấn đọc: bảng lỗi DQ (tìm kiếm, lọc, thống kê) và danh mục chi nhánh / quy tắc."""
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models import DQError, DQErrorOut, DQFilter, DQRule, DQStats


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def keyword_condition(keyword: str, *columns):
    pattern = f"%{escape_like(keyword)}%"
    return or_(*(col.ilike(pattern, escape="\\") for col in columns))


def _conditions(f: DQFilter) -> list:
    c = DQError
    conds = []
    if f.branch_code:
        conds.append(c.branch_code == f.branch_code)
    if f.severity:
        conds.append(c.severity == f.severity.value)
    if f.status:
        conds.append(c.status == f.status.value)
    if f.date_from:
        conds.append(c.detected_date >= f.date_from)
    if f.date_to:
        conds.append(c.detected_date <= f.date_to)
    if f.keyword:
        conds.append(keyword_condition(f.keyword, c.branch_code, c.branch_name, c.rule_code, c.description, c.owner))
    return conds


def _ordered(stmt):
    return stmt.order_by(DQError.detected_date.desc(), DQError.id.desc())


def search_errors(db: Session, f: DQFilter, page: int, page_size: int) -> tuple[list[DQErrorOut], int]:
    conds = _conditions(f)
    total = db.scalar(select(func.count()).select_from(DQError).where(*conds)) or 0
    stmt = _ordered(select(DQError).where(*conds)).offset((page - 1) * page_size).limit(page_size)
    return [DQErrorOut.model_validate(r) for r in db.scalars(stmt)], total


def fetch_errors(db: Session, f: DQFilter, limit: int) -> list[DQErrorOut]:
    stmt = _ordered(select(DQError).where(*_conditions(f))).limit(limit)
    return [DQErrorOut.model_validate(r) for r in db.scalars(stmt)]


def error_stats(db: Session, f: DQFilter) -> DQStats:
    conds = _conditions(f)
    c = DQError
    by_sev = db.execute(select(c.severity, func.count()).where(*conds).group_by(c.severity)).all()
    by_status = db.execute(select(c.status, func.count()).where(*conds).group_by(c.status)).all()
    by_branch = db.execute(
        select(c.branch_code, c.branch_name, func.count()).where(*conds).group_by(c.branch_code, c.branch_name)
    ).all()
    return DQStats(
        total=sum(n for _, n in by_sev),
        by_severity=dict(by_sev),
        by_status=dict(by_status),
        top_branches=sorted((tuple(r) for r in by_branch), key=lambda b: b[2], reverse=True)[:5],
    )


def list_branches(db: Session) -> list[tuple[str, str]]:
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
