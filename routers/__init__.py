"""Jinja2 templates, thông báo flash và helper dùng chung cho các router."""
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import csrf_token
from config import BASE_DIR, settings
from database import SessionLocal, data_source
from models import PENDING_STATUSES, ROLE_LABELS, CurrentUser, ExclusionStatus, Role
from workflow import count_pending_for

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

EXCLUSION_BADGE = {
    ExclusionStatus.PENDING_MANAGER.value: "text-bg-warning",
    ExclusionStatus.PENDING_BUSINESS.value: "text-bg-info",
    ExclusionStatus.PENDING_DQ.value: "text-bg-primary",
    ExclusionStatus.APPROVED.value: "text-bg-success",
    ExclusionStatus.REJECTED.value: "text-bg-danger",
    ExclusionStatus.CANCELLED.value: "text-bg-secondary",
    ExclusionStatus.REVOKED.value: "text-bg-dark",
}


def flash(request: Request, message: str, category: str = "success") -> None:
    request.session["flash"] = [*request.session.get("flash", []), {"category": category, "message": message}]


def pop_flashes(request: Request) -> list[dict]:
    return request.session.pop("flash", [])


def flash_result(request: Request, verb: str, done: int, skipped: list[str], limit: int = 5) -> None:
    """Thông báo kết quả thao tác hàng loạt (liệt kê tối đa `limit` dòng bị bỏ qua)."""
    if done:
        flash(request, f"Đã {verb} {done} dòng.", "success")
    if skipped:
        more = f" (và {len(skipped) - limit} dòng khác)" if len(skipped) > limit else ""
        flash(request, f"Bỏ qua {len(skipped)} dòng: " + "; ".join(skipped[:limit]) + more, "warning")


def safe_next(url: str | None, default: str = "/") -> str:
    """Chỉ cho phép chuyển hướng nội bộ (chống open redirect)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return default


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def pending_exclusions(user: CurrentUser | None) -> int:
    if not user or not user.can_approve:
        return 0
    with SessionLocal() as db:
        return count_pending_for(db, user)


def page_url(path: str, params: dict, page: int) -> str:
    return f"{path}?{urlencode({**params, 'page': page})}"


templates.env.globals.update(
    app_name=settings.APP_NAME,
    mock_ldap=settings.MOCK_LDAP,
    exclusion_statuses=[s.value for s in ExclusionStatus],
    pending_statuses=list(PENDING_STATUSES),
    roles=[(r.value, ROLE_LABELS[r]) for r in Role],
    exclusion_badge=lambda v: EXCLUSION_BADGE.get(v, "text-bg-light"),
    data_source=data_source,
    csrf_token=csrf_token,
    pop_flashes=pop_flashes,
    pending_exclusions=pending_exclusions,
    page_url=page_url,
    reason_min_length=settings.EXCLUSION_REASON_MIN_LENGTH,
)
