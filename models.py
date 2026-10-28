"""SQLAlchemy model và Pydantic schema: lỗi DQ, danh mục quy tắc, yêu cầu loại trừ, phân quyền, nhật ký."""
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import NamedTuple

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


# Trạng thái admin cập nhật được trên dashboard
MANUAL_STATUSES = (Status.PENDING, Status.IN_PROGRESS, Status.DONE)


class ExclusionStatus(str, Enum):
    PENDING_MANAGER = "Chờ LĐ phòng duyệt"
    PENDING_BUSINESS = "Chờ duyệt nghiệp vụ"
    PENDING_DQ = "Chờ duyệt QTDL"
    APPROVED = "Đã duyệt"
    REJECTED = "Từ chối"
    CANCELLED = "Đã hủy"
    REVOKED = "Đã thu hồi"


class Role(str, Enum):
    """Thứ tự khai báo = thứ tự cột ma trận quyền. Giá trị "approver" giữ nguyên từ bản 1 cấp (nay là Phê duyệt QTDL)."""
    ADMIN = "admin"
    APPROVER = "approver"
    BUSINESS_APPROVER = "business_approver"
    BRANCH_MANAGER = "branch_manager"
    BRANCH_USER = "branch_user"


ROLE_LABELS = {
    Role.ADMIN: "Quản trị DQ",
    Role.APPROVER: "Phê duyệt QTDL",
    Role.BUSINESS_APPROVER: "Phê duyệt nghiệp vụ",
    Role.BRANCH_MANAGER: "Lãnh đạo phòng ban",
    Role.BRANCH_USER: "User Chi nhánh",
}
# Vai trò mặc định xem toàn hệ thống (khi lấy quyền theo nhóm AD)
HQ_ROLES = (Role.ADMIN, Role.APPROVER, Role.BUSINESS_APPROVER)


class ApprovalLevel(NamedTuple):
    """Một cấp phê duyệt: trạng thái chờ ở cấp này, trạng thái sau khi duyệt, tiền tố cột lưu người / ngày duyệt."""
    key: str
    label: str
    pending: ExclusionStatus
    next: ExclusionStatus
    role: Role


# Luồng phê duyệt tuần tự: LĐ phòng ban -> Nghiệp vụ -> QTDL. Từ chối ở cấp nào thì kết thúc ở cấp đó.
APPROVAL_LEVELS = (
    ApprovalLevel("manager", "LĐ phòng ban", ExclusionStatus.PENDING_MANAGER, ExclusionStatus.PENDING_BUSINESS,
                  Role.BRANCH_MANAGER),
    ApprovalLevel("business", "Nghiệp vụ", ExclusionStatus.PENDING_BUSINESS, ExclusionStatus.PENDING_DQ,
                  Role.BUSINESS_APPROVER),
    ApprovalLevel("dq", "QTDL", ExclusionStatus.PENDING_DQ, ExclusionStatus.APPROVED, Role.APPROVER),
)
LEVEL_BY_STATUS = {lv.pending.value: lv for lv in APPROVAL_LEVELS}
PENDING_STATUSES = tuple(lv.pending.value for lv in APPROVAL_LEVELS)


class ExclusionSource(str, Enum):
    MANUAL = "Nhập tay"
    EXCEL = "Excel"


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
    # Ngày xử lý (Hoàn thành) và người thực hiện
    resolved_date: Mapped[date | None] = mapped_column("resolved_date", Date, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column("resolved_by", String(100), nullable=True)


class DQRule(Base):
    """Danh mục mã quy tắc DQ do admin quản lý (thêm / sửa / upload thay thế toàn bộ)."""
    __tablename__ = "dq_rules"
    __table_args__ = _schema(settings.APP_TABLE_SCHEMA)

    rule_code: Mapped[str] = mapped_column(String(50), primary_key=True)  # chữ hoa
    rule_name: Mapped[str] = mapped_column(String(500))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # ngừng dùng: không khai báo mới được
    updated_by: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class ExclusionRequest(Base):
    """Yêu cầu loại trừ một bản ghi khỏi một quy tắc DQ (không liên kết tới bảng lỗi DQ)."""
    __tablename__ = "dq_exclusion_requests"
    __table_args__ = _schema(settings.APP_TABLE_SCHEMA)

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    branch_code: Mapped[str] = mapped_column(String(20), index=True)
    rule_code: Mapped[str] = mapped_column(String(50), index=True)
    record_key: Mapped[str] = mapped_column(String(100), index=True)  # CIF / số TK / số HĐ...
    reason: Mapped[str] = mapped_column(String(2000))
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)  # bắt buộc khi tạo; NULL (dữ liệu cũ) = vô hạn
    source: Mapped[str] = mapped_column(String(20))  # ExclusionSource
    upload_file: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(30), index=True)
    requested_by: Mapped[str] = mapped_column(String(100), index=True)
    requested_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    # Người / ngày duyệt từng cấp (tiền tố = ApprovalLevel.key)
    manager_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    manager_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    manager_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    business_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    business_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    business_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dq_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    dq_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    dq_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Thao tác kết thúc yêu cầu: duyệt cấp cuối / từ chối / hủy / thu hồi
    decided_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    decided_by_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    decision_note: Mapped[str | None] = mapped_column(String(4000), nullable=True)  # nhật ký ghi chú các cấp


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
APP_TABLES = [DQRule.__table__, ExclusionRequest.__table__, UserPermission.__table__, AuditLog.__table__]


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
    "resolved_date": "Ngày xử lý",
    "resolved_by": "Người xử lý",
}


class ExclusionRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    branch_code: str
    rule_code: str
    record_key: str
    reason: str
    valid_to: date | None = None
    source: str
    upload_file: str | None = None
    status: str
    requested_by: str
    requested_by_name: str | None = None
    requested_at: datetime
    manager_by: str | None = None
    manager_by_name: str | None = None
    manager_at: datetime | None = None
    business_by: str | None = None
    business_by_name: str | None = None
    business_at: datetime | None = None
    dq_by: str | None = None
    dq_by_name: str | None = None
    dq_at: datetime | None = None
    decided_by: str | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    rule_name: str | None = None  # từ danh mục quy tắc (dq_rules), không lưu trong bảng này

    def approvals(self) -> list[tuple[ApprovalLevel, str | None, datetime | None]]:
        """(cấp, người duyệt, ngày duyệt) theo thứ tự cấp - dùng để hiển thị tiến trình."""
        return [(lv, getattr(self, f"{lv.key}_by_name") or getattr(self, f"{lv.key}_by"), getattr(self, f"{lv.key}_at"))
                for lv in APPROVAL_LEVELS]


# Cột file xuất yêu cầu loại trừ đã duyệt (6 cột đầu cùng tiêu đề / thứ tự với file mẫu upload)
EXCLUSION_EXPORT_COLUMNS: dict[str, str] = {
    "branch_code": "Mã chi nhánh",
    "rule_code": "Mã quy tắc DQ",
    "rule_name": "Tên quy tắc DQ",
    "record_key": "Mã bản ghi",
    "reason": "Lý do loại trừ",
    "valid_to": "Hiệu lực đến",
    "id": "Mã yêu cầu",
    "requested_by": "Người gửi",
    "requested_at": "Ngày gửi",
    "manager_by": "LĐ phòng ban duyệt",
    "manager_at": "Ngày LĐ phòng duyệt",
    "business_by": "Nghiệp vụ duyệt",
    "business_at": "Ngày nghiệp vụ duyệt",
    "dq_by": "QTDL duyệt",
    "dq_at": "Ngày QTDL duyệt",
    "decision_note": "Ghi chú duyệt",
}


class DQRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rule_code: str
    rule_name: str
    is_active: bool
    updated_by: str
    updated_at: datetime


@dataclass
class ExclusionFilter:
    """Bộ lọc danh sách / file xuất yêu cầu loại trừ."""
    branch_code: str | None = None
    rule_code: str | None = None
    status: str | None = None
    keyword: str | None = None
    decided_from: date | None = None  # ngày kết thúc yêu cầu (với Đã duyệt = ngày QTDL duyệt)
    decided_to: date | None = None
    active_only: bool = False  # chỉ yêu cầu còn hiệu lực (valid_to trống hoặc >= hôm nay)


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
    def can_view_errors(self) -> bool:
        """Xem dashboard / API / xuất file lỗi DQ (cấp chi nhánh không xem)."""
        return self.role in HQ_ROLES

    @property
    def can_update_status(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def can_request(self) -> bool:
        """Khai báo / upload yêu cầu loại trừ."""
        return self.role in (Role.ADMIN, Role.BRANCH_USER)

    @property
    def approval_levels(self) -> tuple[ApprovalLevel, ...]:
        """Các cấp được duyệt: admin mọi cấp, vai trò phê duyệt đúng cấp của mình."""
        return tuple(lv for lv in APPROVAL_LEVELS if self.role in (Role.ADMIN, lv.role))

    @property
    def can_approve(self) -> bool:
        return bool(self.approval_levels)

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
