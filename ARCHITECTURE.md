# ARCHITECTURE.md – DQ Dashboard

> Tài liệu bàn giao cho AI / developer tiếp tục phát triển **mà không cần đọc lại toàn bộ repo**.
> Mô tả trạng thái code tại thời điểm viết (2026-10-26). Khi sửa kiến trúc, quy ước hoặc luồng nghiệp vụ,
> **hãy cập nhật file này cùng commit**. Hướng dẫn cho người dùng cuối nằm ở `README.md`.

---

## 1. Tổng quan

Web app nội bộ (LAN), dùng để theo dõi **lỗi Chất lượng Dữ liệu (DQ)** của các chi nhánh ngân hàng:

- Đăng nhập bằng Active Directory (ldap3), có chế độ giả lập `MOCK_LDAP`.
- Phân quyền 3 vai trò, lấy từ nhóm AD và có thể bị **phân quyền nội bộ** (lưu trong DB) ghi đè.
- Dashboard lọc / tìm kiếm / thống kê, cập nhật trạng thái xử lý hàng loạt.
- **Luồng yêu cầu → phê duyệt ngoại lệ** (maker-checker).
- Xuất Excel (openpyxl, 2 sheet) và CSV (pandas), áp đúng bộ lọc và phạm vi quyền.
- Nhật ký hệ thống (audit log).

Server-side rendering hoàn toàn: FastAPI + Jinja2 + Bootstrap 5.3.3 (CDN) + một ít JS thuần trong template.
Không có SPA, không build frontend.

**Ngôn ngữ:** giao diện, thông báo lỗi, log, comment và docstring đều bằng **tiếng Việt có dấu**.
Tên biến, hàm và bảng bằng tiếng Anh. Giữ nguyên quy ước này khi viết thêm code.

## 2. Môi trường & lệnh thường dùng

| Mục | Giá trị |
|---|---|
| Python | **3.13.5** cài trên máy (`C:\Users\PC\AppData\Local\Programs\Python\Python313\python.exe`), **không dùng venv**; gọi qua launcher `py -3.13` |
| Thư viện chính (đã test) | fastapi 0.162, starlette 1.10, SQLAlchemy 2.1.6, pydantic 2.14, pandas 3.1, openpyxl 3.1.5, ldap3 2.9.1, Jinja2 3.1.6, uvicorn 0.54 |
| OS dev | Windows 11; shell PowerShell 5.1 |

```powershell
py -3.13 -m pip install -r requirements.txt                 # cài thư viện vào Python 3.13 của máy
py -3.13 -m uvicorn main:app --host 0.0.0.0 --port 8080     # chạy (LAN)
py -3.13 database.py reset-mock                             # làm mới dữ liệu giả lập
py -3.13 database.py init-db --seed                         # tạo bảng + seed trên DATABASE_URL
```

- Cài offline cho máy không có Internet: thư mục `wheels/` (bị `.gitignore`) chứa wheel cho win_amd64 / cp313, `wheels/drivers/` chứa pyodbc, oracledb, psycopg2-binary. Lệnh tạo và cài: xem README mục *Cài offline*.
- **Chưa có thư mục test trong repo.** Các lần trước kiểm thử bằng một script end-to-end dùng `fastapi.testclient.TestClient`.
  Script đó đặt `MOCK_DATABASE_URL` trỏ tới file SQLite tạm, đăng nhập từng vai trò, lấy CSRF token bằng regex
  `name="csrf_token" value="..."` từ HTML, và đọc flash message từ HTML sau redirect. Nên tái tạo nó thành `tests/` (pytest) khi cần.
- Khi `uvicorn` đang chạy, Windows **khóa file `.pyd`** trong `site-packages` của Python 3.13, nên `pip install --upgrade` có thể lỗi. Phải dừng tiến trình trước.

## 3. Cấu trúc module & hướng import

```
config.py        Settings đọc env/.env (python-dotenv). Đối tượng toàn cục: settings, BASE_DIR
models.py        Enum + SQLAlchemy ORM + Pydantic schema + CurrentUser (chứa logic quyền)
mock_data.py     Sinh dữ liệu giả lập (seed=42) + MOCK_USERS (tài khoản AD giả)
database.py      Engine, SessionLocal, init_database(), get_db(), data_source(), seed, CLI
repository.py    Truy vấn đọc bảng lỗi DQ (search/fetch/stats/branches) + keyword_condition()
workflow.py      Nghiệp vụ GHI: update_status, luồng ngoại lệ, audit(), list/count yêu cầu
auth.py          Xác thực AD, resolve_user() (tính quyền), get_current_user, require_admin, CSRF
routers/__init__.py   templates (Jinja2), globals cho template, flash, safe_next, redirect, page_url
routers/auth_router.py      /login, /logout, /api/me
routers/dq_router.py        /, /dashboard, /dq/status, /api/dq-errors, get_filters(), scoped_branches()
routers/exception_router.py /exceptions/*
routers/admin_router.py     /admin/permissions/*
routers/export_router.py    /export/excel, /export/csv
main.py          App, middleware, exception handler, mount static, include routers, /health
templates/       base, login, dashboard, exceptions, admin_permissions, error, _pagination
static/css/app.css
```

**Hướng import một chiều; không được tạo vòng import:**

```
config → models → mock_data → database → repository → workflow → auth → routers/__init__ → routers/* → main
```

- `workflow.py` và `repository.py` **không được import** `auth` hay `routers`.
  Logic phân quyền cần dùng ở tầng nghiệp vụ được đặt thành method của `CurrentUser` trong `models.py`
  (`can_access`, `scope`, `can_edit`, `can_approve`, `is_admin`) chính là để tránh vòng import.
- `routers/__init__.py` import `auth.csrf_token` và `workflow.count_pending_for` để đăng ký làm Jinja globals.
- `export_router` và `exception_router` dùng lại `get_filters` và `scoped_branches` từ `dq_router`.

## 4. Mô hình dữ liệu (`models.py`)

### 4.1 Enum. Giá trị chuỗi tiếng Việt chính là giá trị LƯU TRONG DB

```python
Severity: "High" | "Medium" | "Low"
Status (cột dq_errors.status):
    PENDING="Chưa xử lý", IN_PROGRESS="Đang xử lý", DONE="Hoàn thành",
    EXCEPTION_PENDING="Chờ duyệt ngoại lệ", EXCEPTION_APPROVED="Ngoại lệ đã duyệt"
MANUAL_STATUSES             = (PENDING, IN_PROGRESS, DONE)      # user tự đặt được
EXCEPTION_ELIGIBLE_STATUSES = (PENDING, IN_PROGRESS)            # được gửi ngoại lệ
CLOSED_STATUSES             = (DONE, EXCEPTION_APPROVED)        # có resolved_date
EXCEPTION_STATUSES          = (EXCEPTION_PENDING, EXCEPTION_APPROVED)  # bị khóa, chỉ đổi qua luồng duyệt
ExceptionStatus (cột dq_exception_requests.status):
    "Chờ duyệt" | "Đã duyệt" | "Từ chối" | "Đã hủy" | "Đã thu hồi"
Role: "admin" | "approver" | "branch_user"   (ROLE_LABELS: tên hiển thị tiếng Việt)
```

⚠️ **Template so sánh trực tiếp với chuỗi literal**, ví dụ `r.status == 'Chờ duyệt'` và
`locked_statuses = ['Chờ duyệt ngoại lệ', 'Ngoại lệ đã duyệt']` trong `dashboard.html`, hay `stats.by_status.get('Hoàn thành')`.
Khi đổi hoặc thêm giá trị enum phải `grep` cả `templates/`. Xem thêm §11.

### 4.2 Bảng

| Bảng | Sở hữu | Ghi chú |
|---|---|---|
| `dq_errors` (tên lấy từ `DQ_TABLE_NAME`, schema từ `DQ_TABLE_SCHEMA`) | Hệ thống DQ bên ngoài; app **đọc + update** | Cột: `id` PK Identity, `branch_code`, `branch_name`, `rule_code`, `description`, `severity`, `detected_date`, `status`, `owner`, **`resolved_date`**, **`resolved_by`** (2 cột cuối do app ghi). App **không bao giờ INSERT** dòng lỗi, trừ khi seed. |
| `dq_exception_requests` | App | `error_id` (không có FK, cố ý), `branch_code` (lưu lặp để lọc phạm vi), `reason`, **`previous_status`** (để khôi phục), `status`, `requested_by`/`_name`/`_at`, `decided_by`/`_name`/`_at`, `decision_note` |
| `dq_user_permissions` | App | PK `username` (chữ thường, không có domain). `role`, `branch_code` (NULL = dùng chi nhánh từ AD), `all_branches`, `is_active`, `note`, `updated_by`, `updated_at` |
| `dq_audit_log` | App | `at`, `username`, `action`, `target`, `detail` (cắt ở 2000 ký tự) |

`APP_TABLES` = 3 bảng của app, schema lấy từ `APP_TABLE_SCHEMA`; được `create_all` khi khởi động ở chế độ DB thật.
Tên cột DB của `DQError` là tham số đầu tiên của `mapped_column(...)`. Muốn map sang bảng thật có tên cột khác thì sửa ở đó,
còn tên thuộc tính Python giữ nguyên.

Datetime lưu dạng **naive local time** (`datetime.now()`); `resolved_date` lấy theo `date.today()`.

### 4.3 Schema Pydantic chính

- `DQErrorOut`: dữ liệu ra của một dòng lỗi (`from_attributes`).
- `DQFilter`: `branch_code`, `severity`, `status`, `keyword`, `date_from`, `date_to`. Có `to_query_params()` để giữ bộ lọc trên URL.
- `ExceptionRequestOut`: yêu cầu ngoại lệ, kèm `branch_name`, `rule_code`, `description`, `severity` lấy từ outer join với bảng lỗi.
- `UserPermissionOut`, `DQStats`, `PagedResult`.
- `ADIdentity`: thông tin AD lưu trong session (`username`, `display_name`, `email`, `branch_code`, `groups` là danh sách CN).
- **`CurrentUser`**: người dùng hiệu lực, gồm `role`, `branch_code`, `all_branches`, `permission_source` ("AD" | "Nội bộ").
  - Thuộc tính quyền: `is_admin`; `can_edit` (admin hoặc branch_user); `can_approve` (admin hoặc approver).
  - `can_access(branch)`: cho phép nếu xem toàn hệ thống, hoặc đúng chi nhánh của user.
  - `scope(filters)`: trả bộ lọc đã bị ép `branch_code` khi user không xem toàn hệ thống.
- `EXPORT_COLUMNS`: dict định nghĩa thứ tự và tiêu đề cột khi export.

## 5. Xác thực & phân quyền (`auth.py`)

### 5.1 Session (Starlette `SessionMiddleware`, cookie `dq_session`, ký bằng `SECRET_KEY`)

| Key | Nội dung |
|---|---|
| `identity` | `ADIdentity.model_dump(mode="json")`. **Chỉ lưu danh tính, KHÔNG lưu quyền** |
| `csrf` | Token sinh lười bằng `csrf_token(request)` |
| `flash` | `list[{"category", "message"}]`, được `pop_flashes` lấy ra trong `base.html` |

### 5.2 Luồng đăng nhập

1. `POST /login` gọi `authenticate()` trong threadpool (ldap3 là thư viện đồng bộ).
   - Hàm này chuẩn hóa username: `CORP\u`, `u@corp.local` đều thành `u`, chữ thường.
   - **Chặn mật khẩu rỗng** vì AD chấp nhận unauthenticated bind.
   - Kết quả là một `ADIdentity`.
2. Gọi `resolve_user(db, identity)` để kiểm tra quyền ngay lúc login. Không có quyền thì trả 401 và render lại `login.html`.
3. `session.clear()` (chống session fixation), lưu `identity`, ghi audit `LOGIN`.

Ở LDAP thật, app bind bằng chính tài khoản user (UPN `user@LDAP_UPN_SUFFIX`, SIMPLE, khuyến nghị LDAPS), rồi search theo `sAMAccountName`:
- Đọc các thuộc tính `displayName`, `mail`, `memberOf` và `LDAP_BRANCH_ATTRIBUTE`.
- Nếu `LDAP_NESTED_GROUPS=true` thì lấy nhóm bằng `LDAP_MATCHING_RULE_IN_CHAIN`.
- **Nhánh LDAP thật chưa từng được test với AD thật**; chỉ nhánh mock được test.

### 5.3 `resolve_user`: tính quyền hiệu lực, chạy ở MỖI request qua `get_current_user`

```
Có dòng dq_user_permissions(username)?
  ├─ is_active = False                 → AuthError "đã bị khóa"
  └─ có → role = perm.role; branch = perm.branch_code or AD branch; all_branches = perm.all_branches; source="Nội bộ"
Không có → role theo nhóm AD, ưu tiên: LDAP_GROUP_ADMIN > LDAP_GROUP_APPROVER > LDAP_GROUP_USER
           (không thuộc nhóm nào → AuthError); all_branches = role in (admin, approver); source="AD"
Sau đó ép buộc: admin → all_branches=True; branch_user → all_branches=False
Nếu không all_branches mà không có branch_code → AuthError
```

`get_current_user` khi gặp `AuthError` thì xóa session, đặt flash lỗi rồi raise `NotAuthenticated`.
`main.py` bắt exception này: với `/api/*` trả **401 JSON**, còn lại **redirect 303** tới `/login?next=<url hiện tại>`.
Nhờ đó khóa hoặc đổi quyền có hiệu lực ngay ở request kế tiếp.

### 5.4 Ma trận quyền và nơi kiểm tra

| Chức năng | admin | approver | branch_user | Kiểm tra tại |
|---|:-:|:-:|:-:|---|
| Xem dashboard / API / export | ✔ | ✔ | ✔ | `get_current_user` + `user.scope(filters)` |
| Cập nhật trạng thái, gửi ngoại lệ | ✔ | | ✔ | `user.can_edit` trong `workflow` |
| Hủy yêu cầu | người gửi hoặc admin | | | `workflow.cancel_request` |
| Duyệt / từ chối | ✔ | ✔ | | `user.can_approve` trong `workflow` |
| Thu hồi ngoại lệ đã duyệt | ✔ | | | `user.is_admin` trong `workflow.revoke_exception` |
| `/admin/*` | ✔ | | | dependency `require_admin` (trả 403 và render `error.html`) |

**Nguyên tắc: quyền LUÔN được kiểm tra ở `workflow.py` / query phía server.** Template chỉ ẩn hoặc hiện nút cho tiện.
Phạm vi chi nhánh được kiểm tra **từng dòng** bằng `user.can_access(row.branch_code)` cho thao tác ghi,
và bằng `user.scope(filters)` cho truy vấn đọc. Query `/exceptions` tự ép `branch_code` trong `_request_conditions`.

### 5.5 CSRF

- Mọi route POST thay đổi dữ liệu khai báo `dependencies=[Depends(verify_csrf)]`.
- Mọi form POST trong template phải có `<input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">`.
- `verify_csrf` đọc `await request.form()` (Starlette cache lại form nên không xung đột với các tham số `Form(...)`) và so sánh bằng `secrets.compare_digest`.
- Sai token thì trả 403.
- **Ngoại lệ:** `POST /login` không có CSRF vì chưa có session.

## 6. Nghiệp vụ (`workflow.py`)

### 6.1 Máy trạng thái

```
Chưa xử lý ⇄ Đang xử lý → Hoàn thành            (update_status; DONE ghi resolved_date/by, trạng thái khác xóa)
Chưa xử lý | Đang xử lý ──request_exceptions──▶ Chờ duyệt ngoại lệ   (tạo ExceptionRequest, previous_status = trạng thái cũ)
Chờ duyệt ngoại lệ ──decide(approve)──▶ Ngoại lệ đã duyệt          (resolved_date = hôm nay, resolved_by = người duyệt)
Chờ duyệt ngoại lệ ──decide(reject, note bắt buộc) / cancel_request──▶ previous_status (xóa resolved_*)
Ngoại lệ đã duyệt ──revoke_exception (admin, note bắt buộc)──▶ previous_status (yêu cầu → "Đã thu hồi", note nối vào decision_note)
```

Các bất biến phải giữ:

- Dòng có trạng thái thuộc `EXCEPTION_STATUSES` **không được** đổi qua `update_status`.
- `resolved_date` khác NULL **khi và chỉ khi** status thuộc `CLOSED_STATUSES`. Đã kiểm tra trên toàn bộ dữ liệu seed.
- Mỗi lỗi có tối đa một yêu cầu đang "Chờ duyệt". Điều này được đảm bảo gián tiếp: chỉ lỗi ở trạng thái eligible mới tạo được yêu cầu,
  và tạo xong thì lỗi chuyển sang `EXCEPTION_PENDING`.
- **Maker-checker:** `req.requested_by == user.username` thì bỏ qua, kể cả khi user là admin.
- Lý do gửi ngoại lệ phải có độ dài ít nhất `EXCEPTION_REASON_MIN_LENGTH` (mặc định 10).

### 6.2 Quy ước API của tầng nghiệp vụ

- Thao tác hàng loạt nhận `list[int]` id và trả `ActionResult(done: int, skipped: list[str])`.
  Mỗi phần tử `skipped` có dạng `"#<id>: <lý do tiếng Việt>"`. **Dòng không hợp lệ được bỏ qua, không làm hỏng cả lô.**
- Lỗi chặn toàn bộ thao tác (sai quyền, thiếu lý do, danh sách rỗng) thì raise `WorkflowError(message cho người dùng)`.
- Mỗi hàm tự `db.commit()`. Bản ghi được nạp bằng `with_for_update()` (SQLite bỏ qua, DB thật thì khóa dòng).
- Mỗi thay đổi đều gọi `audit(db, username, ACTION, target, detail)`, trong cùng transaction.
  Các action đang dùng: `LOGIN, STATUS_UPDATE, EXC_REQUEST, EXC_APPROVE, EXC_REJECT, EXC_CANCEL, EXC_REVOKE, PERM_UPSERT, PERM_DELETE, EXPORT`.
  **Thêm action mới thì nhớ thêm vào `AUDIT_ACTIONS` trong `admin_router.py`** để bộ lọc nhật ký hiển thị được.
  `target` theo dạng `DQ#<id>`, `NL#<id> / DQ#<id>`, hoặc username.
- `list_requests(db, user, tab, page, page_size, branch_code, status, keyword, error_id)` với `tab` là `pending`, `mine` hoặc `all`.
- `count_pending_for(user)` đếm số yêu cầu đang chờ mà user này duyệt được (đã trừ yêu cầu do chính user gửi). Dùng cho badge trên menu.

## 7. Routes

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| GET | `/login` | — | Form đăng nhập; đã có session thì redirect `next` |
| POST | `/login` | — | Form: `username`, `password`, `next` |
| POST | `/logout` | CSRF | Xóa session |
| GET | `/api/me` | login | `CurrentUser` JSON |
| GET | `/` | — | Redirect `/dashboard` |
| GET | `/dashboard` | login | Query: các trường `DQFilter` + `page` |
| POST | `/dq/status` | CSRF, `can_edit` | Form: `ids` (nhiều giá trị), `new_status`, `next` |
| GET | `/api/dq-errors` | login | JSON `PagedResult`; `page_size` ≤ 500 |
| GET | `/exceptions` | login | Query: `tab`, `branch_code`, `status`, `keyword`, `error_id`, `page`. Tab mặc định: approver → `pending`, còn lại → `mine` (hoặc `all` nếu có `error_id`) |
| POST | `/exceptions/request` | CSRF, `can_edit` | `ids`, `reason`, `next` |
| POST | `/exceptions/approve` · `/exceptions/reject` | CSRF, `can_approve` | `ids`, `note`, `next` |
| POST | `/exceptions/{id}/cancel` | CSRF | `next` |
| POST | `/exceptions/{id}/revoke` | CSRF, admin | `note`, `next` |
| GET | `/admin`, `/admin/permissions` | admin | Danh sách phân quyền + nhật ký (`action`, `keyword`, `page`; 50 dòng/trang) |
| POST | `/admin/permissions` | CSRF, admin | Thêm hoặc sửa (upsert): `username`, `display_name`, `role`, `branch_code`, `all_branches` (checkbox), `is_active` (checkbox), `note` |
| POST | `/admin/permissions/{username}/delete` | CSRF, admin | Xóa phân quyền nội bộ, user quay về quyền theo AD |
| GET | `/export/excel` · `/export/csv` | login | Cùng query với dashboard |
| GET | `/health` | — | `{"status","data_source"}` |
| GET | `/docs` | — | Chỉ có khi `DEBUG=true` |

**Mẫu xử lý POST (PRG):** gọi workflow → `flash_result(...)` hoặc `flash(...)` → `redirect(safe_next(next))` (303).
Hàm `safe_next` chỉ chấp nhận đường dẫn nội bộ (chống open redirect).
Form gửi nhiều giá trị cho một trường thì khai báo `ids: list[int] = Form([])`. **Không dùng** `Form(default_factory=...)`.

Các validation đặc biệt của admin (`_validate` trong `admin_router.py`):
- Username phải khớp `^[a-z0-9._-]{1,100}$`.
- Không được tự hạ quyền hoặc tự khóa; điều kiện này kiểm tra **trước tiên**. Không được tự xóa phân quyền của mình.
- Approver không xem toàn hệ thống thì bắt buộc có `branch_code`.

## 8. Giao diện (templates)

- **Chữ ký TemplateResponse:** luôn gọi `templates.TemplateResponse(request, "name.html", {...})` (Starlette mới).
  `request` tự có trong context.
- **Context bắt buộc:** trang cần menu thì phải truyền `user`. `base.html` chỉ render menu, khối thông tin user và nút đăng xuất khi `user` có giá trị.
- **Jinja globals** (đăng ký trong `routers/__init__.py`):
  - Dữ liệu và cấu hình: `app_name`, `mock_ldap`, `severities`, `statuses`, `exception_statuses`, `roles`, `reason_min_length`.
  - Class CSS cho badge: `severity_badge(v)`, `status_badge(v)`, `exception_badge(v)`.
  - Hàm tiện ích: `data_source()`, `csrf_token(request)`, `pop_flashes(request)`, `pending_exceptions(user)` (tự mở `SessionLocal` riêng), `page_url(path, params, page)`.
- **Phân trang:** `{% include "_pagination.html" %}`, cần `page`, `pages` và `params` (dict bộ lọc, không gồm `page`) trong context.
- **Chọn nhiều dòng** (JS chung ở cuối `base.html`), quy ước theo thuộc tính `data-group="<tên nhóm>"`:
  - `.row-check`: checkbox từng dòng; `.check-all`: ô chọn tất cả.
  - `.needs-selection`: nút tự disable khi chưa chọn dòng nào; `.selection-count`: hiển thị số dòng đã chọn.
  - Checkbox nằm trong bảng, **ngoài** form, gắn vào form bằng thuộc tính `form="bulkForm"` (dashboard, nhóm `err`)
    hoặc `form="decideForm"` (trang ngoại lệ, nhóm `req`).
  - Nhiều nút submit dùng chung một form và đổi đích bằng `formaction`.
- ⚠️ **Modal không được đặt trong phần tử sticky hoặc có z-index** (ví dụ `.bulk-bar`), vì lớp nền mờ sẽ che mất modal.
  Hãy đặt modal ngoài form và gắn các trường vào form bằng `form="..."`, như `#exceptionModal` trong `dashboard.html`.
- Kiểm tra phía trình duyệt (lý do ngoại lệ, ghi chú từ chối) dùng JS `preventDefault` và class `is-invalid`.
  **Không dùng `required`** cho trường nằm trong modal ẩn của form có nhiều nút submit, vì trình duyệt sẽ chặn cả các nút submit khác.
  Server luôn kiểm tra lại.
- Màu sắc: `--dq-primary #1f4e78` (`.bg-dq`, `.btn-dq`); trạng thái "Ngoại lệ đã duyệt" dùng màu tím `.badge-exception` / `.bg-exception`.
- Bootstrap và Bootstrap Icons được tải từ **CDN jsdelivr**. Nếu LAN không ra được Internet thì phải tải về `static/` và sửa `base.html`.

## 9. Export (`routers/export_router.py`)

- Cả hai định dạng dùng `get_filters`, sau đó `user.scope(...)`, rồi `fetch_errors(limit = EXPORT_MAX_ROWS + 1)` để biết có bị cắt bớt hay không.
  Mỗi lần xuất đều ghi audit `EXPORT`.
- **Excel**, gồm 2 sheet:
  - Sheet "Chi tiết lỗi DQ":
    - Dòng 1 là tiêu đề, dòng 2–5 là metadata (phạm vi, bộ lọc, người xuất, số bản ghi).
    - **Header ở dòng 7, dữ liệu từ dòng 8.** Có freeze pane, autofilter, tô màu cột mức độ.
    - Cột ngày (`DATE_COLUMNS`) dùng định dạng `DD/MM/YYYY`; độ rộng cột lấy từ `COLUMN_WIDTHS`.
  - Sheet "Tổng hợp": crosstab chi nhánh × mức độ bằng pandas, dòng cuối là công thức `SUM`.
- **CSV:** mã hóa UTF-8 **có BOM** (`utf-8-sig`) để Excel mở đúng tiếng Việt; ngày ở dạng `dd/mm/YYYY`.
- Tên file: `DQ_Report_<ToanHeThong|BRANCH>_<yyyymmdd_HHMMSS>.<ext>`.
- Thêm cột export: thêm vào `EXPORT_COLUMNS` (models). Nếu là cột ngày thì thêm vào `DATE_COLUMNS`; chỉnh độ rộng ở `COLUMN_WIDTHS`.

## 10. CSDL & khởi tạo (`database.py`)

- `init_database()` chạy một lần (có khóa luồng). Được gọi trong lifespan của `main.py` và lười trong `get_db()`.
- **Chế độ mock** (`USE_MOCK_DATA=true`, hoặc `MOCK_DB=true`, mặc định):
  - Dùng file SQLite `MOCK_DATABASE_URL` (mặc định `./dq_mock.db`), `create_all` toàn bộ bảng.
  - Lần đầu sẽ seed từ `mock_data.generate_mock_dataset()`: 480 lỗi, 10 chi nhánh, 16 quy tắc,
    53 yêu cầu ngoại lệ (29 đã duyệt, 19 chờ duyệt, 5 từ chối), nhất quán với trạng thái lỗi.
  - **Dữ liệu được giữ lại giữa các lần chạy**; muốn làm mới thì chạy `reset-mock`.
- **Chế độ DB thật:**
  - Kết nối `DATABASE_URL`, sau đó `_check_dq_table`: bảng phải tồn tại và có đủ cột của `DQError`, gồm `resolved_date` và `resolved_by`.
  - Tiếp theo `create_all(tables=APP_TABLES)`.
  - Lỗi ở bất kỳ bước nào: nếu `DB_FALLBACK_TO_MOCK=true` thì chuyển sang mock (log exception); nếu `false` thì raise.
- `data_source()` trả `"mock"` hoặc `"database"`. Footer hiển thị badge theo giá trị này.
- SQLite có `check_same_thread=False`. Engine bật `pool_pre_ping`.
- `repository.keyword_condition` dùng `ilike` có escape `% _ \`. **SQLite `lower()` chỉ xử lý ký tự ASCII**,
  nên tìm "hà nội" sẽ không khớp "Hà Nội" (khác hoa thường ở ký tự có dấu). DB thật thì phụ thuộc collation.
- Driver cho DB thật đang để comment trong `requirements.txt`: `pyodbc`, `oracledb`, `psycopg2-binary`.

## 11. Công thức thay đổi thường gặp

**Thêm một trạng thái lỗi mới:**
1. `models.Status` và các tuple liên quan (`MANUAL_STATUSES`, `CLOSED_STATUSES`...).
2. `routers/__init__.py`: `STATUS_BADGE`.
3. `dashboard.html`: thanh tiến độ (danh sách màu), KPI, `locked_statuses`, `manual_statuses` truyền từ `dq_router.dashboard`.
4. Quy tắc chuyển trạng thái trong `workflow.py`.
5. Có thể cần cập nhật `mock_data` và README.

**Thêm vai trò mới:**
1. `models.Role` và `ROLE_LABELS`.
2. Các thuộc tính quyền của `CurrentUser`.
3. `auth.role_from_groups` và cấu hình nhóm AD trong `config.py` / `.env.example`.
4. Phần ép `all_branches` trong `resolve_user` và trong `admin_router._validate`.
5. Ma trận quyền trong `admin_permissions.html` (thứ tự cột theo `roles`, tức thứ tự khai báo enum) và README.

**Thêm thao tác ghi mới:**
1. Viết hàm trong `workflow.py`: kiểm tra quyền, kiểm tra phạm vi từng dòng, `audit`, `commit`; trả `ActionResult` hoặc raise `WorkflowError`.
2. Thêm route POST có `verify_csrf` theo mẫu PRG.
3. Thêm form trong template có `csrf_token` và `next`.
4. Thêm action vào `AUDIT_ACTIONS`.

**Thêm trang mới:**
1. Viết router mới với các dependency `get_current_user` / `require_admin` và `get_db`.
2. `app.include_router` trong `main.py`.
3. Tạo template `{% extends "base.html" %}`, truyền `user` vào context.
4. Thêm link vào menu trong `base.html` (dùng biến `path` để đánh dấu mục active).

**Map sang bảng DQ thật có tên cột khác:**
- Sửa tham số tên cột trong `mapped_column` của `DQError`. `_check_dq_table` kiểm tra theo tên cột DB này (so sánh chữ thường).

## 12. Cấu hình (`config.py`; đầy đủ trong `.env.example`)

| Nhóm | Biến chính |
|---|---|
| App / session | `APP_NAME`, `DEBUG`, `LOG_LEVEL`, `SECRET_KEY` (không đặt thì sinh ngẫu nhiên, session mất khi restart và hỏng khi chạy `--workers`), `SESSION_MAX_AGE`, `SESSION_HTTPS_ONLY` |
| AD | `MOCK_LDAP`, `LDAP_SERVER`, `LDAP_USE_SSL`, `LDAP_PORT`, `LDAP_UPN_SUFFIX`, `LDAP_BASE_DN`, `LDAP_TIMEOUT`, `LDAP_BRANCH_ATTRIBUTE`, `LDAP_NESTED_GROUPS`, `LDAP_GROUP_ADMIN`, `LDAP_GROUP_APPROVER`, `LDAP_GROUP_USER` |
| DB | `USE_MOCK_DATA` (alias `MOCK_DB`), `MOCK_DATABASE_URL`, `DB_FALLBACK_TO_MOCK`, `DATABASE_URL`, `DQ_TABLE_NAME`, `DQ_TABLE_SCHEMA`, `APP_TABLE_SCHEMA`, `DB_ECHO` |
| Khác | `PAGE_SIZE` (25), `EXPORT_MAX_ROWS` (100000), `EXCEPTION_REASON_MIN_LENGTH` (10) |

Tài khoản giả lập (`MOCK_LDAP=true`):

| Tài khoản | Mật khẩu | Nhóm | Chi nhánh |
|---|---|---|---|
| `admin` | `Admin@123` | DQ_ADMIN | HO |
| `approver` | `Approver@123` | DQ_APPROVER | HO |
| `hn.user` | `User@123` | DQ_USER | HN001 |
| `hcm.user` | `User@123` | DQ_USER | HCM01 |
| `guest` | `Guest@123` | không có nhóm DQ, bị từ chối | DN001 |

Trong dữ liệu seed, các yêu cầu ngoại lệ do `hn.user`, `hcm.user` hoặc `<mã cn>.user` gửi và do `approver` quyết định.

## 13. Bẫy đã gặp & lưu ý

- **`requirements.txt` chỉ được chứa ký tự ASCII.** pip trên Windows đọc file bằng cp1252 nên lỗi với chú thích tiếng Việt có dấu.
- `fastapi.testclient` phát `StarletteDeprecationWarning` (khuyên dùng `httpx2`). Cảnh báo này chỉ ảnh hưởng test, không ảnh hưởng app.
- `Identity()` trên cột PK dùng được cho SQLite, PostgreSQL, Oracle và SQL Server. Khi seed vẫn INSERT id tường minh (để giữ lịch sử ngoại lệ khớp `error_id`).
- Flash message được HTML-escape khi render, nên ký tự `'` thành `&#39;`. Test so sánh chuỗi cần lưu ý điều này.
- Đổi quyền, khóa hoặc xóa phân quyền có hiệu lực ngay vì `resolve_user` chạy mỗi request. Đổi lại, mỗi request tốn thêm một truy vấn `db.get(UserPermission)`.
- `pending_exceptions()` trong menu mở thêm một DB session cho mỗi trang render. Chấp nhận được ở quy mô LAN.
- Trên máy dev, PATH hệ thống (Machine) vẫn trỏ Python 3.12, nên lệnh `python` / `uvicorn` có thể chưa phải 3.13. Luôn gọi `py -3.13` (và `py -3.13 -m uvicorn`).

## 14. Giới hạn hiện tại / hướng mở rộng

- Chưa có bộ test trong repo (xem §2) và chưa có migration tool (Alembic); schema được tạo bằng `create_all`.
- Ngoại lệ đã duyệt không có ngày hết hiệu lực; chưa có thông báo email khi có yêu cầu hoặc khi được duyệt.
- Phê duyệt chỉ có một cấp; người phê duyệt chỉ giới hạn được ở một chi nhánh, hoặc xem toàn hệ thống.
- Tìm kiếm không phân biệt dấu tiếng Việt (ví dụ "ha noi" khớp "Hà Nội") chưa được hỗ trợ.
- Export chưa có sheet lịch sử ngoại lệ; trang `/exceptions` chưa có nút xuất file.
- Nhánh LDAP thật chưa được kiểm thử với Domain Controller.
