"""Dữ liệu giả lập: lỗi DQ và tài khoản AD dùng khi chạy offline / dev."""
import random
from datetime import date, datetime, time, timedelta

from config import settings
from models import ExceptionStatus, Severity, Status

BRANCHES: list[tuple[str, str]] = [
    ("HN001", "Chi nhánh Hà Nội"),
    ("HN002", "Chi nhánh Hoàn Kiếm"),
    ("HCM01", "Chi nhánh TP. Hồ Chí Minh"),
    ("HCM02", "Chi nhánh Sài Gòn"),
    ("DN001", "Chi nhánh Đà Nẵng"),
    ("HP001", "Chi nhánh Hải Phòng"),
    ("CT001", "Chi nhánh Cần Thơ"),
    ("QN001", "Chi nhánh Quảng Ninh"),
    ("NA001", "Chi nhánh Nghệ An"),
    ("BD001", "Chi nhánh Bình Dương"),
]
# Chi nhánh lớn phát sinh nhiều lỗi hơn
BRANCH_WEIGHTS = [16, 8, 18, 10, 9, 7, 6, 5, 5, 8]

# (Mã quy tắc, Mô tả, Mức độ mặc định)
DQ_RULES: list[tuple[str, str, Severity]] = [
    ("DQ_CUS_001", "Thiếu số CMND/CCCD của khách hàng", Severity.HIGH),
    ("DQ_CUS_002", "Ngày sinh khách hàng lớn hơn ngày hiện tại", Severity.HIGH),
    ("DQ_CUS_003", "Số điện thoại di động sai định dạng", Severity.MEDIUM),
    ("DQ_CUS_004", "Email khách hàng sai định dạng", Severity.LOW),
    ("DQ_CUS_005", "Địa chỉ thường trú thiếu Tỉnh/Thành phố", Severity.MEDIUM),
    ("DQ_CUS_006", "Trùng CIF khách hàng (cùng số giấy tờ định danh)", Severity.HIGH),
    ("DQ_CUS_007", "Quốc tịch không thuộc danh mục ISO 3166", Severity.LOW),
    ("DQ_CORP_001", "Mã số thuế doanh nghiệp không đủ 10/13 chữ số", Severity.HIGH),
    ("DQ_CORP_002", "Thiếu thông tin người đại diện theo pháp luật", Severity.MEDIUM),
    ("DQ_CORP_003", "Mã ngành kinh tế không thuộc danh mục VSIC", Severity.LOW),
    ("DQ_ACC_001", "Tài khoản thanh toán không gắn mã CIF", Severity.HIGH),
    ("DQ_ACC_002", "Số dư âm bất thường trên tài khoản tiết kiệm", Severity.HIGH),
    ("DQ_LN_001", "Khoản vay thiếu thông tin tài sản đảm bảo", Severity.HIGH),
    ("DQ_LN_002", "Lãi suất cho vay nằm ngoài khung quy định", Severity.MEDIUM),
    ("DQ_LN_003", "Ngày đáo hạn nhỏ hơn ngày giải ngân", Severity.MEDIUM),
    ("DQ_LN_004", "Nhóm nợ không khớp với số ngày quá hạn", Severity.MEDIUM),
]

OWNER_NAMES = [
    "Nguyễn Văn An", "Trần Thị Bình", "Lê Minh Châu", "Phạm Quốc Dũng", "Hoàng Thu Hà",
    "Vũ Đức Huy", "Đặng Ngọc Lan", "Bùi Thanh Long", "Đỗ Thị Mai", "Ngô Gia Nam",
    "Dương Hải Phong", "Lý Thị Quỳnh", "Phan Văn Sơn", "Trịnh Thu Trang", "Đinh Công Vinh",
    "Mai Anh Tuấn", "Hồ Thị Yến", "Tạ Quang Khải", "Lương Bảo Ngọc", "Chu Minh Đức",
]


EXCEPTION_REASONS = [
    "Khách hàng nước ngoài, không có CCCD - đã lưu hộ chiếu thay thế",
    "Dữ liệu chuyển đổi từ hệ thống cũ, không còn hồ sơ gốc để bổ sung",
    "Khách hàng đã tất toán toàn bộ sản phẩm, không còn giao dịch",
    "Đã xác minh thực tế với khách hàng, thông tin đúng nhưng nằm ngoài quy tắc",
    "Khoản vay thuộc chương trình ưu đãi đặc thù đã được Hội sở phê duyệt",
]
REJECT_NOTES = [
    "Đề nghị bổ sung chứng từ chứng minh trước khi gửi lại",
    "Lý do chưa đủ cơ sở, chi nhánh cần liên hệ khách hàng cập nhật",
]


def _branch_user(branch_code: str) -> str:
    """Tên tài khoản giả lập của user chi nhánh (khớp MOCK_USERS cho HN001/HCM01)."""
    return {"HN001": "hn.user", "HCM01": "hcm.user"}.get(branch_code, f"{branch_code.lower()}.user")


def _at(day: date, rng: random.Random) -> datetime:
    return datetime.combine(day, time(rng.randint(8, 17), rng.randint(0, 59)))


def generate_dq_errors(n: int = 480, seed: int = 42, today: date | None = None) -> list[dict]:
    return generate_mock_dataset(n, seed, today)[0]


def generate_mock_dataset(n: int = 480, seed: int = 42,
                          today: date | None = None) -> tuple[list[dict], list[dict]]:
    """Sinh (lỗi DQ, yêu cầu ngoại lệ) ổn định theo seed, lịch sử nhất quán với trạng thái lỗi."""
    rng = random.Random(seed)
    today = today or date.today()
    owners = {code: rng.sample(OWNER_NAMES, 3) for code, _ in BRANCHES}
    severities = list(Severity)

    rows: list[dict] = []
    requests: list[dict] = []
    for i in range(1, n + 1):
        branch_code, branch_name = rng.choices(BRANCHES, weights=BRANCH_WEIGHTS)[0]
        rule_code, rule_desc, severity = rng.choice(DQ_RULES)
        if rng.random() < 0.15:  # đôi khi mức độ được đánh giá lại
            severity = rng.choice(severities)

        age_days = int(rng.triangular(0, 120, 7))
        # Lỗi càng cũ càng có khả năng đã xử lý xong
        p_done = min(0.85, age_days / 120 + 0.1)
        roll = rng.random()
        if roll < p_done:
            status = Status.DONE
        elif rng.random() < 0.4:
            status = Status.IN_PROGRESS
        else:
            status = Status.PENDING

        ref = f"CIF {rng.randint(10_000_000, 99_999_999)}"
        if rule_code.startswith("DQ_ACC"):
            ref = f"TK {rng.randint(10**11, 10**12 - 1)}"
        elif rule_code.startswith("DQ_LN"):
            ref = f"HĐ LD{rng.randint(100000, 999999)}"

        detected = today - timedelta(days=age_days)
        owner = rng.choice(owners[branch_code])
        row = {
            "id": i,
            "branch_code": branch_code,
            "branch_name": branch_name,
            "rule_code": rule_code,
            "description": f"{rule_desc} ({ref})",
            "severity": severity.value,
            "detected_date": detected,
            "status": status.value,
            "owner": owner,
            "resolved_date": None,
            "resolved_by": None,
        }
        if status == Status.DONE:
            row["resolved_date"] = detected + timedelta(days=rng.randint(0, age_days))
            row["resolved_by"] = _branch_user(branch_code)
        elif age_days >= 3:
            # Một phần lỗi còn mở đã đi qua luồng ngoại lệ (row được cập nhật trạng thái tương ứng)
            req = _mock_exception(row, age_days, today, rng)
            if req:
                requests.append(req)
        rows.append(row)
    return rows, requests


def _pick_outcome(rng: random.Random) -> ExceptionStatus | None:
    roll = rng.random()
    if roll < 0.10:
        return ExceptionStatus.APPROVED
    if roll < 0.18:
        return ExceptionStatus.PENDING
    if roll < 0.22:
        return ExceptionStatus.REJECTED
    return None


def _mock_exception(row: dict, age_days: int, today: date, rng: random.Random) -> dict | None:
    outcome = _pick_outcome(rng)
    if outcome is None:
        return None
    requested = row["detected_date"] + timedelta(days=rng.randint(1, max(1, age_days - 2)))
    decided = min(today, requested + timedelta(days=rng.randint(0, 2)))
    req = {
        "error_id": row["id"],
        "branch_code": row["branch_code"],
        "reason": rng.choice(EXCEPTION_REASONS),
        "previous_status": row["status"],
        "status": outcome.value,
        "requested_by": _branch_user(row["branch_code"]),
        "requested_by_name": row["owner"],
        "requested_at": _at(requested, rng),
        "decided_by": None, "decided_by_name": None, "decided_at": None, "decision_note": None,
    }
    if outcome == ExceptionStatus.PENDING:
        row["status"] = Status.EXCEPTION_PENDING.value
        return req
    req.update(decided_by="approver", decided_by_name="Phạm Phê Duyệt",
               decided_at=max(_at(decided, rng), req["requested_at"]))
    if outcome == ExceptionStatus.APPROVED:
        row.update(status=Status.EXCEPTION_APPROVED.value, resolved_date=decided, resolved_by="approver")
    else:
        req["decision_note"] = rng.choice(REJECT_NOTES)
    return req


def _group_dn(cn: str) -> str:
    return f"CN={cn},OU=Groups,DC=corp,DC=local"


# Tài khoản AD giả lập (MOCK_LDAP=True). member_of giữ dạng DN như AD thật trả về.
MOCK_USERS: dict[str, dict] = {
    "admin": {
        "password": "Admin@123",
        "display_name": "Nguyễn Quản Trị",
        "email": "admin@corp.local",
        "branch_code": "HO",
        "member_of": [_group_dn(settings.LDAP_GROUP_ADMIN), _group_dn("Domain Users")],
    },
    "approver": {
        "password": "Approver@123",
        "display_name": "Phạm Phê Duyệt",
        "email": "approver@corp.local",
        "branch_code": "HO",
        "member_of": [_group_dn(settings.LDAP_GROUP_APPROVER), _group_dn("Domain Users")],
    },
    "hn.user": {
        "password": "User@123",
        "display_name": "Trần Thị Hà",
        "email": "ha.tt@corp.local",
        "branch_code": "HN001",
        "member_of": [_group_dn(settings.LDAP_GROUP_USER), _group_dn("Domain Users")],
    },
    "hcm.user": {
        "password": "User@123",
        "display_name": "Lê Minh Khoa",
        "email": "khoa.lm@corp.local",
        "branch_code": "HCM01",
        "member_of": [_group_dn(settings.LDAP_GROUP_USER), _group_dn("Domain Users")],
    },
    # Không thuộc nhóm DQ nào -> bị từ chối truy cập
    "guest": {
        "password": "Guest@123",
        "display_name": "Khách",
        "email": "guest@corp.local",
        "branch_code": "DN001",
        "member_of": [_group_dn("Domain Users")],
    },
}
