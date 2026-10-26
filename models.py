"""SQLAlchemy model và Pydantic schema: lỗi DQ, yêu cầu ngoại lệ, phân quyền, nhật ký."""
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Date, DateTime, Identity, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from config import settings


# --------------------------------------------------------------------------- #
# Enum dùng chung
# --------------------------------------------------------------------------- #
class Severity(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Status(str, Enum):
    PENDING = "Chưa xử lý"
    IN_PROGRESS = "Đang xử lý"
    DONE = "Hoàn thành"
    EXCEPTION_PENDING = "Chờ duyệt ngoại lệ"
    EXCEPTION_APPROVED = "Ngoại lệ đã duyệt"


# Trạng thái người dùng tự cập nhật được (2 trạng thái ngoại lệ chỉ đi qua luồng phê duyệt)
MANUAL_STATUSES = (Status.PENDING, Status.IN_PROGRESS, Status.DONE)
# Trạng thái được phép gửi yêu cầu ngoại lệ
EXCEPTION_ELIGIBLE_STATUSES = (Status.PENDING, Status.IN_PROGRESS)
# Trạng thái đã đóng -> có Ngày xử lý / phê duyệt ngoại lệ
CLOSED_STATUSES = (Status.DONE, Status.EXCEPTION_APPROVED)
EXCEPTION_STATUSES = (Status.EXCEPTION_PENDING, Status.EXCEPTION_APPROVED)


class ExceptionStatus(str, Enum):
    PENDING = "Chờ duyệt"
    APPROVED = "Đã duyệt"
    REJECTED = "Từ chối"
    CANCELLED = "Đã hủy"
    REVOKED = "Đã thu hồi"


class Role(str, Enum):
    ADMIN = "admin"
    APPROVER = "approver"
    BRANCH_USER = "branch_user"


ROLE_LABELS = {
    Role.ADMIN: "Quản trị DQ",
    Role.APPROVER: "Người phê duyệt",
    Role.BRANCH_USER: "User Chi nhánh",
}


# --------------------------------------------------------------------------- #
# SQLAlchemy model
# --------------------------------------------------------------------------- #
class Base(DeclarativeBase):
    pass


def _schema(name: str | None) -> dict:
    return {"schema": name} if name else {}


class DQError(Base):
    """Bảng lỗi DQ. Đổi tên cột (tham số đầu của mapped_column) nếu bảng thật đặt tên khác."""
    __tablename__ = settings.DQ_TABLE_NAME
    __table_args__ = _schema(settings.DQ_TABLE_SCHEMA)

    id: Mapped[int] = mapped_column("id", Integer, Identity(), primary_key=True)
    branch_code: Mapped[str] = mapped_column("branch_code", String(20), index=True)
    branch_name: Mapped[str] = mapped_column("branch_name", String(200))
    rule_code: Mapped[str] = mapped_column("rule_code", String(50), index=True)
    description: Mapped[str] = mapped_column("description", String(1000))
    severity: Mapped[str] = mapped_column("severity", String(10), index=True)
    detected_date: Mapped[date] = mapped_column("detected_date", Date, index=True)
    status: Mapped[str] = mapped_column("status", String(30), index=True)
    owner: Mapped[str | None] = mapped_column("owner", String(200), nullable=True)
    # Ngày xử lý (Hoàn thành) / ngày phê duyệt ngoại lệ, và người thực hiện
    resolved_date: Mapped[date | None] = mapped_column("resolved_date", Date, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column("resolved_by", String(100), nullable=True)


class ExceptionRequest(Base):
    __tablename__ = "dq_exception_requests"
    __table_args__ = _schema(settings.APP_TABLE_SCHEMA)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    error_id: Mapped[int] = mapped_column(Integer, index=True)
    branch_code: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(String(2000))
    previous_status: Mapped[str] = mapped_column(String(30))  # để trả lại khi từ chối / hủy / thu hồi
    status: Mapped[str] = mapped_column(String(20), index=True)
    requested_by: Mapped[str] = mapped_column(String(100), index=True)
    requested_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime)
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)


class UserPermission(Base):
    """Phân quyền nội bộ: ghi đè quyền lấy từ nhóm AD."""
    __tablename__ = "dq_user_permissions"
    __table_args__ = _schema(settings.APP_TABLE_SCHEMA)

    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[str] = mapped_column(String(20))
    branch_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    all_branches: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    updated_by: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "dq_audit_log"
    __table_args__ = _schema(settings.APP_TABLE_SCHEMA)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    username: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(30), index=True)
    target: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(2000), nullable=True)


# Bảng do ứng dụng sở hữu (tự tạo khi khởi động nếu chưa có)
APP_TABLES = [ExceptionRequest.__table__, UserPermission.__table__, AuditLog.__table__]


# --------------------------------------------------------------------------- #
# Pydantic schema
# --------------------------------------------------------------------------- #
class DQErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    branch_code: str
    branch_name: str
    rule_code: str
    description: str
    severity: str
    detected_date: date
    status: str
    owner: str | None = None
    resolved_date: date | None = None
    resolved_by: str | None = None


# Thứ tự & tiêu đề cột khi xuất Excel/CSV
EXPORT_COLUMNS: dict[str, str] = {
    "branch_code": "Mã chi nhánh",
    "branch_name": "Tên chi nhánh",
    "rule_code": "Mã quy tắc DQ",
    "description": "Tên lỗi / Mô tả",
    "severity": "Mức độ",
    "detected_date": "Ngày phát hiện",
    "status": "Trạng thái",
    "owner": "Người phụ trách",
    "resolved_date": "Ngày xử lý / Phê duyệt NL",
    "resolved_by": "Người xử lý / Phê duyệt",
}


class ExceptionRequestOut(BaseModel):
    """Yêu cầu ngoại lệ kèm thông tin lỗi DQ liên quan."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    error_id: int
    branch_code: str
    reason: str
    previous_status: str
    status: str
    requested_by: str
    requested_by_name: str | None = None
    requested_at: datetime
    decided_by: str | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    # Từ bảng lỗi DQ
    branch_name: str | None = None
    rule_code: str | None = None
    description: str | None = None
    severity: str | None = None


class UserPermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    username: str
    display_name: str | None = None
    role: Role
    branch_code: str | None = None
    all_branches: bool
    is_active: bool
    note: str | None = None
    updated_by: str
    updated_at: datetime

    @property
    def role_label(self) -> str:
        return ROLE_LABELS[self.role]


class DQFilter(BaseModel):
    branch_code: str | None = None
    severity: Severity | None = None
    status: Status | None = None
    keyword: str | None = None
    date_from: date | None = None
    date_to: date | None = None

    def to_query_params(self) -> dict[str, str]:
        """Bộ lọc dạng query string (bỏ giá trị rỗng) để giữ khi phân trang / xuất file."""
        params = {}
        for key, value in self.model_dump(exclude_none=True).items():
            params[key] = value.value if isinstance(value, Enum) else str(value)
        return params


class DQStats(BaseModel):
    total: int = 0
    by_severity: dict[str, int] = {}
    by_status: dict[str, int] = {}
    top_branches: list[tuple[str, str, int]] = []  # (mã CN, tên CN, số lỗi)


class PagedResult(BaseModel):
    items: list[DQErrorOut]
    total: int
    page: int
    page_size: int
    pages: int


class ADIdentity(BaseModel):
    """Thông tin lấy từ AD lúc đăng nhập (lưu trong session)."""
    username: str
    display_name: str
    email: str | None = None
    branch_code: str | None = None
    groups: list[str] = []


class CurrentUser(BaseModel):
    """Người dùng hiệu lực = thông tin AD + phân quyền (AD group hoặc phân quyền nội bộ)."""
    username: str
    display_name: str
    email: str | None = None
    role: Role
    branch_code: str | None = None
    all_branches: bool = False
    groups: list[str] = []
    permission_source: str = "AD"  # "AD" | "Nội bộ"

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def can_edit(self) -> bool:
        """Cập nhật trạng thái & gửi yêu cầu ngoại lệ."""
        return self.role in (Role.ADMIN, Role.BRANCH_USER)

    @property
    def can_approve(self) -> bool:
        return self.role in (Role.ADMIN, Role.APPROVER)

    @property
    def role_label(self) -> str:
        return ROLE_LABELS[self.role]

    def can_access(self, branch_code: str | None) -> bool:
        return self.all_branches or (branch_code is not None and branch_code == self.branch_code)

    def scope(self, filters: DQFilter) -> DQFilter:
        """Xem toàn hệ thống: giữ nguyên bộ lọc. Ngược lại: luôn ép về chi nhánh của user."""
        if self.all_branches:
            return filters
        return filters.model_copy(update={"branch_code": self.branch_code})
