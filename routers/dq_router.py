"""Dashboard DQ: hiển thị, tìm kiếm, lọc, cập nhật trạng thái xử lý."""
import math
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from sqlalchemy.orm import Session

from auth import get_current_user, verify_csrf
from config import settings
from database import get_db
from models import CurrentUser, DQFilter, PagedResult, Severity, Status
from repository import error_stats, list_branches, search_errors
from routers import flash, flash_result, redirect, safe_next, templates
from workflow import WorkflowError, update_status

router = APIRouter(tags=["dq"])


def _clean(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if _clean(value) else None
    except ValueError:
        return None


def get_filters(
    branch_code: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> DQFilter:
    """Đọc bộ lọc từ query string; giá trị rỗng / không hợp lệ được bỏ qua.
    Dùng chung cho dashboard, API và export để kết quả luôn khớp nhau."""
    severity, status = _clean(severity), _clean(status)
    return DQFilter(
        branch_code=(_clean(branch_code) or "").upper() or None,
        severity=Severity(severity) if severity in {s.value for s in Severity} else None,
        status=Status(status) if status in {s.value for s in Status} else None,
        keyword=(_clean(keyword) or "")[:100] or None,
        date_from=_parse_date(date_from),
        date_to=_parse_date(date_to),
    )


def scoped_branches(db: Session, user: CurrentUser) -> list[tuple[str, str]]:
    branches = list_branches(db)
    if user.all_branches:
        return branches
    return [b for b in branches if b[0] == user.branch_code] or [(user.branch_code, user.branch_code)]


@router.get("/")
def index():
    return redirect("/dashboard")


@router.get("/dashboard")
def dashboard(
    request: Request,
    page: int = Query(1, ge=1),
    user: CurrentUser = Depends(get_current_user),
    filters: DQFilter = Depends(get_filters),
    db: Session = Depends(get_db),
):
    scoped = user.scope(filters)
    page_size = settings.PAGE_SIZE

    items, total = search_errors(db, scoped, page, page_size)
    pages = max(1, math.ceil(total / page_size))
    if page > pages:
        page = pages
        items, total = search_errors(db, scoped, page, page_size)

    params = scoped.to_query_params()
    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "filters": scoped,
        "items": items,
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
        "stats": error_stats(db, scoped),
        "branches": scoped_branches(db, user),
        "params": params,
        "qs": urlencode(params),
        "qs_no_branch": urlencode({k: v for k, v in params.items() if k != "branch_code"}),
        "current_url": request.url.path + (f"?{request.url.query}" if request.url.query else ""),
        "manual_statuses": [Status.PENDING.value, Status.IN_PROGRESS.value, Status.DONE.value],
    })


@router.post("/dq/status", dependencies=[Depends(verify_csrf)])
def change_status(
    request: Request,
    ids: list[int] = Form([]),
    new_status: str = Form(""),
    next: str = Form("/dashboard"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        result = update_status(db, user, ids, Status(new_status))
        flash_result(request, f"cập nhật trạng thái '{new_status}' cho", *result)
    except ValueError:
        flash(request, "Vui lòng chọn trạng thái mới.", "danger")
    except WorkflowError as exc:
        flash(request, str(exc), "danger")
    return redirect(safe_next(next))


@router.get("/api/dq-errors", response_model=PagedResult)
def api_dq_errors(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    user: CurrentUser = Depends(get_current_user),
    filters: DQFilter = Depends(get_filters),
    db: Session = Depends(get_db),
):
    """API JSON (cùng phân quyền như dashboard) để tích hợp hệ thống khác."""
    items, total = search_errors(db, user.scope(filters), page, page_size)
    return PagedResult(items=items, total=total, page=page, page_size=page_size,
                       pages=max(1, math.ceil(total / page_size)))
