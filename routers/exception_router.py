"""Luồng phê duyệt ngoại lệ: gửi yêu cầu, duyệt / từ chối, hủy, thu hồi, tra cứu."""
import math

from fastapi import APIRouter, Depends, Form, Query, Request
from sqlalchemy.orm import Session

from auth import get_current_user, verify_csrf
from config import settings
from database import get_db
from models import CurrentUser, ExceptionStatus
from routers import flash, flash_result, redirect, safe_next, templates
from routers.dq_router import scoped_branches
from workflow import (WorkflowError, cancel_request, decide_exceptions, list_requests, request_exceptions,
                      revoke_exception)

router = APIRouter(prefix="/exceptions", tags=["exceptions"])

TABS = {
    "pending": "Chờ phê duyệt",
    "mine": "Yêu cầu của tôi",
    "all": "Tất cả / Lịch sử",
}


@router.get("")
def exceptions_page(
    request: Request,
    tab: str | None = None,
    branch_code: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    error_id: int | None = None,
    page: int = Query(1, ge=1),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if tab not in TABS:
        tab = "pending" if user.can_approve else ("all" if error_id else "mine")
    branch_code = (branch_code or "").strip().upper() or None
    status = status if status in {s.value for s in ExceptionStatus} else None
    keyword = (keyword or "").strip()[:100] or None
    page_size = settings.PAGE_SIZE

    items, total = list_requests(db, user, tab, page, page_size, branch_code, status, keyword, error_id)
    pages = max(1, math.ceil(total / page_size))
    params = {k: v for k, v in {"tab": tab, "branch_code": branch_code, "status": status,
                                "keyword": keyword, "error_id": error_id}.items() if v}
    return templates.TemplateResponse(request, "exceptions.html", {
        "user": user,
        "tabs": TABS,
        "tab": tab,
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
        "params": params,
        "f": {"branch_code": branch_code, "status": status, "keyword": keyword, "error_id": error_id},
        "branches": scoped_branches(db, user),
        "current_url": request.url.path + (f"?{request.url.query}" if request.url.query else ""),
    })


@router.post("/request", dependencies=[Depends(verify_csrf)])
def submit_request(
    request: Request,
    ids: list[int] = Form([]),
    reason: str = Form(""),
    next: str = Form("/dashboard"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        flash_result(request, "gửi yêu cầu ngoại lệ cho", *request_exceptions(db, user, ids, reason))
    except WorkflowError as exc:
        flash(request, str(exc), "danger")
    return redirect(safe_next(next))


def _decide(request: Request, ids: list[int], note: str, next: str, approve: bool,
            user: CurrentUser, db: Session):
    try:
        result = decide_exceptions(db, user, ids, approve, note)
        flash_result(request, "phê duyệt" if approve else "từ chối", *result)
    except WorkflowError as exc:
        flash(request, str(exc), "danger")
    return redirect(safe_next(next, "/exceptions"))


@router.post("/approve", dependencies=[Depends(verify_csrf)])
def approve(request: Request, ids: list[int] = Form([]), note: str = Form(""), next: str = Form("/exceptions"),
            user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _decide(request, ids, note, next, True, user, db)


@router.post("/reject", dependencies=[Depends(verify_csrf)])
def reject(request: Request, ids: list[int] = Form([]), note: str = Form(""), next: str = Form("/exceptions"),
           user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _decide(request, ids, note, next, False, user, db)


@router.post("/{request_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel(request: Request, request_id: int, next: str = Form("/exceptions"),
           user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        cancel_request(db, user, request_id)
        flash(request, f"Đã hủy yêu cầu ngoại lệ #{request_id}.")
    except WorkflowError as exc:
        flash(request, str(exc), "danger")
    return redirect(safe_next(next, "/exceptions"))


@router.post("/{request_id}/revoke", dependencies=[Depends(verify_csrf)])
def revoke(request: Request, request_id: int, note: str = Form(""), next: str = Form("/exceptions"),
           user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        revoke_exception(db, user, request_id, note)
        flash(request, f"Đã thu hồi ngoại lệ #{request_id}.")
    except WorkflowError as exc:
        flash(request, str(exc), "danger")
    return redirect(safe_next(next, "/exceptions"))
