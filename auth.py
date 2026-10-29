"""Xác thực Active Directory (ldap3), phân quyền (nhóm AD + phân quyền nội bộ), CSRF."""
import logging
import secrets

from fastapi import Depends, HTTPException, Request
from ldap3 import SIMPLE, SUBTREE, Connection, Server
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars
from pydantic import ValidationError
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from mock_data import MOCK_USERS
from models import HQ_ROLES, ADIdentity, CurrentUser, Role, UserPermission

logger = logging.getLogger("dq.auth")

# OID LDAP_MATCHING_RULE_IN_CHAIN: tìm cả nhóm lồng nhau
_IN_CHAIN = "1.2.840.113556.1.4.1941"


class AuthError(Exception):
    """Đăng nhập / truy cập bị từ chối; message hiển thị trực tiếp cho người dùng."""


class NotAuthenticated(Exception):
    """Chưa đăng nhập hoặc session hết hạn (main.py chuyển hướng về /login)."""


# --------------------------------------------------------------------------- #
# Phân quyền
# --------------------------------------------------------------------------- #
def group_cn(dn: str) -> str:
    """'CN=DQ_ADMIN,OU=Groups,DC=corp,DC=local' -> 'DQ_ADMIN'."""
    first = dn.split(",", 1)[0].strip()
    return first[3:] if first.upper().startswith("CN=") else first


def group_roles() -> list[tuple[str, Role]]:
    """(nhóm AD, vai trò) theo thứ tự ưu tiên khi user thuộc nhiều nhóm."""
    return [(settings.LDAP_GROUP_ADMIN, Role.ADMIN), (settings.LDAP_GROUP_APPROVER, Role.APPROVER),
            (settings.LDAP_GROUP_BUSINESS, Role.BUSINESS_APPROVER), (settings.LDAP_GROUP_MANAGER, Role.BRANCH_MANAGER),
            (settings.LDAP_GROUP_USER, Role.BRANCH_USER)]


def role_from_groups(groups: list[str]) -> Role | None:
    names = {g.upper() for g in groups}
    return next((role for group, role in group_roles() if group.upper() in names), None)


def resolve_user(db: Session, identity: ADIdentity) -> CurrentUser:
    """Quyền hiệu lực: phân quyền nội bộ (nếu có) ghi đè quyền theo nhóm AD."""
    perm = db.get(UserPermission, identity.username)
    if perm is not None:
        if not perm.is_active:
            raise AuthError("Tài khoản đã bị khóa quyền truy cập DQ Dashboard.")
        role = Role(perm.role)
        branch_code = perm.branch_code or identity.branch_code
        all_branches = perm.all_branches
        source = "Nội bộ"
    else:
        role = role_from_groups(identity.groups)
        if role is None:
            raise AuthError(
                f"Tài khoản không thuộc nhóm {', '.join(g for g, _ in group_roles())} và chưa được phân quyền. "
                "Vui lòng liên hệ quản trị hệ thống."
            )
        branch_code = identity.branch_code
        # Nhóm phê duyệt QTDL / nghiệp vụ trên AD mặc định là bộ phận Hội sở, xem được toàn hệ thống
        all_branches = role in HQ_ROLES
        source = "AD"

    if role == Role.ADMIN:
        all_branches = True
    elif role in (Role.BRANCH_USER, Role.BRANCH_MANAGER):
        all_branches = False
    if not all_branches and not branch_code:
        raise AuthError("Tài khoản chưa được gán Mã chi nhánh.")
    return CurrentUser(username=identity.username, display_name=identity.display_name, email=identity.email,
                       role=role, branch_code=branch_code, all_branches=all_branches,
                       groups=identity.groups, permission_source=source)


def normalize_username(raw: str) -> str:
    """Chấp nhận 'user', 'CORP\\user' hoặc 'user@corp.local' -> 'user'."""
    name = raw.strip()
    if "\\" in name:
        name = name.split("\\", 1)[1]
    if "@" in name:
        name = name.split("@", 1)[0]
    return name.lower()


# --------------------------------------------------------------------------- #
# Xác thực AD
# --------------------------------------------------------------------------- #
def authenticate(raw_username: str, password: str) -> ADIdentity:
    username = normalize_username(raw_username)
    # Bắt buộc: AD cho phép "unauthenticated bind" khi mật khẩu rỗng -> luôn thành công
    if not username or not password:
        raise AuthError("Vui lòng nhập tên đăng nhập và mật khẩu.")
    return _mock_authenticate(username, password) if settings.MOCK_LDAP else _ldap_authenticate(username, password)


def _mock_authenticate(username: str, password: str) -> ADIdentity:
    entry = MOCK_USERS.get(username)
    if not entry or entry["password"] != password:
        raise AuthError("Sai tên đăng nhập hoặc mật khẩu.")
    return ADIdentity(username=username, display_name=entry["display_name"], email=entry["email"],
                      branch_code=entry["branch_code"], groups=sorted(group_cn(dn) for dn in entry["member_of"]))


def _first(attrs: dict, name: str) -> str | None:
    values = attrs.get(name) or []
    if isinstance(values, (list, tuple)):
        return str(values[0]) if values else None
    return str(values)


def _ldap_authenticate(username: str, password: str) -> ADIdentity:
    server = Server(settings.LDAP_SERVER, port=settings.LDAP_PORT, use_ssl=settings.LDAP_USE_SSL,
                    connect_timeout=settings.LDAP_TIMEOUT)
    bind_user = f"{username}@{settings.LDAP_UPN_SUFFIX}"
    branch_attr = settings.LDAP_BRANCH_ATTRIBUTE
    try:
        # Bind bằng chính tài khoản người dùng -> không cần lưu service account
        with Connection(server, user=bind_user, password=password, authentication=SIMPLE,
                        auto_bind=True, receive_timeout=settings.LDAP_TIMEOUT) as conn:
            conn.search(
                search_base=settings.LDAP_BASE_DN,
                search_filter=f"(&(objectClass=user)(sAMAccountName={escape_filter_chars(username)}))",
                search_scope=SUBTREE,
                attributes=["displayName", "mail", "memberOf", branch_attr],
            )
            if not conn.entries:
                raise AuthError("Không tìm thấy tài khoản trong Active Directory.")
            entry = conn.entries[0]
            attrs = entry.entry_attributes_as_dict
            user_dn = entry.entry_dn

            if settings.LDAP_NESTED_GROUPS:
                conn.search(
                    search_base=settings.LDAP_BASE_DN,
                    search_filter=f"(&(objectClass=group)(member:{_IN_CHAIN}:={escape_filter_chars(user_dn)}))",
                    search_scope=SUBTREE,
                    attributes=["cn"],
                )
                groups = [str(g.cn) for g in conn.entries]
            else:
                groups = [group_cn(dn) for dn in attrs.get("memberOf", [])]
    except LDAPBindError:
        raise AuthError("Sai tên đăng nhập hoặc mật khẩu.")
    except LDAPException:
        logger.exception("Lỗi kết nối LDAP tới %s", settings.LDAP_SERVER)
        raise AuthError("Không kết nối được máy chủ Active Directory. Vui lòng thử lại sau.")

    branch = (_first(attrs, branch_attr) or "").strip().upper() or None
    return ADIdentity(username=username, display_name=_first(attrs, "displayName") or username,
                      email=_first(attrs, "mail"), branch_code=branch, groups=sorted(groups))


# --------------------------------------------------------------------------- #
# Session, dependency phân quyền, CSRF
# --------------------------------------------------------------------------- #
def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    """Dependency: quyền được tính lại mỗi request -> khóa / đổi quyền có hiệu lực ngay."""
    data = request.session.get("identity")
    if not data:
        raise NotAuthenticated()
    try:
        return resolve_user(db, ADIdentity.model_validate(data))
    except (ValidationError, AuthError) as exc:
        request.session.clear()
        if isinstance(exc, AuthError):
            request.session["flash"] = [{"category": "danger", "message": str(exc)}]
        raise NotAuthenticated()


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Chức năng chỉ dành cho Quản trị DQ.")
    return user


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = request.session["csrf"] = secrets.token_urlsafe(32)
    return token


async def verify_csrf(request: Request) -> None:
    """Dependency cho mọi POST thay đổi dữ liệu (form phải có trường csrf_token)."""
    form = await request.form()
    sent = str(form.get("csrf_token") or "")
    expected = request.session.get("csrf") or ""
    if not expected or not secrets.compare_digest(sent, expected):
        raise HTTPException(status_code=403, detail="Phiên làm việc không hợp lệ, vui lòng tải lại trang.")
