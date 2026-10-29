"""Kết nối CSDL (SQLAlchemy) và khởi tạo dữ liệu.

- USE_MOCK_DATA / MOCK_DB = True: dùng file SQLite MOCK_DATABASE_URL, tự tạo bảng và nạp dữ liệu
  từ mock_data.py ở lần chạy đầu (dữ liệu được giữ lại giữa các lần khởi động).
- USE_MOCK_DATA = False: kết nối DATABASE_URL (SQL Server / Oracle / PostgreSQL...), tự tạo các bảng
  của ứng dụng (danh mục quy tắc, yêu cầu loại trừ, phân quyền, nhật ký) nếu chưa có. Không kết nối được và
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
from mock_data import generate_mock_dataset, mock_rules
from models import APP_TABLES, AuditLog, Base, DQError, DQRule, ExclusionRequest, UserPermission

logger = logging.getLogger("dq.database")

SessionLocal = sessionmaker(expire_on_commit=False)
_state: dict = {"engine": None, "source": None}
_lock = threading.Lock()

# Bảng lỗi DQ thật chỉ dùng làm danh mục chi nhánh -> chỉ cần 2 cột này
REQUIRED_DQ_COLUMNS = {DQError.__table__.c.branch_code.name, DQError.__table__.c.branch_name.name}


def _make_engine(url: str) -> Engine:
    kwargs: dict = {"pool_pre_ping": True, "echo": settings.DB_ECHO}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def _count(s: Session, model) -> int:
    return s.scalar(select(func.count()).select_from(model)) or 0


def seed_mock_data(engine: Engine, force: bool = False) -> None:
    """Nạp lỗi DQ + yêu cầu loại trừ giả lập (khi bảng lỗi trống hoặc force) và danh mục quy tắc (khi trống)."""
    with Session(engine) as s:
        if force:
            for model in (ExclusionRequest, DQError, DQRule):
                s.execute(delete(model))
        if not _count(s, DQRule):
            s.add_all(DQRule(**r) for r in mock_rules())
            logger.info("Đã nạp danh mục mã quy tắc giả lập")
        if _count(s, DQError):
            s.commit()
            return
        errors, exclusions = generate_mock_dataset()
        s.add_all(DQError(**r) for r in errors)
        s.add_all(ExclusionRequest(**r) for r in exclusions)
        s.commit()
    logger.info("Đã nạp %d lỗi DQ và %d yêu cầu loại trừ giả lập", len(errors), len(exclusions))


def _missing_columns(engine: Engine, table) -> list[str]:
    insp = inspect(engine)
    if not insp.has_table(table.name, schema=table.schema):
        return []
    existing = {c["name"].lower() for c in insp.get_columns(table.name, schema=table.schema)}
    return sorted(c.name for c in table.columns if c.name.lower() not in existing)


def _init_mock() -> Engine:
    engine = _make_engine(settings.MOCK_DATABASE_URL)
    # File mock từ phiên bản cũ: bảng yêu cầu loại trừ thiếu cột (duyệt nhiều cấp) -> tạo lại bảng
    stale = bool(_missing_columns(engine, ExclusionRequest.__table__))
    if stale:
        ExclusionRequest.__table__.drop(engine)
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        # ... hoặc chưa có yêu cầu loại trừ nào (phiên bản luồng ngoại lệ) -> nạp lại toàn bộ
        stale = stale or (bool(_count(s, DQError)) and not _count(s, ExclusionRequest))
    if stale:
        logger.info("Dữ liệu giả lập thuộc phiên bản cũ -> nạp lại")
    seed_mock_data(engine, force=stale)
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
            "Xem mục 'Kết nối CSDL thật' trong README."
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
                # create_all không thêm cột vào bảng đã có -> báo rõ thay vì lỗi SQL khi chạy
                for table in APP_TABLES:
                    if missing := _missing_columns(engine, table):
                        raise RuntimeError(f"Bảng '{table.name}' thiếu cột {missing} (bảng tạo từ phiên bản cũ). "
                                           "Cần ALTER TABLE thêm cột, xem mục 'Kết nối CSDL thật' trong README.")
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
