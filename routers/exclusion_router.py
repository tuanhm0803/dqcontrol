"""Yêu cầu loại trừ: khai báo tay / upload Excel, phê duyệt, hủy, thu hồi, tra cứu, xuất file đã duyệt."""
import calendar
import logging
import math
import os
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth import get_current_user, verify_csrf
from config import settings
from database import get_db
from models import CurrentUser, ExclusionFilter, ExclusionSource, ExclusionStatus
from repository import list_branches, list_rules
from routers import flash, flash_result, redirect, safe_next, templates
from routers.dq_router import scoped_branches
from routers.exclusion_files import (UploadError, build_export_csv, build_export_excel, build_template,
                                     describe_filter, parse_upload)
from routers.export_router import XLSX_MIME, attachment
from workflow import (ExclusionInput, WorkflowError, audit, cancel_exclusion, create_exclusions, decide_blocker,
                      decide_exclusions, fetch_exclusions, list_exclusions, revoke_exclusion)

logger = logging.getLogger("dq.exclusions")
router = APIRouter(prefix="/exclusions", tags=["exclusions"])

TABS = {
    "pending": "Chờ tôi duyệt",
    "mine": "Yêu cầu của tôi",
    "all": "Tất cả / Lịch sử",
}
MAX_MANUAL_ROWS = 200
ROW_FIELDS = ("branch_code", "rule_code", "record_key", "reason", "valid_to")


def _clean(value: str | None, max_len: int = 100) -> str | None:
    return (value or "").strip()[:max_len] or None


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value.strip()) if value and value.strip() else None
    except ValueError:
        return None


def get_exclusion_filter(
    branch_code: str | None = None,
    rule_code: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    decided_from: str | None = None,
    decided_to: str | None = None,
    active_only: str | None = None,
) -> ExclusionFilter:
    """Bộ lọc từ query string; giá trị rỗng / không hợp lệ bị bỏ qua."""
    return ExclusionFilter(
        branch_code=(_clean(branch_code, 20) or "").upper() or None,
        rule_code=(_clean(rule_code, 50) or "").upper() or None,
        status=status if status in {s.value for s in ExclusionStatus} else None,
        keyword=_clean(keyword),
        decided_from=_date(decided_from),
        decided_to=_date(decided_to),
        active_only=bool(active_only),
    )


def _filter_params(f: ExclusionFilter) -> dict[str, str]:
    params = {k: (v.isoformat() if isinstance(v, date) else str(v))
              for k, v in vars(f).items() if v and k != "active_only"}
    if f.active_only:
        params["active_only"] = "1"
    return params


def _current_url(request: Request) -> str:
    return request.url.path + (f"?{request.url.query}" if request.url.query else "")


# --------------------------------------------------------------------------- #
# Danh sách
# --------------------------------------------------------------------------- #
@router.get("")
def exclusions_page(
    request: Request,
    tab: str | None = None,
    page: int = Query(1, ge=1),
    f: ExclusionFilter = Depends(get_exclusion_filter),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if tab not in TABS or (tab == "pending" and not user.can_approve):
        tab = "pending" if user.can_approve else "mine"
    page_size = settings.PAGE_SIZE
    items, total = list_exclusions(db, user, tab, f, page, page_size)
    return templates.TemplateResponse(request, "exclusions.html", {
        "user": user,
        "tabs": TABS,
        "tab": tab,
        "items": items,
        # Yêu cầu user được duyệt ngay (hiện checkbox); còn lại hiện lý do không duyệt được ở tooltip
        "blockers": {i.id: decide_blocker(user, i) for i in items},
        "total": total,
        "page": page,
        "pages": max(1, math.ceil(total / page_size)),
        "page_size": page_size,
        "params": {"tab": tab, **_filter_params(f)},
        "f": f,
        "branches": scoped_branches(db, user),
        "rules": list_rules(db, active_only=False),
        "current_url": _current_url(request),
        "today": date.today(),
    })


# --------------------------------------------------------------------------- #
# Khai báo: nhập tay / upload Excel
# --------------------------------------------------------------------------- #
def one_month_later(day: date) -> date:
    """Cùng ngày tháng sau (ngày 31/01 -> 28 hoặc 29/02): hạn hiệu lực mặc định của yêu cầu loại trừ."""
    year, month = (day.year + 1, 1) if day.month == 12 else (day.year, day.month + 1)
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def _render_new(request: Request, user: CurrentUser, db: Session, rows: list[dict] | None = None,
                status_code: int = 200):
    branches = list_branches(db)
    today = date.today()
    # Dòng mới: chi nhánh mặc định = chi nhánh của user (nếu có trong danh mục), hiệu lực mặc định 1 tháng
    defaults = {"branch_code": user.branch_code if user.branch_code in {c for c, _ in branches} else "",
                "valid_to": one_month_later(today).isoformat()}
    rules = list_rules(db)
    return templates.TemplateResponse(request, "exclusion_new.html", {
        "user": user,
        "branches": branches,
        "rules": rules,
        "rule_names": {code.upper(): name for code, name in rules},
        "defaults": defaults,
        # Mỗi dòng: dict theo ROW_FIELDS (+ "error" khi gửi lỗi). Mặc định 3 dòng mới.
        "rows": rows or [defaults for _ in range(3)],
        "today": today,
        "max_manual_rows": MAX_MANUAL_ROWS,
        "max_rows": settings.EXCLUSION_UPLOAD_MAX_ROWS,
        "max_mb": settings.EXCLUSION_UPLOAD_MAX_MB,
    }, status_code=status_code)


@router.get("/new")
def new_page(request: Request, user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    if not user.can_request:
        flash(request, "Bạn không có quyền gửi yêu cầu loại trừ.", "danger")
        return redirect("/exclusions")
    return _render_new(request, user, db)


def _posted_rows(*columns: list[str]) -> list[dict]:
    """Ghép các danh sách song song (theo ROW_FIELDS) thành dòng; bỏ dòng chưa nhập gì.
    Chi nhánh / hiệu lực có sẵn mặc định, nên dòng chỉ tính là có dữ liệu khi đã nhập quy tắc / mã / lý do."""
    n = max(len(c) for c in columns)
    rows = [{k: (c[i] if i < len(c) else "").strip() for k, c in zip(ROW_FIELDS, columns)} for i in range(n)]
    return [r for r in rows if r["rule_code"] or r["record_key"] or r["reason"]]


def _rows_to_items(rows: list[dict]) -> tuple[list[ExclusionInput], dict[str, str]]:
    """-> (dòng đưa vào workflow, lỗi định dạng theo label 'Dòng n')."""
    items: list[ExclusionInput] = []
    errors: dict[str, str] = {}
    for i, r in enumerate(rows, start=1):
        label, day = f"Dòng {i}", _date(r["valid_to"])
        if r["valid_to"] and day is None:
            errors[label] = "ngày hiệu lực không hợp lệ"
            continue
        items.append(ExclusionInput(label=label, branch_code=r["branch_code"] or None, rule_code=r["rule_code"],
                                    record_key=r["record_key"], reason=r["reason"], valid_to=day))
    return items, errors


@router.post("/new", dependencies=[Depends(verify_csrf)])
def submit_manual(
    request: Request,
    branch_code: list[str] = Form([]),
    rule_code: list[str] = Form([]),
    record_key: list[str] = Form([]),
    reason: list[str] = Form([]),
    valid_to: list[str] = Form([]),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Bảng nhiều dòng, mỗi dòng một yêu cầu. Các trường gửi lên là danh sách song song theo thứ tự dòng.
    Dòng lỗi được giữ lại trên form kèm lý do để sửa và gửi lại."""
    rows = _posted_rows(branch_code, rule_code, record_key, reason, valid_to)
    if not rows:
        flash(request, "Vui lòng nhập ít nhất một dòng yêu cầu loại trừ.", "danger")
        return _render_new(request, user, db, None, 400)
    if len(rows) > MAX_MANUAL_ROWS:
        flash(request, f"Tối đa {MAX_MANUAL_ROWS} dòng mỗi lần; số lượng lớn hơn hãy dùng upload Excel.", "danger")
        return _render_new(request, user, db, rows, 400)

    items, errors = _rows_to_items(rows)
    done = 0
    if items:
        try:
            result = create_exclusions(db, user, items, ExclusionSource.MANUAL)
        except WorkflowError as exc:
            flash(request, str(exc), "danger")
            return _render_new(request, user, db, rows, 400)
        done = result.done
        for msg in result.skipped:
            label, _, why = msg.partition(": ")
            errors[label] = why

    if done:
        flash(request, f"Đã gửi {done} yêu cầu loại trừ.")
    if not errors:
        return redirect("/exclusions?tab=mine")
    flash(request, f"Còn {len(errors)} dòng chưa gửi được - xem lý do ở từng dòng, sửa rồi gửi lại.", "warning")
    keep = [{**r, "error": errors[f"Dòng {i}"]} for i, r in enumerate(rows, start=1) if f"Dòng {i}" in errors]
    return _render_new(request, user, db, keep, 200 if done else 400)


@router.get("/template")
def download_template(user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    buf = build_template(list_branches(db), list_rules(db), user)
    return StreamingResponse(buf, media_type=XLSX_MIME, headers=attachment("Mau_yeu_cau_loai_tru.xlsx"))


@router.post("/upload", dependencies=[Depends(verify_csrf)])
def upload(
    request: Request,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = os.path.basename(file.filename or "upload.xlsx")[:255]
    limit = settings.EXCLUSION_UPLOAD_MAX_MB * 1024 * 1024
    data = file.file.read(limit + 1)
    try:
        if not filename.lower().endswith(".xlsx"):
            raise UploadError("Chỉ nhận file Excel .xlsx (dùng file mẫu).")
        if len(data) > limit:
            raise UploadError(f"File vượt quá {settings.EXCLUSION_UPLOAD_MAX_MB} MB.")
        items, errors = parse_upload(data)
        result = create_exclusions(db, user, items, ExclusionSource.EXCEL, filename) if items else None
    except (UploadError, WorkflowError) as exc:
        flash(request, str(exc), "danger")
        return redirect("/exclusions/new")
    done = result.done if result else 0
    # Lỗi đọc file và lỗi nghiệp vụ gộp lại, sắp theo số dòng ("Dòng <n>: ...")
    skipped = sorted(errors + (result.skipped if result else []),
                     key=lambda s: int(s.split(":", 1)[0].removeprefix("Dòng ").strip() or 0))
    logger.info("Upload loại trừ %s bởi %s: %d dòng hợp lệ, %d bỏ qua", filename, user.username, done, len(skipped))
    if not done:
        flash(request, f"Không có dòng nào được gửi từ file '{filename}'.", "danger")
    flash_result(request, f"gửi yêu cầu loại trừ từ file '{filename}' cho", done, skipped, limit=10)
    return redirect("/exclusions?tab=mine" if done else "/exclusions/new")


# --------------------------------------------------------------------------- #
# Phê duyệt / từ chối / hủy / thu hồi
# --------------------------------------------------------------------------- #
def _decide(request: Request, ids: list[int], note: str, next: str, approve: bool,
            user: CurrentUser, db: Session):
    try:
        flash_result(request, "phê duyệt" if approve else "từ chối", *decide_exclusions(db, user, ids, approve, note))
    except WorkflowError as exc:
        flash(request, str(exc), "danger")
    return redirect(safe_next(next, "/exclusions"))


@router.post("/approve", dependencies=[Depends(verify_csrf)])
def approve(request: Request, ids: list[int] = Form([]), note: str = Form(""), next: str = Form("/exclusions"),
            user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _decide(request, ids, note, next, True, user, db)


@router.post("/reject", dependencies=[Depends(verify_csrf)])
def reject(request: Request, ids: list[int] = Form([]), note: str = Form(""), next: str = Form("/exclusions"),
           user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return _decide(request, ids, note, next, False, user, db)


@router.post("/{request_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel(request: Request, request_id: int, next: str = Form("/exclusions"),
           user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        cancel_exclusion(db, user, request_id)
        flash(request, f"Đã hủy yêu cầu loại trừ #{request_id}.")
    except WorkflowError as exc:
        flash(request, str(exc), "danger")
    return redirect(safe_next(next, "/exclusions"))


@router.post("/{request_id}/revoke", dependencies=[Depends(verify_csrf)])
def revoke(request: Request, request_id: int, note: str = Form(""), next: str = Form("/exclusions"),
           user: CurrentUser = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        revoke_exclusion(db, user, request_id, note)
        flash(request, f"Đã thu hồi yêu cầu loại trừ #{request_id}.")
    except WorkflowError as exc:
        flash(request, str(exc), "danger")
    return redirect(safe_next(next, "/exclusions"))


# --------------------------------------------------------------------------- #
# Xuất yêu cầu đã duyệt
# --------------------------------------------------------------------------- #
def _export_rows(db: Session, user: CurrentUser, f: ExclusionFilter, fmt: str):
    f.status = ExclusionStatus.APPROVED.value
    rows = fetch_exclusions(db, user, f, settings.EXPORT_MAX_ROWS + 1)
    truncated = len(rows) > settings.EXPORT_MAX_ROWS
    rows = rows[:settings.EXPORT_MAX_ROWS]
    audit(db, user.username, "EXCL_EXPORT", fmt.upper(), f"{describe_filter(f, user)}; {len(rows)} dòng")
    db.commit()
    return rows, truncated


def _export_name(ext: str, f: ExclusionFilter, user: CurrentUser) -> str:
    scope = "ToanHeThong" if user.all_branches and not f.branch_code else (f.branch_code or user.branch_code)
    return f"Loai_tru_da_duyet_{scope}_{datetime.now():%Y%m%d_%H%M%S}.{ext}"


@router.get("/export/excel")
def export_excel(f: ExclusionFilter = Depends(get_exclusion_filter), user: CurrentUser = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    rows, truncated = _export_rows(db, user, f, "xlsx")
    return StreamingResponse(build_export_excel(rows, user, f, truncated), media_type=XLSX_MIME,
                             headers=attachment(_export_name("xlsx", f, user)))


@router.get("/export/csv")
def export_csv(f: ExclusionFilter = Depends(get_exclusion_filter), user: CurrentUser = Depends(get_current_user),
               db: Session = Depends(get_db)):
    rows, _ = _export_rows(db, user, f, "csv")
    return StreamingResponse(build_export_csv(rows), media_type="text/csv; charset=utf-8",
                             headers=attachment(_export_name("csv", f, user)))
