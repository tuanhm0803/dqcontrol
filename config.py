"""Cấu hình ứng dụng: đọc từ biến môi trường hoặc file .env (nếu có python-dotenv)."""
import logging
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:  # python-dotenv là tùy chọn
    pass

logger = logging.getLogger("dq.config")


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = _env(name)
    return int(value) if value else default


class Settings:
    def __init__(self) -> None:
        # ---- Ứng dụng ----
        self.APP_NAME = _env("APP_NAME", "DQ Dashboard")
        self.DEBUG = _bool("DEBUG", False)
        self.LOG_LEVEL = _env("LOG_LEVEL", "INFO")

        # ---- Session ----
        secret = _env("SECRET_KEY")
        self.SECRET_KEY_GENERATED = secret is None
        # Không đặt SECRET_KEY -> sinh ngẫu nhiên, mọi session mất khi restart.
        self.SECRET_KEY = secret or secrets.token_urlsafe(48)
        self.SESSION_MAX_AGE = _int("SESSION_MAX_AGE", 8 * 3600)  # 8 giờ làm việc
        self.SESSION_HTTPS_ONLY = _bool("SESSION_HTTPS_ONLY", False)

        # ---- Active Directory / LDAP ----
        self.MOCK_LDAP = _bool("MOCK_LDAP", True)
        self.LDAP_SERVER = _env("LDAP_SERVER", "dc01.corp.local")
        self.LDAP_USE_SSL = _bool("LDAP_USE_SSL", True)  # LDAPS (636) - khuyến nghị
        self.LDAP_PORT = _int("LDAP_PORT", 636 if self.LDAP_USE_SSL else 389)
        self.LDAP_UPN_SUFFIX = _env("LDAP_UPN_SUFFIX", "corp.local")  # user@corp.local
        self.LDAP_BASE_DN = _env("LDAP_BASE_DN", "DC=corp,DC=local")
        self.LDAP_TIMEOUT = _int("LDAP_TIMEOUT", 5)
        # Thuộc tính AD chứa Mã chi nhánh của user (vd: physicalDeliveryOfficeName,
        # department, extensionAttribute1...)
        self.LDAP_BRANCH_ATTRIBUTE = _env("LDAP_BRANCH_ATTRIBUTE", "physicalDeliveryOfficeName")
        # Có duyệt nhóm lồng nhau (nested group) hay không
        self.LDAP_NESTED_GROUPS = _bool("LDAP_NESTED_GROUPS", False)
        self.LDAP_GROUP_ADMIN = _env("LDAP_GROUP_ADMIN", "DQ_ADMIN")
        self.LDAP_GROUP_USER = _env("LDAP_GROUP_USER", "DQ_USER")
        self.LDAP_GROUP_APPROVER = _env("LDAP_GROUP_APPROVER", "DQ_APPROVER")

        # ---- Database ----
        # MOCK_DB được giữ làm tên thay thế cho USE_MOCK_DATA.
        # Chế độ mock dùng một file SQLite riêng, tự tạo và nạp dữ liệu từ mock_data.py
        # (cần CSDL ghi được cho luồng phê duyệt ngoại lệ và phân quyền).
        self.USE_MOCK_DATA = _bool("USE_MOCK_DATA", _bool("MOCK_DB", True))
        self.MOCK_DATABASE_URL = _env("MOCK_DATABASE_URL", "sqlite:///./dq_mock.db")
        # Không kết nối được CSDL thật -> tự chuyển sang dữ liệu giả lập
        self.DB_FALLBACK_TO_MOCK = _bool("DB_FALLBACK_TO_MOCK", True)
        # Ví dụ:
        #   SQL Server: mssql+pyodbc://user:pass@host:1433/DQ?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
        #   Oracle:     oracle+oracledb://user:pass@host:1521/?service_name=ORCLPDB1
        #   PostgreSQL: postgresql+psycopg2://user:pass@host:5432/dq
        #   SQLite:     sqlite:///./dq_demo.db
        self.DATABASE_URL = _env("DATABASE_URL", "sqlite:///./dq_demo.db")
        self.DQ_TABLE_NAME = _env("DQ_TABLE_NAME", "dq_errors")
        self.DQ_TABLE_SCHEMA = _env("DQ_TABLE_SCHEMA")
        # Schema cho các bảng của ứng dụng (ngoại lệ, phân quyền, nhật ký)
        self.APP_TABLE_SCHEMA = _env("APP_TABLE_SCHEMA")
        self.DB_ECHO = _bool("DB_ECHO", False)

        # ---- Hiển thị, xuất báo cáo, phê duyệt ----
        self.PAGE_SIZE = _int("PAGE_SIZE", 25)
        self.EXPORT_MAX_ROWS = _int("EXPORT_MAX_ROWS", 100_000)
        self.EXCEPTION_REASON_MIN_LENGTH = _int("EXCEPTION_REASON_MIN_LENGTH", 10)


settings = Settings()
