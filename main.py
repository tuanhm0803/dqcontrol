"""Điểm khởi chạy ứng dụng DQ Dashboard.

Chạy trong mạng LAN:
    uvicorn main:app --host 0.0.0.0 --port 8080
"""
import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from auth import NotAuthenticated
from config import BASE_DIR, settings
from database import data_source, init_database
from routers import admin_router, auth_router, dq_router, exclusion_router, export_router, templates

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
logger = logging.getLogger("dq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.SECRET_KEY_GENERATED:
        logger.warning("Chưa đặt SECRET_KEY -> dùng khóa ngẫu nhiên, mọi session sẽ mất khi khởi động lại.")
    logger.info("MOCK_LDAP=%s | USE_MOCK_DATA=%s", settings.MOCK_LDAP, settings.USE_MOCK_DATA)
    init_database()  # kết nối CSDL sớm để phát hiện lỗi cấu hình ngay khi khởi động
    logger.info("Nguồn dữ liệu: %s", data_source())
    yield


app = FastAPI(
    title=settings.APP_NAME,
    lifespan=lifespan,
    # Chỉ bật Swagger UI khi DEBUG
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# ---------------- Middleware ----------------
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="dq_session",
    max_age=settings.SESSION_MAX_AGE,
    same_site="lax",
    https_only=settings.SESSION_HTTPS_ONLY,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path not in ("/login",) and not request.url.path.startswith("/static"):
        # Không cache trang chứa dữ liệu nội bộ (nút Back sau khi đăng xuất)
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, exc: NotAuthenticated):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Chưa đăng nhập hoặc phiên đã hết hạn"}, status_code=401)
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?next={quote(target)}", status_code=303)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    """Trang lỗi HTML cho 403/404 trên giao diện; API giữ nguyên JSON."""
    if exc.status_code in (403, 404) and not request.url.path.startswith("/api/"):
        return templates.TemplateResponse(request, "error.html", {"status_code": exc.status_code,
                                                                  "detail": exc.detail},
                                          status_code=exc.status_code)
    return await http_exception_handler(request, exc)


# ---------------- Static & routers ----------------
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(auth_router.router)
app.include_router(dq_router.router)
app.include_router(exclusion_router.router)
app.include_router(admin_router.router)
app.include_router(export_router.router)


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "data_source": data_source()}
