"""Trang quản trị: phân quyền người dùng (ghi đè quyền theo nhóm AD) và nhật ký hệ thống."""
import math
import re
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from auth import normalize_username, require_admin, verify_csrf
from config import settings
from database import get_db
from models import ROLE_LABELS, AuditLog, CurrentUser, Role, UserPermission, UserPermissionOut
from repository import keyword_condition, list_branches
from routers import flash, redirect, templates
from workflow import audit

router = APIRouter(prefix="/admin", tags=["admin"])

USERNAME_RE = re.compile(r"^[a-z0-9._-]{1,100}$")
AUDIT_ACTIONS = ["LOGIN", "STATUS_UPDATE", "EXC_REQUEST", "EXC_APPROVE", "EXC_REJECT", "EXC_CANCEL",
                 "EXC_REVOKE", "PERM_UPSERT", "PERM_DELETE", "EXPORT"]


@router.get("")
def admin_home():
    return redirect("/admin/permissions")


@router.get("/permissions")
def permissions_page(
    request: Request,
    action: str | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    perms = [UserPermissionOut.model_validate(p)
             for p in db.scalars(select(UserPermission).order_by(UserPermission.username))]

    action = action if action in AUDIT_ACTIONS else None
    keyword = (keyword or "").strip()[:100] or None
    conds = []
    if action:
        conds.append(AuditLog.action == action)
    if keyword:
        conds.append(keyword_condition(keyword, AuditLog.username, AuditLog.target, AuditLog.detail))
    page_size = 50
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conds)) or 0
    logs = db.scalars(select(AuditLog).where(*conds).order_by(AuditLog.at.desc(), AuditLog.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()

    return templates.TemplateResponse(request, "admin_permissions.html", {
        "user": user,
        "perms": perms,
        "branches": list_branches(db),
        "logs": logs,
        "log_total": total,
        "page": page,
        "pages": max(1, math.ceil(total / page_size)),
        "params": {k: v for k, v in {"action": action, "keyword": keyword}.items() if v},
        "audit_actions": AUDIT_ACTIONS,
        "f": {"action": action, "keyword": keyword},
        "ad_groups": [
            (settings.LDAP_GROUP_ADMIN, ROLE_LABELS[Role.ADMIN], "Toàn hệ thống; quản trị phân quyền; phê duyệt"),
            (settings.LDAP_GROUP_APPROVER, ROLE_LABELS[Role.APPROVER], "Toàn hệ thống; phê duyệt / từ chối ngoại lệ"),
            (settings.LDAP_GROUP_USER, ROLE_LABELS[Role.BRANCH_USER],
             f"Chi nhánh theo thuộc tính AD '{settings.LDAP_BRANCH_ATTRIBUTE}'; xử lý lỗi, gửi ngoại lệ"),
        ],
    })


def _validate(username: str, role: str, branch_code: str | None, all_branches: bool, is_active: bool,
              current: CurrentUser) -> tuple[Role, bool]:
    if not USERNAME_RE.match(username):
        raise ValueError("Tên đăng nhập chỉ gồm chữ thường, số và . _ -")
    try:
        role_enum = Role(role)
    except ValueError:
        raise ValueError("Vai trò không hợp lệ.") from None
    if username == current.username and (role_enum != Role.ADMIN or not is_active):
        raise ValueError("Không thể tự hạ quyền hoặc khóa chính tài khoản của bạn.")
    if role_enum == Role.ADMIN:
        all_branches = True
    elif role_enum == Role.BRANCH_USER:
        all_branches = False
    if not all_branches and not branch_code:
        raise ValueError("Cần chọn Mã chi nhánh khi không cho xem toàn hệ thống.")
    return role_enum, all_branches


def _describe(p: UserPermission | None) -> str:
    if p is None:
        return "(theo AD)"
    return (f"{p.role}/{p.branch_code or '-'}/{'all' if p.all_branches else 'branch'}/"
            f"{'active' if p.is_active else 'locked'}")


@router.post("/permissions", dependencies=[Depends(verify_csrf)])
def save_permission(
    request: Request,
    username: str = Form(""),
    display_name: str = Form(""),
    role: str = Form(""),
    branch_code: str = Form(""),
    all_branches: str | None = Form(None),
    is_active: str | None = Form(None),
    note: str = Form(""),
    user: CurrentUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    username = normalize_username(username)
    branch = branch_code.strip().upper() or None
    active = is_active is not None
    try:
        role_enum, all_b = _validate(username, role, branch, all_branches is not None, active, user)
    except ValueError as exc:
        flash(request, str(exc), "danger")
        return redirect("/admin/permissions")

    perm = db.get(UserPermission, username)
    before = _describe(perm)
    if perm is None:
        perm = UserPermission(username=username)
        db.add(perm)
    perm.display_name = display_name.strip()[:200] or None
    perm.role = role_enum.value
    perm.branch_code = branch
    perm.all_branches = all_b
    perm.is_active = active
    perm.note = note.strip()[:500] or None
    perm.updated_by = user.username
    perm.updated_at = datetime.now()
    audit(db, user.username, "PERM_UPSERT", username, f"{before} -> {_describe(perm)}")
    db.commit()
    flash(request, f"Đã lưu phân quyền cho '{username}'. Có hiệu lực ngay ở thao tác tiếp theo của người dùng.")
    return redirect("/admin/permissions")


@router.post("/permissions/{username}/delete", dependencies=[Depends(verify_csrf)])
def delete_permission(request: Request, username: str, user: CurrentUser = Depends(require_admin),
                      db: Session = Depends(get_db)):
    username = normalize_username(username)
    if username == user.username:
        flash(request, "Không thể xóa phân quyền của chính bạn.", "danger")
        return redirect("/admin/permissions")
    perm = db.get(UserPermission, username)
    if perm:
        audit(db, user.username, "PERM_DELETE", username, f"{_describe(perm)} -> (theo AD)")
        db.delete(perm)
        db.commit()
        flash(request, f"Đã xóa phân quyền nội bộ của '{username}' - người dùng quay về quyền theo nhóm AD.")
    return redirect("/admin/permissions")
