"""Jinja2 templates, thông báo flash và helper dùng chung cho các router."""
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import csrf_token
from config import BASE_DIR, settings
from database import SessionLocal, data_source
from models import ROLE_LABELS, CurrentUser, ExceptionStatus, Role, Severity, Status
from workflow import count_pending_for

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

SEVERITY_BADGE = {
    Severity.HIGH.value: "text-bg-danger",
    Severity.MEDIUM.value: "text-bg-warning",
    Severity.LOW.value: "text-bg-info",
}
STATUS_BADGE = {
    Status.PENDING.value: "text-bg-secondary",
    Status.IN_PROGRESS.value: "text-bg-primary",
    Status.DONE.value: "text-bg-success",
    Status.EXCEPTION_PENDING.value: "text-bg-warning",
    Status.EXCEPTION_APPROVED.value: "badge-exception",
}
EXCEPTION_BADGE = {
    ExceptionStatus.PENDING.value: "text-bg-warning",
    ExceptionStatus.APPROVED.value: "text-bg-success",
    ExceptionStatus.REJECTED.value: "text-bg-danger",
    ExceptionStatus.CANCELLED.value: "text-bg-secondary",
    ExceptionStatus.REVOKED.value: "text-bg-dark",
}


def flash(request: Request, message: str, category: str = "success") -> None:
    request.session["flash"] = [*request.session.get("flash", []), {"category": category, "message": message}]


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop("flash", [])


def flash_result(request: Request, verb: str, done: int, skipped: list[str]) -> None:
    """Thông báo kết quả thao tác hàng loạt."""
    if done:
        flash(request, f"Đã {verb} {done} dòng.", "success")
    if skipped:
        more = f" (và {len(skipped) - 5} dòng khác)" if len(skipped) > 5 else ""
        flash(request, f"Bỏ qua {len(skipped)} dòng: " + "; ".join(skipped[:5]) + more, "warning")


def safe_next(url: str | None, default: str = "/dashboard") -> str:
    """Chỉ cho phép chuyển hướng nội bộ (chống open redirect)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def pending_exceptions(user: CurrentUser | None) -> int:
    if not user or not user.can_approve:
        return 0
    with SessionLocal() as db:
        return count_pending_for(db, user)


def page_url(path: str, params: dict, page: int) -> str:
    return f"{path}?{urlencode({**params, 'page': page})}"


templates.env.globals.update(
    app_name=settings.APP_NAME,
    mock_ldap=settings.MOCK_LDAP,
    severities=[s.value for s in Severity],
    statuses=[s.value for s in Status],
    exception_statuses=[s.value for s in ExceptionStatus],
    roles=[(r.value, ROLE_LABELS[r]) for r in Role],
    severity_badge=lambda v: SEVERITY_BADGE.get(v, "text-bg-light"),
    status_badge=lambda v: STATUS_BADGE.get(v, "text-bg-light"),
    exception_badge=lambda v: EXCEPTION_BADGE.get(v, "text-bg-light"),
    data_source=data_source,
    csrf_token=csrf_token,
    pop_flashes=pop_flashes,
    pending_exceptions=pending_exceptions,
    page_url=page_url,
    reason_min_length=settings.EXCEPTION_REASON_MIN_LENGTH,
)
