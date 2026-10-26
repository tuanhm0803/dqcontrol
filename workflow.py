"""Nghiệp vụ: cập nhật trạng thái lỗi DQ, luồng phê duyệt ngoại lệ, nhật ký hệ thống.

Luồng ngoại lệ:
    Chưa xử lý / Đang xử lý --(user chi nhánh / admin gửi yêu cầu)--> Chờ duyệt ngoại lệ
    Chờ duyệt ngoại lệ --(người phê duyệt / admin duyệt)--> Ngoại lệ đã duyệt (ghi ngày phê duyệt)
    Chờ duyệt ngoại lệ --(từ chối / người gửi hủy)--> trạng thái trước khi gửi
    Ngoại lệ đã duyệt --(admin thu hồi)--> trạng thái trước khi gửi
Người gửi yêu cầu không được tự phê duyệt yêu cầu của chính mình (maker-checker).
"""
import logging
from datetime import date, datetime
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import settings
from models import (EXCEPTION_ELIGIBLE_STATUSES, EXCEPTION_STATUSES, MANUAL_STATUSES, AuditLog, CurrentUser,
                    DQError, ExceptionRequest, ExceptionRequestOut, ExceptionStatus, Status)
from repository import keyword_condition

logger = logging.getLogger("dq.workflow")


class WorkflowError(Exception):
    """Thao tác không hợp lệ; message hiển thị trực tiếp cho người dùng."""


class ActionResult(NamedTuple):
    done: int
    skipped: list[str]  # "#id: lý do"


def audit(db: Session, username: str, action: str, target: str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(at=datetime.now(), username=username, action=action, target=target,
                    detail=detail[:2000] if detail else None))


def _load_errors(db: Session, ids: list[int]) -> list[DQError]:
    if not ids:
        raise WorkflowError("Chưa chọn dòng lỗi nào.")
    return list(db.scalars(select(DQError).where(DQError.id.in_(ids)).with_for_update()))


def _set_resolved(row: DQError, by: str | None) -> None:
    row.resolved_date = date.today() if by else None
    row.resolved_by = by


# --------------------------------------------------------------------------- #
# Cập nhật trạng thái xử lý
# --------------------------------------------------------------------------- #
def update_status(db: Session, user: CurrentUser, error_ids: list[int], new_status: Status) -> ActionResult:
    if not user.can_edit:
        raise WorkflowError("Bạn không có quyền cập nhật trạng thái lỗi.")
    if new_status not in MANUAL_STATUSES:
        raise WorkflowError("Trạng thái ngoại lệ chỉ được thay đổi qua luồng phê duyệt.")

    done, skipped = 0, []
    for row in _load_errors(db, error_ids):
        if not user.can_access(row.branch_code):
            skipped.append(f"#{row.id}: ngoài phạm vi chi nhánh")
        elif row.status in EXCEPTION_STATUSES:
            skipped.append(f"#{row.id}: đang ở trạng thái '{row.status}'")
        elif row.status == new_status.value:
            skipped.append(f"#{row.id}: đã ở trạng thái '{row.status}'")
        else:
            audit(db, user.username, "STATUS_UPDATE", f"DQ#{row.id}", f"{row.status} -> {new_status.value}")
            row.status = new_status.value
            _set_resolved(row, user.username if new_status == Status.DONE else None)
            done += 1
    db.commit()
    return ActionResult(done, skipped)


# --------------------------------------------------------------------------- #
# Luồng ngoại lệ
# --------------------------------------------------------------------------- #
def request_exceptions(db: Session, user: CurrentUser, error_ids: list[int], reason: str) -> ActionResult:
    if not user.can_edit:
        raise WorkflowError("Bạn không có quyền gửi yêu cầu ngoại lệ.")
    reason = (reason or "").strip()
    if len(reason) < settings.EXCEPTION_REASON_MIN_LENGTH:
        raise WorkflowError(f"Lý do ngoại lệ cần tối thiểu {settings.EXCEPTION_REASON_MIN_LENGTH} ký tự.")

    eligible = {s.value for s in EXCEPTION_ELIGIBLE_STATUSES}
    now = datetime.now()
    done, skipped = 0, []
    for row in _load_errors(db, error_ids):
        if not user.can_access(row.branch_code):
            skipped.append(f"#{row.id}: ngoài phạm vi chi nhánh")
        elif row.status not in eligible:
            skipped.append(f"#{row.id}: trạng thái '{row.status}' không được gửi ngoại lệ")
        else:
            db.add(ExceptionRequest(
                error_id=row.id, branch_code=row.branch_code, reason=reason[:2000],
                previous_status=row.status, status=ExceptionStatus.PENDING.value,
                requested_by=user.username, requested_by_name=user.display_name, requested_at=now,
            ))
            row.status = Status.EXCEPTION_PENDING.value
            audit(db, user.username, "EXC_REQUEST", f"DQ#{row.id}", reason)
            done += 1
    db.commit()
    return ActionResult(done, skipped)


def _load_requests(db: Session, ids: list[int]) -> list[ExceptionRequest]:
    if not ids:
        raise WorkflowError("Chưa chọn yêu cầu nào.")
    return list(db.scalars(select(ExceptionRequest).where(ExceptionRequest.id.in_(ids)).with_for_update()))


def _restore_error(db: Session, req: ExceptionRequest) -> None:
    row = db.get(DQError, req.error_id)
    if row:
        row.status = req.previous_status
        _set_resolved(row, None)


def decide_exceptions(db: Session, user: CurrentUser, request_ids: list[int], approve: bool,
                      note: str | None) -> ActionResult:
    if not user.can_approve:
        raise WorkflowError("Bạn không có quyền phê duyệt ngoại lệ.")
    note = (note or "").strip() or None
    if not approve and not note:
        raise WorkflowError("Vui lòng nhập lý do từ chối.")

    now = datetime.now()
    done, skipped = 0, []
    for req in _load_requests(db, request_ids):
        if req.status != ExceptionStatus.PENDING.value:
            skipped.append(f"#{req.id}: đã ở trạng thái '{req.status}'")
        elif not user.can_access(req.branch_code):
            skipped.append(f"#{req.id}: ngoài phạm vi chi nhánh")
        elif req.requested_by == user.username:
            skipped.append(f"#{req.id}: không được tự phê duyệt yêu cầu của chính mình")
        else:
            req.status = (ExceptionStatus.APPROVED if approve else ExceptionStatus.REJECTED).value
            req.decided_by, req.decided_by_name, req.decided_at = user.username, user.display_name, now
            req.decision_note = note
            if approve:
                row = db.get(DQError, req.error_id)
                if row:
                    row.status = Status.EXCEPTION_APPROVED.value
                    _set_resolved(row, user.username)
            else:
                _restore_error(db, req)
            audit(db, user.username, "EXC_APPROVE" if approve else "EXC_REJECT",
                  f"NL#{req.id} / DQ#{req.error_id}", note)
            done += 1
    db.commit()
    return ActionResult(done, skipped)


def cancel_request(db: Session, user: CurrentUser, request_id: int) -> None:
    req = db.get(ExceptionRequest, request_id, with_for_update=True)
    if not req or not user.can_access(req.branch_code):
        raise WorkflowError("Không tìm thấy yêu cầu.")
    if req.status != ExceptionStatus.PENDING.value:
        raise WorkflowError("Chỉ hủy được yêu cầu đang chờ duyệt.")
    if req.requested_by != user.username and not user.is_admin:
        raise WorkflowError("Chỉ người gửi hoặc quản trị viên được hủy yêu cầu.")
    req.status = ExceptionStatus.CANCELLED.value
    req.decided_by, req.decided_by_name, req.decided_at = user.username, user.display_name, datetime.now()
    _restore_error(db, req)
    audit(db, user.username, "EXC_CANCEL", f"NL#{req.id} / DQ#{req.error_id}")
    db.commit()


def revoke_exception(db: Session, user: CurrentUser, request_id: int, note: str) -> None:
    if not user.is_admin:
        raise WorkflowError("Chỉ quản trị viên được thu hồi ngoại lệ.")
    note = (note or "").strip()
    if not note:
        raise WorkflowError("Vui lòng nhập lý do thu hồi.")
    req = db.get(ExceptionRequest, request_id, with_for_update=True)
    if not req or req.status != ExceptionStatus.APPROVED.value:
        raise WorkflowError("Chỉ thu hồi được ngoại lệ đã duyệt.")
    req.status = ExceptionStatus.REVOKED.value
    req.decision_note = f"{req.decision_note or ''}\n[Thu hồi bởi {user.username} {datetime.now():%d/%m/%Y %H:%M}] {note}".strip()
    _restore_error(db, req)
    audit(db, user.username, "EXC_REVOKE", f"NL#{req.id} / DQ#{req.error_id}", note)
    db.commit()


# --------------------------------------------------------------------------- #
# Truy vấn yêu cầu ngoại lệ
# --------------------------------------------------------------------------- #
def _request_conditions(user: CurrentUser, tab: str, branch_code: str | None, status: str | None,
                        keyword: str | None, error_id: int | None) -> list:
    r = ExceptionRequest
    conds = []
    if not user.all_branches:
        conds.append(r.branch_code == user.branch_code)
    elif branch_code:
        conds.append(r.branch_code == branch_code)
    if tab == "pending":
        conds.append(r.status == ExceptionStatus.PENDING.value)
    elif tab == "mine":
        conds.append(r.requested_by == user.username)
    if status:
        conds.append(r.status == status)
    if error_id:
        conds.append(r.error_id == error_id)
    if keyword:
        conds.append(keyword_condition(keyword, r.reason, r.requested_by, r.requested_by_name,
                                       DQError.rule_code, DQError.description))
    return conds


def list_requests(db: Session, user: CurrentUser, tab: str, page: int, page_size: int,
                  branch_code: str | None = None, status: str | None = None, keyword: str | None = None,
                  error_id: int | None = None) -> tuple[list[ExceptionRequestOut], int]:
    conds = _request_conditions(user, tab, branch_code, status, keyword, error_id)
    join = (ExceptionRequest.error_id == DQError.id)
    total = db.scalar(select(func.count()).select_from(ExceptionRequest).outerjoin(DQError, join).where(*conds)) or 0
    stmt = (select(ExceptionRequest, DQError).outerjoin(DQError, join).where(*conds)
            .order_by(ExceptionRequest.requested_at.desc(), ExceptionRequest.id.desc())
            .offset((page - 1) * page_size).limit(page_size))
    items = []
    for req, err in db.execute(stmt):
        out = ExceptionRequestOut.model_validate(req)
        if err:
            out = out.model_copy(update={"branch_name": err.branch_name, "rule_code": err.rule_code,
                                         "description": err.description, "severity": err.severity})
        items.append(out)
    return items, total


def count_pending_for(db: Session, user: CurrentUser) -> int:
    """Số yêu cầu đang chờ mà user này có thể phê duyệt (badge trên menu)."""
    if not user.can_approve:
        return 0
    conds = [ExceptionRequest.status == ExceptionStatus.PENDING.value,
             ExceptionRequest.requested_by != user.username]
    if not user.all_branches:
        conds.append(ExceptionRequest.branch_code == user.branch_code)
    return db.scalar(select(func.count()).select_from(ExceptionRequest).where(*conds)) or 0
