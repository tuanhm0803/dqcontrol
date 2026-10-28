"""Nghiệp vụ: cập nhật trạng thái lỗi DQ, danh mục quy tắc, luồng yêu cầu loại trừ, nhật ký hệ thống.

Luồng loại trừ (mỗi yêu cầu = loại trừ 1 bản ghi khỏi 1 quy tắc DQ của 1 chi nhánh), duyệt tuần tự 3 cấp
(models.APPROVAL_LEVELS):
    khai báo (user chi nhánh)    --> Chờ LĐ phòng duyệt
    khai báo (admin)             --> Chờ duyệt nghiệp vụ          (bỏ qua cấp LĐ phòng ban)
    Chờ LĐ phòng duyệt  --(LĐ phòng ban của chi nhánh)--> Chờ duyệt nghiệp vụ
    Chờ duyệt nghiệp vụ --(phê duyệt nghiệp vụ)-->        Chờ duyệt QTDL
    Chờ duyệt QTDL      --(phê duyệt QTDL)-->             Đã duyệt  -> được xuất file cho hệ thống DQ xử lý tiếp
    Chờ ... --(từ chối ở bất kỳ cấp, bắt buộc ghi chú)--> Từ chối;  --(người gửi / admin hủy)--> Đã hủy
    Đã duyệt --(admin thu hồi, bắt buộc ghi chú)--> Đã thu hồi
Admin duyệt được mọi cấp. Người gửi không tự duyệt yêu cầu của mình, và một người không duyệt 2 cấp của cùng yêu cầu.
Chống trùng theo (chi nhánh, quy tắc, mã bản ghi): chỉ yêu cầu ĐÃ DUYỆT còn hiệu lực chặn gửi / duyệt thêm;
nhiều yêu cầu chờ duyệt cho cùng bản ghi được phép.
"""
import logging
import re
from datetime import date, datetime, time, timedelta
from typing import NamedTuple

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from config import settings
from models import (APPROVAL_LEVELS, LEVEL_BY_STATUS, MANUAL_STATUSES, PENDING_STATUSES, ApprovalLevel, AuditLog,
                    CurrentUser, DQError, DQRule, ExclusionFilter, ExclusionRequest, ExclusionRequestOut,
                    ExclusionSource, ExclusionStatus, Status)
from repository import keyword_condition, list_branches, list_rules, rule_names

logger = logging.getLogger("dq.workflow")

# Số giá trị tối đa trong một mệnh đề IN (SQL Server giới hạn 2100 tham số / câu lệnh)
_IN_CHUNK = 500
RULE_CODE_RE = re.compile(r"^[A-Z0-9_.\-]{1,50}$")


class WorkflowError(Exception):
    """Thao tác không hợp lệ; message hiển thị trực tiếp cho người dùng."""


class ActionResult(NamedTuple):
    done: int
    skipped: list[str]  # "#id: lý do" hoặc "Dòng n: lý do"


class ExclusionInput(NamedTuple):
    """Một dòng yêu cầu loại trừ trước khi kiểm tra (từ form nhập tay hoặc file Excel)."""
    label: str  # "Dòng 5" - dùng trong thông báo bỏ qua
    branch_code: str | None
    rule_code: str
    record_key: str
    reason: str
    valid_to: date | None


class RuleInput(NamedTuple):
    """Một dòng danh mục quy tắc (form hoặc file upload)."""
    label: str
    rule_code: str
    rule_name: str


def audit(db: Session, username: str, action: str, target: str | None = None, detail: str | None = None) -> None:
    db.add(AuditLog(at=datetime.now(), username=username, action=action, target=target,
                    detail=detail[:2000] if detail else None))


# --------------------------------------------------------------------------- #
# Cập nhật trạng thái xử lý lỗi DQ (chỉ admin)
# --------------------------------------------------------------------------- #
def update_status(db: Session, user: CurrentUser, error_ids: list[int], new_status: Status) -> ActionResult:
    if not user.can_update_status:
        raise WorkflowError("Bạn không có quyền cập nhật trạng thái lỗi.")
    if new_status not in MANUAL_STATUSES:
        raise WorkflowError("Trạng thái không hợp lệ.")
    if not error_ids:
        raise WorkflowError("Chưa chọn dòng lỗi nào.")

    done, skipped = 0, []
    for row in db.scalars(select(DQError).where(DQError.id.in_(error_ids)).with_for_update()):
        if not user.can_access(row.branch_code):
            skipped.append(f"#{row.id}: ngoài phạm vi chi nhánh")
        elif row.status == new_status.value:
            skipped.append(f"#{row.id}: đã ở trạng thái '{row.status}'")
        else:
            audit(db, user.username, "STATUS_UPDATE", f"DQ#{row.id}", f"{row.status} -> {new_status.value}")
            row.status = new_status.value
            done_now = new_status == Status.DONE
            row.resolved_date = date.today() if done_now else None
            row.resolved_by = user.username if done_now else None
            done += 1
    db.commit()
    return ActionResult(done, skipped)


# --------------------------------------------------------------------------- #
# Danh mục mã quy tắc (chỉ admin)
# --------------------------------------------------------------------------- #
def _check_rule(item: RuleInput) -> tuple[str, str] | str:
    code, name = item.rule_code.strip().upper(), " ".join(item.rule_name.split())
    if not code:
        return "thiếu mã quy tắc"
    if not RULE_CODE_RE.match(code):
        return f"mã quy tắc '{code}' chỉ gồm chữ, số và _ . - (tối đa 50 ký tự)"
    if not name:
        return f"thiếu tên quy tắc cho {code}"
    if len(name) > 500:
        return f"tên quy tắc {code} dài quá 500 ký tự"
    return code, name


def save_rule(db: Session, user: CurrentUser, item: RuleInput, is_active: bool) -> bool:
    """Thêm / sửa một mã quy tắc. Trả True nếu là mã mới."""
    if not user.is_admin:
        raise WorkflowError("Chỉ quản trị viên được cập nhật danh mục mã quy tắc.")
    checked = _check_rule(item)
    if isinstance(checked, str):
        raise WorkflowError(checked[0].upper() + checked[1:] + ".")
    code, name = checked
    rule = db.get(DQRule, code)
    created = rule is None
    before = "(mới)" if created else f"{rule.rule_name} / {'đang dùng' if rule.is_active else 'ngừng dùng'}"
    if created:
        rule = DQRule(rule_code=code)
        db.add(rule)
    rule.rule_name, rule.is_active = name, is_active
    rule.updated_by, rule.updated_at = user.username, datetime.now()
    audit(db, user.username, "RULE_UPSERT", code, f"{before} -> {name} / {'đang dùng' if is_active else 'ngừng dùng'}")
    db.commit()
    return created


def replace_rules(db: Session, user: CurrentUser, items: list[RuleInput], filename: str) -> tuple[int, int, int]:
    """Upload thay thế toàn bộ: mã trong file được thêm / cập nhật và bật dùng, mã không có trong file chuyển ngừng dùng
    (không xóa, để yêu cầu cũ vẫn hiển thị tên). Tất cả hoặc không: một dòng sai thì không ghi gì.
    Trả (số mã thêm mới, số mã cập nhật, số mã chuyển ngừng dùng)."""
    if not user.is_admin:
        raise WorkflowError("Chỉ quản trị viên được cập nhật danh mục mã quy tắc.")
    if not items:
        raise WorkflowError("File không có mã quy tắc nào - danh mục giữ nguyên.")
    errors, rows = [], {}
    for item in items:
        checked = _check_rule(item)
        if isinstance(checked, str):
            errors.append(f"{item.label}: {checked}")
        elif checked[0] in rows:
            errors.append(f"{item.label}: trùng mã {checked[0]} với dòng khác")
        else:
            rows[checked[0]] = checked[1]
    if errors:
        more = f" (và {len(errors) - 10} lỗi khác)" if len(errors) > 10 else ""
        raise WorkflowError(f"File có {len(errors)} dòng lỗi, danh mục giữ nguyên: " + "; ".join(errors[:10]) + more)

    now = datetime.now()
    existing = {r.rule_code: r for r in db.scalars(select(DQRule))}
    added = updated = deactivated = 0
    for code, name in rows.items():
        rule = existing.get(code)
        if rule is None:
            db.add(DQRule(rule_code=code, rule_name=name, is_active=True, updated_by=user.username, updated_at=now))
            added += 1
        elif rule.rule_name != name or not rule.is_active:
            rule.rule_name, rule.is_active, rule.updated_by, rule.updated_at = name, True, user.username, now
            updated += 1
    for code, rule in existing.items():
        if code not in rows and rule.is_active:
            rule.is_active, rule.updated_by, rule.updated_at = False, user.username, now
            deactivated += 1
    audit(db, user.username, "RULE_UPLOAD", filename,
          f"{len(rows)} mã trong file: thêm {added}, cập nhật {updated}, ngừng dùng {deactivated}")
    db.commit()
    return added, updated, deactivated


# --------------------------------------------------------------------------- #
# Gửi yêu cầu loại trừ
# --------------------------------------------------------------------------- #
def _approved_valid(today: date):
    """Yêu cầu đã duyệt và còn hiệu lực: chặn gửi / duyệt trùng cùng (chi nhánh, quy tắc, bản ghi).
    Yêu cầu đang chờ duyệt KHÔNG chặn: được gửi nhiều yêu cầu chờ duyệt cho cùng bản ghi."""
    r = ExclusionRequest
    return (r.status == ExclusionStatus.APPROVED.value) & or_(r.valid_to.is_(None), r.valid_to >= today)


def _approved_keys(db: Session, record_keys: set[str], today: date) -> set[tuple[str, str, str]]:
    r = ExclusionRequest
    found: set[tuple[str, str, str]] = set()
    keys = sorted(record_keys)
    for i in range(0, len(keys), _IN_CHUNK):
        rows = db.execute(select(r.branch_code, r.rule_code, r.record_key)
                          .where(r.record_key.in_(keys[i:i + _IN_CHUNK]), _approved_valid(today)))
        found.update(tuple(row) for row in rows)
    return found


def _check_item(item: ExclusionInput, user: CurrentUser, branches: dict[str, str], rules: set[str],
                today: date) -> tuple[str, str, str, str] | str:
    """Trả (chi nhánh, mã quy tắc, mã bản ghi, lý do) đã chuẩn hóa, hoặc chuỗi lý do bỏ qua.
    Chi nhánh bỏ trống = chi nhánh của user; được khai báo cho chi nhánh khác."""
    branch = (item.branch_code or "").strip().upper() or (user.branch_code or "").upper()
    if not branch:
        return "thiếu mã chi nhánh"
    if branches:
        if branch not in branches:
            return f"mã chi nhánh '{branch}' không tồn tại"
        branch = branches[branch]

    rule = item.rule_code.strip().upper()
    if not rule:
        return "thiếu mã quy tắc DQ"
    if rule not in rules:
        return f"mã quy tắc '{rule}' không có trong danh mục hoặc đã ngừng dùng"

    key = item.record_key.strip()
    if not key:
        return "thiếu mã bản ghi"
    if len(key) > 100:
        return "mã bản ghi dài quá 100 ký tự"
    reason = item.reason.strip()
    if len(reason) < settings.EXCLUSION_REASON_MIN_LENGTH:
        return f"lý do cần tối thiểu {settings.EXCLUSION_REASON_MIN_LENGTH} ký tự"
    if not item.valid_to:
        return "thiếu ngày hiệu lực đến"
    if item.valid_to < today:
        return "ngày hiệu lực đến đã qua"
    return branch, rule, key, reason[:2000]


def first_status(user: CurrentUser) -> ExclusionStatus:
    """Trạng thái ban đầu: yêu cầu do admin khai báo bỏ qua cấp LĐ phòng ban."""
    return ExclusionStatus.PENDING_BUSINESS if user.is_admin else ExclusionStatus.PENDING_MANAGER


def create_exclusions(db: Session, user: CurrentUser, items: list[ExclusionInput], source: ExclusionSource,
                      upload_file: str | None = None) -> ActionResult:
    """Tạo yêu cầu loại trừ hàng loạt. Dòng không hợp lệ hoặc trùng yêu cầu đã duyệt còn hiệu lực bị bỏ qua."""
    if not user.can_request:
        raise WorkflowError("Bạn không có quyền gửi yêu cầu loại trừ.")
    if not items:
        raise WorkflowError("Không có dòng nào để gửi.")
    rules = {code for code, _ in list_rules(db)}
    if not rules:
        raise WorkflowError("Danh mục mã quy tắc đang trống. Vui lòng liên hệ quản trị viên cập nhật danh mục.")

    today, now = date.today(), datetime.now()
    # Danh mục chi nhánh chuẩn (so khớp không phân biệt hoa thường, lưu theo cách viết trong bảng lỗi DQ)
    branches = {code.upper(): code for code, _ in list_branches(db)}
    approved = _approved_keys(db, {i.record_key.strip() for i in items if i.record_key.strip()}, today)
    status = first_status(user).value

    created: list[ExclusionRequest] = []
    seen: set[tuple[str, str, str]] = set()
    skipped: list[str] = []
    for item in items:
        checked = _check_item(item, user, branches, rules, today)
        if isinstance(checked, str):
            skipped.append(f"{item.label}: {checked}")
            continue
        branch, rule, key, reason = checked
        if (branch, rule, key) in seen:
            skipped.append(f"{item.label}: trùng với dòng khác trong lần gửi này")
        elif (branch, rule, key) in approved:
            skipped.append(f"{item.label}: đã có yêu cầu đã duyệt còn hiệu lực cho {rule} - {key}")
        else:
            seen.add((branch, rule, key))
            created.append(ExclusionRequest(
                branch_code=branch, rule_code=rule, record_key=key, reason=reason, valid_to=item.valid_to,
                source=source.value, upload_file=upload_file, status=status,
                requested_by=user.username, requested_by_name=user.display_name, requested_at=now,
            ))
    if created:
        db.add_all(created)
        db.flush()
        ids = [r.id for r in created]
        target = f"LT#{ids[0]}" if len(ids) == 1 else f"LT#{min(ids)}..{max(ids)}"
        detail = f"{len(created)} yêu cầu ({source.value}{': ' + upload_file if upload_file else ''})"
        if skipped:
            detail += f"; bỏ qua {len(skipped)} dòng"
        audit(db, user.username, "EXCL_UPLOAD" if source == ExclusionSource.EXCEL else "EXCL_REQUEST",
              target, detail)
        db.commit()
    return ActionResult(len(created), skipped)


# --------------------------------------------------------------------------- #
# Phê duyệt nhiều cấp / từ chối / hủy / thu hồi
# --------------------------------------------------------------------------- #
def _load_requests(db: Session, ids: list[int]) -> list[ExclusionRequest]:
    if not ids:
        raise WorkflowError("Chưa chọn yêu cầu nào.")
    return list(db.scalars(select(ExclusionRequest).where(ExclusionRequest.id.in_(ids)).with_for_update()))


def _approved_duplicate(db: Session, req: ExclusionRequest, today: date) -> int | None:
    """Id yêu cầu khác đã duyệt còn hiệu lực cho cùng bản ghi (autoflush nên thấy cả dòng vừa duyệt trong lô)."""
    r = ExclusionRequest
    return db.scalar(select(r.id).where(r.id != req.id, r.branch_code == req.branch_code, r.rule_code == req.rule_code,
                                        r.record_key == req.record_key, _approved_valid(today)).limit(1))


def _approved_level_by(req, username: str) -> ApprovalLevel | None:
    """Cấp mà user đã duyệt trên yêu cầu này (một người không duyệt 2 cấp)."""
    return next((lv for lv in APPROVAL_LEVELS if getattr(req, f"{lv.key}_by") == username), None)


def decide_blocker(user: CurrentUser, req) -> str | None:
    """Lý do user không được duyệt / từ chối yêu cầu (req: model hoặc ExclusionRequestOut), None nếu được.
    Chỉ gồm điều kiện không cần truy vấn - template dùng để hiện checkbox."""
    level = LEVEL_BY_STATUS.get(req.status)
    if level is None:
        return f"đã ở trạng thái '{req.status}'"
    if level not in user.approval_levels:
        return f"đang chờ cấp {level.label}, bạn không có quyền duyệt cấp này"
    if not user.can_access(req.branch_code):
        return "ngoài phạm vi chi nhánh"
    if req.requested_by == user.username:
        return "không được tự phê duyệt yêu cầu của chính mình"
    if done := _approved_level_by(req, user.username):
        return f"bạn đã duyệt cấp {done.label} của yêu cầu này"
    return None


def _append_note(req: ExclusionRequest, action: str, user: CurrentUser, now: datetime, note: str | None) -> None:
    """Nối một dòng vào nhật ký ghi chú các cấp: '[Duyệt cấp QTDL - user dd/mm/yyyy HH:MM] ghi chú'."""
    line = f"[{action} - {user.username} {now:%d/%m/%Y %H:%M}]" + (f" {note}" if note else "")
    req.decision_note = f"{req.decision_note or ''}\n{line}".strip()[:4000]


def decide_exclusions(db: Session, user: CurrentUser, request_ids: list[int], approve: bool,
                      note: str | None) -> ActionResult:
    """Duyệt (chuyển sang cấp kế tiếp, cấp cuối -> Đã duyệt) hoặc từ chối các yêu cầu ở cấp user được duyệt."""
    if not user.can_approve:
        raise WorkflowError("Bạn không có quyền phê duyệt yêu cầu loại trừ.")
    note = (note or "").strip()[:1000] or None
    if not approve and not note:
        raise WorkflowError("Vui lòng nhập lý do từ chối.")

    today, now = date.today(), datetime.now()
    done, skipped = 0, []
    for req in _load_requests(db, request_ids):
        level = LEVEL_BY_STATUS.get(req.status)
        blocker = decide_blocker(user, req)
        if not blocker and approve and req.valid_to and req.valid_to < today:
            blocker = f"đã quá ngày hiệu lực {req.valid_to:%d/%m/%Y}"
        if not blocker and approve and level.next == ExclusionStatus.APPROVED:
            if dup := _approved_duplicate(db, req, today):
                blocker = f"bản ghi đã có yêu cầu đã duyệt còn hiệu lực #{dup}"
        if blocker:
            skipped.append(f"#{req.id}: {blocker}")
            continue
        if approve:
            setattr(req, f"{level.key}_by", user.username)
            setattr(req, f"{level.key}_by_name", user.display_name)
            setattr(req, f"{level.key}_at", now)
            req.status = level.next.value
            if level.next == ExclusionStatus.APPROVED:
                req.decided_by, req.decided_by_name, req.decided_at = user.username, user.display_name, now
        else:
            req.status = ExclusionStatus.REJECTED.value
            req.decided_by, req.decided_by_name, req.decided_at = user.username, user.display_name, now
        if note or not approve:
            _append_note(req, f"{'Duyệt' if approve else 'Từ chối'} cấp {level.label}", user, now, note)
        audit(db, user.username, "EXCL_APPROVE" if approve else "EXCL_REJECT", f"LT#{req.id}",
              f"Cấp {level.label}: {req.rule_code} - {req.record_key} -> {req.status}" + (f"; {note}" if note else ""))
        done += 1
    db.commit()
    return ActionResult(done, skipped)


def cancel_exclusion(db: Session, user: CurrentUser, request_id: int) -> None:
    req = db.get(ExclusionRequest, request_id, with_for_update=True)
    if not req or not (user.can_access(req.branch_code) or req.requested_by == user.username):
        raise WorkflowError("Không tìm thấy yêu cầu.")
    if req.status not in PENDING_STATUSES:
        raise WorkflowError("Chỉ hủy được yêu cầu đang chờ duyệt.")
    if req.requested_by != user.username and not user.is_admin:
        raise WorkflowError("Chỉ người gửi hoặc quản trị viên được hủy yêu cầu.")
    req.status = ExclusionStatus.CANCELLED.value
    req.decided_by, req.decided_by_name, req.decided_at = user.username, user.display_name, datetime.now()
    audit(db, user.username, "EXCL_CANCEL", f"LT#{req.id}", f"{req.rule_code} - {req.record_key}")
    db.commit()


def revoke_exclusion(db: Session, user: CurrentUser, request_id: int, note: str) -> None:
    if not user.is_admin:
        raise WorkflowError("Chỉ quản trị viên được thu hồi yêu cầu loại trừ.")
    note = (note or "").strip()[:1000]
    if not note:
        raise WorkflowError("Vui lòng nhập lý do thu hồi.")
    req = db.get(ExclusionRequest, request_id, with_for_update=True)
    if not req or req.status != ExclusionStatus.APPROVED.value:
        raise WorkflowError("Chỉ thu hồi được yêu cầu đã duyệt.")
    now = datetime.now()
    req.status = ExclusionStatus.REVOKED.value
    req.decided_by, req.decided_by_name, req.decided_at = user.username, user.display_name, now
    _append_note(req, "Thu hồi", user, now, note)
    audit(db, user.username, "EXCL_REVOKE", f"LT#{req.id}", f"{req.rule_code} - {req.record_key}; {note}")
    db.commit()


# --------------------------------------------------------------------------- #
# Truy vấn yêu cầu loại trừ
# --------------------------------------------------------------------------- #
def _scope_conditions(user: CurrentUser) -> list:
    """Không xem toàn hệ thống: chi nhánh của mình + yêu cầu chính mình gửi cho chi nhánh khác."""
    r = ExclusionRequest
    if user.all_branches:
        return []
    return [or_(r.branch_code == user.branch_code, r.requested_by == user.username)]


def _pending_for_conditions(user: CurrentUser) -> list:
    """Yêu cầu đang chờ ở cấp user được duyệt."""
    return [ExclusionRequest.status.in_([lv.pending.value for lv in user.approval_levels])]


def _exclusion_conditions(user: CurrentUser, tab: str, f: ExclusionFilter) -> list:
    r = ExclusionRequest
    conds = _scope_conditions(user)
    if f.branch_code:
        conds.append(r.branch_code == f.branch_code)
    if tab == "pending":
        conds += _pending_for_conditions(user)
    elif tab == "mine":
        conds.append(r.requested_by == user.username)
    if f.status:
        conds.append(r.status == f.status)
    if f.rule_code:
        conds.append(r.rule_code == f.rule_code)
    if f.decided_from:
        conds.append(r.decided_at >= datetime.combine(f.decided_from, time.min))
    if f.decided_to:
        conds.append(r.decided_at < datetime.combine(f.decided_to + timedelta(days=1), time.min))
    if f.active_only:
        today = date.today()
        conds.append(or_(r.valid_to.is_(None), r.valid_to >= today))
    if f.keyword:
        conds.append(keyword_condition(f.keyword, r.record_key, r.rule_code, r.reason, r.requested_by,
                                       r.requested_by_name, r.upload_file))
    return conds


def _with_rule_names(db: Session, rows) -> list[ExclusionRequestOut]:
    names = rule_names(db)
    return [ExclusionRequestOut.model_validate(r).model_copy(update={"rule_name": names.get(r.rule_code)})
            for r in rows]


def list_exclusions(db: Session, user: CurrentUser, tab: str, f: ExclusionFilter, page: int,
                    page_size: int) -> tuple[list[ExclusionRequestOut], int]:
    conds = _exclusion_conditions(user, tab, f)
    total = db.scalar(select(func.count()).select_from(ExclusionRequest).where(*conds)) or 0
    stmt = (select(ExclusionRequest).where(*conds)
            .order_by(ExclusionRequest.requested_at.desc(), ExclusionRequest.id.desc())
            .offset((page - 1) * page_size).limit(page_size))
    return _with_rule_names(db, db.scalars(stmt)), total


def fetch_exclusions(db: Session, user: CurrentUser, f: ExclusionFilter, limit: int) -> list[ExclusionRequestOut]:
    """Dữ liệu cho file xuất (theo phạm vi quyền), sắp theo ngày kết thúc (ngày QTDL duyệt)."""
    stmt = (select(ExclusionRequest).where(*_exclusion_conditions(user, "all", f))
            .order_by(ExclusionRequest.decided_at, ExclusionRequest.id).limit(limit))
    return _with_rule_names(db, db.scalars(stmt))


def count_pending_for(db: Session, user: CurrentUser) -> int:
    """Số yêu cầu đang chờ mà user này có thể duyệt ngay (badge trên menu): đúng cấp, đúng phạm vi,
    không phải yêu cầu của mình và mình chưa duyệt cấp nào trước đó."""
    if not user.can_approve:
        return 0
    r = ExclusionRequest
    conds = [*_pending_for_conditions(user), r.requested_by != user.username]
    if not user.all_branches:
        conds.append(r.branch_code == user.branch_code)
    for lv in APPROVAL_LEVELS:
        col = getattr(r, f"{lv.key}_by")
        conds.append(or_(col.is_(None), col != user.username))
    return db.scalar(select(func.count()).select_from(r).where(*conds)) or 0
