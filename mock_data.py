"""Dữ liệu giả lập: lỗi DQ, danh mục quy tắc, yêu cầu loại trừ và tài khoản AD dùng khi chạy offline / dev."""
import random
from datetime import date, datetime, time, timedelta

from config import settings
from models import APPROVAL_LEVELS, ExclusionSource, ExclusionStatus, Severity, Status

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


EXCLUSION_REASONS = [
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
UPLOAD_FILES = ["loai_tru_thang_{:02d}.xlsx", "LT_{}_dot{}.xlsx"]


def _branch_user(branch_code: str) -> str:
    """Tên tài khoản giả lập của user chi nhánh (khớp MOCK_USERS cho HN001/HCM01)."""
    return {"HN001": "hn.user", "HCM01": "hcm.user"}.get(branch_code, f"{branch_code.lower()}.user")


def _branch_manager(branch_code: str) -> str:
    """Tên tài khoản giả lập của Lãnh đạo phòng ban chi nhánh (khớp MOCK_USERS cho HN001/HCM01)."""
    return {"HN001": "hn.manager", "HCM01": "hcm.manager"}.get(branch_code, f"{branch_code.lower()}.manager")


def mock_rules() -> list[dict]:
    """Danh mục mã quy tắc ban đầu cho chế độ giả lập (thật thì admin upload)."""
    return [{"rule_code": code, "rule_name": name, "is_active": True, "updated_by": "system",
             "updated_at": datetime.now()} for code, name, _ in DQ_RULES]


def _at(day: date, rng: random.Random) -> datetime:
    return datetime.combine(day, time(rng.randint(8, 17), rng.randint(0, 59)))


def generate_dq_errors(n: int = 480, seed: int = 42, today: date | None = None) -> list[dict]:
    return generate_mock_dataset(n, seed, today)[0]


def _record_ref(rule_code: str, rng: random.Random) -> tuple[str, str]:
    """(nhãn hiển thị trong mô tả lỗi, mã bản ghi dùng cho yêu cầu loại trừ)."""
    if rule_code.startswith("DQ_ACC"):
        key = str(rng.randint(10**11, 10**12 - 1))
        return f"TK {key}", key
    if rule_code.startswith("DQ_LN"):
        key = f"LD{rng.randint(100000, 999999)}"
        return f"HĐ {key}", key
    key = str(rng.randint(10_000_000, 99_999_999))
    return f"CIF {key}", key


def generate_mock_dataset(n: int = 480, seed: int = 42,
                          today: date | None = None) -> tuple[list[dict], list[dict]]:
    """Sinh (lỗi DQ, yêu cầu loại trừ) ổn định theo seed. Một phần lỗi còn mở có yêu cầu loại trừ cho đúng bản ghi."""
    rng = random.Random(seed)
    today = today or date.today()
    owners = {code: rng.sample(OWNER_NAMES, 3) for code, _ in BRANCHES}
    severities = list(Severity)

    rows: list[dict] = []
    exclusions: list[dict] = []
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

        ref, record_key = _record_ref(rule_code, rng)
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
            req = _mock_exclusion(row, record_key, age_days, today, rng)
            if req:
                exclusions.append(req)
        rows.append(row)
    return rows, exclusions


def _pick_outcome(rng: random.Random) -> ExclusionStatus | None:
    roll = rng.random()
    for status, upto in ((ExclusionStatus.APPROVED, 0.12), (ExclusionStatus.PENDING_MANAGER, 0.17),
                         (ExclusionStatus.PENDING_BUSINESS, 0.21), (ExclusionStatus.PENDING_DQ, 0.24),
                         (ExclusionStatus.REJECTED, 0.28), (ExclusionStatus.CANCELLED, 0.30)):
        if roll < upto:
            return status
    return None


def _level_approver(key: str, branch_code: str) -> tuple[str, str]:
    return {"manager": (_branch_manager(branch_code), "Lãnh đạo phòng " + branch_code),
            "business": ("business", "Võ Nghiệp Vụ"),
            "dq": ("approver", "Phạm Phê Duyệt")}[key]


def _mock_exclusion(row: dict, record_key: str, age_days: int, today: date, rng: random.Random) -> dict | None:
    """Yêu cầu loại trừ đi qua các cấp duyệt tương ứng với trạng thái kết quả (lịch sử nhất quán)."""
    outcome = _pick_outcome(rng)
    if outcome is None:
        return None
    requested = row["detected_date"] + timedelta(days=rng.randint(1, max(1, age_days - 2)))
    from_excel = rng.random() < 0.6
    upload_file = (rng.choice(UPLOAD_FILES).format(requested.month, row["branch_code"], rng.randint(1, 3))
                   if from_excel else None)
    req = {
        "branch_code": row["branch_code"],
        "rule_code": row["rule_code"],
        "record_key": record_key,
        "reason": rng.choice(EXCLUSION_REASONS),
        # Hiệu lực 1-6 tháng kể từ ngày gửi (một số đã hết hạn)
        "valid_to": requested + timedelta(days=rng.randint(30, 180)),
        "source": (ExclusionSource.EXCEL if from_excel else ExclusionSource.MANUAL).value,
        "upload_file": upload_file,
        "status": outcome.value,
        "requested_by": _branch_user(row["branch_code"]),
        "requested_by_name": row["owner"],
        "requested_at": _at(requested, rng),
        "decided_by": None, "decided_by_name": None, "decided_at": None, "decision_note": None,
    }
    # Số cấp đã duyệt xong, và cấp từ chối (nếu bị từ chối)
    pending_levels = [lv.pending for lv in APPROVAL_LEVELS]
    if outcome in pending_levels:
        n_done, reject_at = pending_levels.index(outcome), None
    elif outcome == ExclusionStatus.REJECTED:
        reject_at = rng.randrange(len(APPROVAL_LEVELS))
        n_done = reject_at
    elif outcome == ExclusionStatus.APPROVED:
        n_done, reject_at = len(APPROVAL_LEVELS), None
    else:  # Đã hủy khi còn chờ cấp đầu
        n_done, reject_at = 0, None

    now = datetime.now()
    at = req["requested_at"]
    for lv in APPROVAL_LEVELS[:n_done]:
        at = min(at + timedelta(hours=rng.randint(2, 30)), now)
        by, name = _level_approver(lv.key, row["branch_code"])
        req.update({f"{lv.key}_by": by, f"{lv.key}_by_name": name, f"{lv.key}_at": at})
    if outcome == ExclusionStatus.APPROVED:
        req.update(decided_by="approver", decided_by_name="Phạm Phê Duyệt", decided_at=at)
    elif outcome == ExclusionStatus.REJECTED:
        lv = APPROVAL_LEVELS[reject_at]
        by, name = _level_approver(lv.key, row["branch_code"])
        at = min(at + timedelta(hours=rng.randint(2, 30)), now)
        req.update(decided_by=by, decided_by_name=name, decided_at=at,
                   decision_note=f"[Từ chối cấp {lv.label} - {by} {at:%d/%m/%Y %H:%M}] {rng.choice(REJECT_NOTES)}")
    elif outcome == ExclusionStatus.CANCELLED:
        req.update(decided_by=req["requested_by"], decided_by_name=row["owner"],
                   decided_at=min(at + timedelta(hours=rng.randint(1, 20)), now))
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
    "business": {
        "password": "Business@123",
        "display_name": "Võ Nghiệp Vụ",
        "email": "business@corp.local",
        "branch_code": "HO",
        "member_of": [_group_dn(settings.LDAP_GROUP_BUSINESS), _group_dn("Domain Users")],
    },
    "hn.manager": {
        "password": "Manager@123",
        "display_name": "Lãnh đạo phòng HN001",
        "email": "manager.hn@corp.local",
        "branch_code": "HN001",
        "member_of": [_group_dn(settings.LDAP_GROUP_MANAGER), _group_dn("Domain Users")],
    },
    "hcm.manager": {
        "password": "Manager@123",
        "display_name": "Lãnh đạo phòng HCM01",
        "email": "manager.hcm@corp.local",
        "branch_code": "HCM01",
        "member_of": [_group_dn(settings.LDAP_GROUP_MANAGER), _group_dn("Domain Users")],
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
