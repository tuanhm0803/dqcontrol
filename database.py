"""Kết nối CSDL (SQLAlchemy) và khởi tạo dữ liệu.

- USE_MOCK_DATA / MOCK_DB = True: dùng file SQLite MOCK_DATABASE_URL, tự tạo bảng và nạp dữ liệu
  từ mock_data.py ở lần chạy đầu (dữ liệu được giữ lại giữa các lần khởi động).
- USE_MOCK_DATA = False: kết nối DATABASE_URL (SQL Server / Oracle / PostgreSQL...), tự tạo các bảng
  của ứng dụng (ngoại lệ, phân quyền, nhật ký) nếu chưa có. Không kết nối được và
  DB_FALLBACK_TO_MOCK = True -> chuyển sang dữ liệu giả lập.

CLI:
    python database.py init-db [--seed]   # tạo bảng (kể cả bảng lỗi DQ) trên DATABASE_URL, tùy chọn nạp dữ liệu mẫu
    python database.py reset-mock         # xóa & nạp lại dữ liệu giả lập
"""
import logging
import sys
import threading

from sqlalchemy import create_engine, delete, func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings
from mock_data import generate_mock_dataset
from models import APP_TABLES, AuditLog, Base, DQError, ExceptionRequest, UserPermission

logger = logging.getLogger("dq.database")

SessionLocal = sessionmaker(expire_on_commit=False)
_state: dict = {"engine": None, "source": None}
_lock = threading.Lock()

# Cột bắt buộc trên bảng lỗi DQ thật (resolved_* được ứng dụng ghi vào)
REQUIRED_DQ_COLUMNS = {c.name for c in DQError.__table__.columns}


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "echo": settings.DB_ECHO}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def seed_mock_data(engine: Engine, force: bool = False) -> None:
    with Session(engine) as s:
        if force:
            for model in (ExceptionRequest, DQError):
                s.execute(delete(model))
        elif s.scalar(select(func.count()).select_from(DQError)):
            return
        errors, requests = generate_mock_dataset()
        s.add_all(DQError(**r) for r in errors)
        s.add_all(ExceptionRequest(**r) for r in requests)
        s.commit()
    logger.info("Đã nạp %d lỗi DQ và %d yêu cầu ngoại lệ giả lập", len(errors), len(requests))


def _init_mock() -> Engine:
    engine = _make_engine(settings.MOCK_DATABASE_URL)
    Base.metadata.create_all(engine)
    seed_mock_data(engine)
    return engine


def _check_dq_table(engine: Engine) -> None:
    insp = inspect(engine)
    if not insp.has_table(settings.DQ_TABLE_NAME, schema=settings.DQ_TABLE_SCHEMA):
        raise RuntimeError(f"Không tìm thấy bảng lỗi DQ '{settings.DQ_TABLE_NAME}'")
    columns = {c["name"].lower() for c in insp.get_columns(settings.DQ_TABLE_NAME, schema=settings.DQ_TABLE_SCHEMA)}
    missing = sorted(REQUIRED_DQ_COLUMNS - columns)
    if missing:
        raise RuntimeError(
            f"Bảng '{settings.DQ_TABLE_NAME}' thiếu cột {missing}. "
            "Xem mục 'Kết nối CSDL thật' trong README để thêm cột resolved_date / resolved_by."
        )


def init_database() -> None:
    """Khởi tạo engine một lần (gọi khi app khởi động; get_db cũng tự gọi nếu cần)."""
    if _state["engine"] is not None:
        return
    with _lock:
        if _state["engine"] is not None:
            return
        if settings.USE_MOCK_DATA:
            logger.info("USE_MOCK_DATA=True -> dữ liệu giả lập tại %s", settings.MOCK_DATABASE_URL)
            engine, source = _init_mock(), "mock"
        else:
            try:
                engine = _make_engine(settings.DATABASE_URL)
                _check_dq_table(engine)
                Base.metadata.create_all(engine, tables=APP_TABLES)
                source = "database"
                logger.info("Đã kết nối CSDL: %s", engine.url.render_as_string(hide_password=True))
            except Exception:
                if not settings.DB_FALLBACK_TO_MOCK:
                    raise
                logger.exception("Không dùng được CSDL thật -> chuyển sang dữ liệu giả lập (DB_FALLBACK_TO_MOCK=True)")
                engine, source = _init_mock(), "mock"
        SessionLocal.configure(bind=engine)
        _state.update(engine=engine, source=source)


def data_source() -> str:
    return _state["source"] or "chưa khởi tạo"


def get_db():
    """Dependency FastAPI: một Session cho mỗi request."""
    init_database()
    with SessionLocal() as db:
        yield db


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) >= 2 else ""
    if command == "init-db":
        target = _make_engine(settings.DATABASE_URL)
        Base.metadata.create_all(target)
        if "--seed" in sys.argv:
            seed_mock_data(target)
        print("Đã tạo bảng" + (" và nạp dữ liệu mẫu." if "--seed" in sys.argv else "."))
    elif command == "reset-mock":
        target = _make_engine(settings.MOCK_DATABASE_URL)
        Base.metadata.create_all(target)
        seed_mock_data(target, force=True)
        with Session(target) as s:
            s.execute(delete(UserPermission))
            s.execute(delete(AuditLog))
            s.commit()
        print("Đã nạp lại dữ liệu giả lập.")
    else:
        print("Cách dùng: python database.py init-db [--seed] | reset-mock")
