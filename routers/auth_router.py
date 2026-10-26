"""Đăng nhập / đăng xuất / kiểm tra session."""
import logging

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from auth import AuthError, authenticate, get_current_user, resolve_user, verify_csrf
from database import get_db
from models import CurrentUser
from routers import redirect, safe_next, templates
from workflow import audit

logger = logging.getLogger("dq.auth")
router = APIRouter(tags=["auth"])


@router.get("/login")
def login_page(request: Request, next: str | None = None):
    if request.session.get("identity"):
        return redirect(safe_next(next))
    return templates.TemplateResponse(request, "login.html", {"next": safe_next(next)})


@router.post("/login")
async def login_submit(request: Request, username: str = Form(""), password: str = Form(""),
                       next: str = Form("/dashboard"), db: Session = Depends(get_db)):
    client = request.client.host if request.client else "?"
    try:
        # ldap3 là thư viện đồng bộ -> chạy trong threadpool để không chặn event loop
        identity = await run_in_threadpool(authenticate, username, password)
        user = resolve_user(db, identity)
    except AuthError as exc:
        logger.warning("Đăng nhập thất bại: %s (%s) từ %s", username, exc, client)
        return templates.TemplateResponse(
            request, "login.html",
            {"error": str(exc), "username": username, "next": safe_next(next)},
            status_code=401,
        )
    request.session.clear()  # tránh session fixation
    request.session["identity"] = identity.model_dump(mode="json")
    audit(db, user.username, "LOGIN", client, f"{user.role_label} · {user.branch_code or '-'} · {user.permission_source}")
    db.commit()
    logger.info("Đăng nhập: %s (role=%s, branch=%s)", user.username, user.role.value, user.branch_code)
    return redirect(safe_next(next))


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


@router.get("/api/me", response_model=CurrentUser)
def me(user: CurrentUser = Depends(get_current_user)):
    """Kiểm tra session hiện tại (401 nếu chưa đăng nhập)."""
    return user
