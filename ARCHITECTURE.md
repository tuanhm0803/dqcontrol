# ARCHITECTURE.md – DQ Dashboard

> Tài liệu bàn giao cho AI / developer tiếp tục phát triển **mà không cần đọc lại toàn bộ repo**.
> Mô tả trạng thái code tại thời điểm viết (2026-10-28). Khi sửa kiến trúc, quy ước hoặc luồng nghiệp vụ,
> **hãy cập nhật file này cùng commit**. Hướng dẫn cho người dùng cuối nằm ở `README.md`.

---

## 1. Tổng quan

Web app nội bộ (LAN; có thêm bản demo trên VPS tại https://dq.tuanhm.pro, xem §2) cho **yêu cầu loại trừ Chất lượng Dữ liệu (DQ)**
của các chi nhánh ngân hàng:

- Đăng nhập bằng Active Directory (ldap3), có chế độ giả lập `MOCK_LDAP`.
- Phân quyền 5 vai trò (Quản trị DQ, Phê duyệt QTDL, Phê duyệt nghiệp vụ, Lãnh đạo phòng ban, User chi nhánh), lấy từ nhóm AD
  và có thể bị **phân quyền nội bộ** (lưu trong DB) ghi đè.
- **Yêu cầu loại trừ** một bản ghi khỏi một quy tắc DQ: khai báo tay hoặc **upload Excel theo mẫu** → **duyệt 3 cấp tuần tự**
  (LĐ phòng ban → Nghiệp vụ → QTDL) → **xuất Excel/CSV các yêu cầu đã duyệt** để hệ thống DQ xử lý tiếp.
  Yêu cầu loại trừ **không liên kết** tới dòng trong bảng lỗi DQ.
- **Danh mục mã quy tắc** (`dq_rules`) do admin quản lý: thêm / sửa / ngừng dùng, upload Excel thay thế toàn bộ.
- Dashboard lỗi DQ (lọc / thống kê / xuất file) **chỉ cho các vai trò Hội sở** (admin, QTDL, nghiệp vụ); cấp chi nhánh không xem lỗi.
  Admin cập nhật trạng thái xử lý hàng loạt.
- Nhật ký hệ thống (audit log).

> Lịch sử: trước 2026-10-28 app có luồng "yêu cầu ngoại lệ" gắn với từng lỗi DQ (bảng `dq_exception_requests`,
> trạng thái lỗi "Chờ duyệt ngoại lệ" / "Ngoại lệ đã duyệt", trang `/exceptions`). Luồng đó đã bị thay bằng module loại trừ.

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

### Deploy production (VPS)

- `Dockerfile` (python:3.13-slim-bookworm, user `dq` uid 1000) chạy **1 worker** uvicorn với `--proxy-headers`.
  Không tăng worker khi còn dùng SQLite: `seed_mock_data` lần đầu sẽ bị nhiều tiến trình chạy cùng lúc.
  `MOCK_DATABASE_URL=sqlite:////data/dq_mock.db` trỏ vào volume `/data`.
- VPS `72.60.43.33` chạy nhiều app; cổng 80/443 thuộc về **`edge-nginx`** (repo riêng `tuanhm_edge_proxy`, `/opt/edge`).
  `deploy/docker-compose.yml` chỉ có service `app` (`container_name: dq-app`) join mạng external `edge-network`, không publish cổng.
  Edge proxy: SNI `dq.tuanhm.pro` → `127.0.0.1:8445` (terminate TLS) → `dq-app:8080`; chứng chỉ do `edge-certbot` cấp
  (domain nằm trong `CERT_DOMAINS`). **Đổi tên container hoặc cổng app thì phải sửa cả `nginx.conf` của repo edge.**
- Trên VPS (`/opt/dqcontrol`) có 2 file do workflow ghi: `.env` (chỉ `APP_IMAGE=ghcr.io/...:<sha>`, dùng cho interpolation của compose)
  và `app.env` (biến môi trường của app, quyền 600).
- `.github/workflows/deploy.yml`: job `build` (đẩy tag `latest` + `<sha>` lên GHCR) → job `deploy` (SSH thuần, không dùng action bên thứ ba;
  đăng nhập GHCR bằng `GITHUB_TOKEN` của job rồi logout) → kiểm tra `/health`.
  Secrets `VPS_HOST`, `VPS_USERNAME`, `VPS_SSH_KEY`, `VPS_PORT` cùng tên với repo edge.
  Bản production hiện là **demo**: workflow cố định `MOCK_LDAP=true`, `USE_MOCK_DATA=true`, `SESSION_HTTPS_ONLY=true`;
  muốn đổi thì thêm dòng vào secret `APP_ENV_EXTRA` (ghi sau nên đè giá trị trước).
- `.dockerignore` loại `.env`, `*.db`, `wheels/`, `.venv`, nên image không mang dữ liệu hay cấu hình máy dev.

## 3. Cấu trúc module & hướng import

```
config.py        Settings đọc env/.env (python-dotenv). Đối tượng toàn cục: settings, BASE_DIR
models.py        Enum + SQLAlchemy ORM + Pydantic schema + ExclusionFilter + CurrentUser (chứa logic quyền)
mock_data.py     Sinh dữ liệu giả lập (seed=42) + MOCK_USERS (tài khoản AD giả)
database.py      Engine, SessionLocal, init_database(), get_db(), data_source(), seed, CLI
repository.py    Truy vấn đọc bảng lỗi DQ (search/fetch/stats) + list_branches (bảng lỗi) / list_rules, rule_names (dq_rules) + keyword_condition()
workflow.py      Nghiệp vụ GHI: update_status, danh mục quy tắc (save_rule/replace_rules), luồng loại trừ
                 (create/decide/cancel/revoke, decide_blocker), audit(), list/fetch/count yêu cầu
auth.py          Xác thực AD, group_roles()/resolve_user() (tính quyền), get_current_user, require_admin, require_error_viewer, CSRF
routers/__init__.py         templates (Jinja2), globals cho template, flash, flash_result, safe_next, redirect, page_url
routers/auth_router.py      /login, /logout, /api/me
routers/dq_router.py        /, /dashboard, /dq/status, /api/dq-errors, get_filters(), scoped_branches()
routers/export_router.py    /export/excel, /export/csv (lỗi DQ) + style Excel dùng chung, attachment()
routers/exclusion_files.py  File mẫu, parse_upload(), build_export_excel/csv() cho yêu cầu loại trừ;
                            build_rules_excel(), parse_rules_upload() cho danh mục quy tắc
routers/exclusion_router.py /exclusions/*
routers/admin_router.py     /admin/permissions/*, /admin/rules/*
main.py          App, middleware, exception handler, mount static, include routers, /health
templates/       base, login, dashboard, exclusions, exclusion_new, admin_permissions, admin_rules, error, _pagination
static/css/app.css
```

**Hướng import một chiều; không được tạo vòng import:**

```
config → models → mock_data → database → repository → workflow → auth → routers/__init__
       → routers/dq_router, routers/export_router → routers/exclusion_files → routers/exclusion_router → main
```

- `workflow.py` và `repository.py` **không được import** `auth` hay `routers`.
  Logic phân quyền cần dùng ở tầng nghiệp vụ được đặt thành method của `CurrentUser` trong `models.py`
  (`can_access`, `scope`, `can_view_errors`, `can_update_status`, `can_request`, `approval_levels`, `can_approve`, `is_admin`)
  chính là để tránh vòng import. Cấu hình luồng duyệt (`APPROVAL_LEVELS`) cũng nằm ở `models.py`.
- `routers/__init__.py` import `auth.csrf_token` và `workflow.count_pending_for` để đăng ký làm Jinja globals.
- `export_router` và `exclusion_router` dùng lại `get_filters` / `scoped_branches` từ `dq_router`;
  `exclusion_files` dùng lại `HEADER_FILL`, `HEADER_FONT`, `BORDER` từ `export_router`;
  `admin_router` dùng `exclusion_files` (file danh mục) và `auth.group_roles`.

## 4. Mô hình dữ liệu (`models.py`)

### 4.1 Enum. Giá trị chuỗi tiếng Việt chính là giá trị LƯU TRONG DB

```python
Severity: "High" | "Medium" | "Low"
Status (cột dq_errors.status): PENDING="Chưa xử lý", IN_PROGRESS="Đang xử lý", DONE="Hoàn thành"
MANUAL_STATUSES = (PENDING, IN_PROGRESS, DONE)       # admin cập nhật trên dashboard
ExclusionStatus (cột dq_exclusion_requests.status):
    "Chờ LĐ phòng duyệt" | "Chờ duyệt nghiệp vụ" | "Chờ duyệt QTDL" | "Đã duyệt" | "Từ chối" | "Đã hủy" | "Đã thu hồi"
ExclusionSource (cột source): "Nhập tay" | "Excel"
Role: "admin" | "approver" (Phê duyệt QTDL) | "business_approver" | "branch_manager" | "branch_user"
      (ROLE_LABELS: tên hiển thị; HQ_ROLES = admin, approver, business_approver: mặc định toàn hệ thống, xem lỗi DQ)
APPROVAL_LEVELS: ApprovalLevel(key, label, pending, next, role) theo thứ tự
    ("manager",  "LĐ phòng ban", Chờ LĐ phòng duyệt  -> Chờ duyệt nghiệp vụ, branch_manager)
    ("business", "Nghiệp vụ",    Chờ duyệt nghiệp vụ -> Chờ duyệt QTDL,      business_approver)
    ("dq",       "QTDL",         Chờ duyệt QTDL      -> Đã duyệt,            approver)
LEVEL_BY_STATUS (trạng thái chờ -> cấp), PENDING_STATUSES (3 trạng thái chờ)
```

⚠️ **Template so sánh trực tiếp với chuỗi literal**, ví dụ `r.status != 'Đã duyệt'` trong `exclusions.html`
(trạng thái chờ dùng global `pending_statuses`),
hay `stats.by_status.get('Hoàn thành')` trong `dashboard.html`. Khi đổi hoặc thêm giá trị enum phải `grep` cả `templates/`. Xem thêm §11.
Bảng lỗi DQ thật có thể chứa giá trị trạng thái khác enum (ví dụ dữ liệu cũ "Ngoại lệ đã duyệt"): hiển thị bằng badge mặc định, không lọc được.

### 4.2 Bảng

| Bảng | Sở hữu | Ghi chú |
|---|---|---|
| `dq_errors` (tên lấy từ `DQ_TABLE_NAME`, schema từ `DQ_TABLE_SCHEMA`) | Hệ thống DQ bên ngoài; app **đọc + update** | Cột: `id` PK Identity, `branch_code`, `branch_name`, `rule_code`, `description`, `severity`, `detected_date`, `status`, `owner`, **`resolved_date`**, **`resolved_by`** (2 cột cuối do app ghi). App **không bao giờ INSERT** dòng lỗi, trừ khi seed. Cũng là **nguồn danh mục** chi nhánh / mã quy tắc (`SELECT DISTINCT`) để kiểm tra yêu cầu loại trừ. |
| `dq_rules` | App | PK `rule_code` (chữ hoa, ≤50), `rule_name` (≤500), `is_active`, `updated_by`, `updated_at`. Danh mục mã quy tắc do admin quản lý; mã ngừng dùng không bị xóa. |
| `dq_exclusion_requests` | App | `branch_code`, `rule_code`, `record_key` (≤100), `reason`, `valid_to` (bắt buộc khi tạo; NULL chỉ ở dữ liệu cũ = không thời hạn), `source`, `upload_file` (tên file Excel), `status` (≤30), `requested_by`/`_name`/`_at`, **người / ngày duyệt từng cấp** `manager_by`/`_by_name`/`_at`, `business_*`, `dq_*` (tiền tố = `ApprovalLevel.key`), `decided_by`/`_name`/`_at` (thao tác **kết thúc**: duyệt cấp cuối / từ chối / hủy / thu hồi), `decision_note` (≤4000, **nhật ký** các dòng `[Duyệt cấp X - user dd/mm/yyyy HH:MM] ghi chú`). Không có FK tới `dq_errors`. Không có unique constraint: chống trùng nằm ở `workflow` (§6.1). |
| `dq_user_permissions` | App | PK `username` (chữ thường, không có domain). `role`, `branch_code` (NULL = dùng chi nhánh từ AD), `all_branches`, `is_active`, `note`, `updated_by`, `updated_at` |
| `dq_audit_log` | App | `at`, `username`, `action`, `target`, `detail` (cắt ở 2000 ký tự) |

`APP_TABLES` = 4 bảng của app (`dq_rules`, `dq_exclusion_requests`, `dq_user_permissions`, `dq_audit_log`), schema lấy từ `APP_TABLE_SCHEMA`; được `create_all` khi khởi động ở chế độ DB thật.
Bảng cũ `dq_exception_requests` không còn trong model; trên DB đã có thì nằm yên (app không xóa).
Tên cột DB của `DQError` là tham số đầu tiên của `mapped_column(...)`. Muốn map sang bảng thật có tên cột khác thì sửa ở đó,
còn tên thuộc tính Python giữ nguyên.

Tên quy tắc **không lưu** trong `dq_exclusion_requests`: `ExclusionRequestOut.rule_name` được điền khi đọc
(`workflow._with_rule_names` dùng `repository.rule_names`, gồm cả mã ngừng dùng). `list_rules(db)` mặc định chỉ trả mã **đang dùng**
(form, file mẫu, kiểm tra khi tạo); `list_rules(db, active_only=False)` cho bộ lọc danh sách.
Danh mục **chi nhánh** vẫn lấy từ bảng lỗi DQ (`list_branches`, `SELECT DISTINCT`).

Datetime lưu dạng **naive local time** (`datetime.now()`); `resolved_date` lấy theo `date.today()`.

### 4.3 Schema Pydantic chính

- `DQErrorOut`: dữ liệu ra của một dòng lỗi (`from_attributes`).
- `DQFilter`: `branch_code`, `severity`, `status`, `keyword`, `date_from`, `date_to`. Có `to_query_params()` để giữ bộ lọc trên URL.
- `ExclusionRequestOut`: một yêu cầu loại trừ (`from_attributes`), kèm `rule_name` tra từ danh mục;
  method `approvals()` trả `(cấp, người duyệt, ngày duyệt)` cho cột *Tiến trình duyệt*.
- `DQRuleOut`: một mã quy tắc của danh mục.
- `ExclusionFilter` (**dataclass**, không phải Pydantic): `branch_code`, `rule_code`, `status`, `keyword`, `decided_from`, `decided_to`,
  `active_only`. Dùng chung cho danh sách và file xuất; đọc từ query bằng `exclusion_router.get_exclusion_filter`.
- `UserPermissionOut`, `DQStats`, `PagedResult`.
- `ADIdentity`: thông tin AD lưu trong session (`username`, `display_name`, `email`, `branch_code`, `groups` là danh sách CN).
- **`CurrentUser`**: người dùng hiệu lực, gồm `role`, `branch_code`, `all_branches`, `permission_source` ("AD" | "Nội bộ").
  - Thuộc tính quyền: `is_admin`; `can_view_errors` (`HQ_ROLES`); `can_update_status` (admin);
    `can_request` (admin, branch_user); `approval_levels` (admin: cả 3 cấp; vai trò duyệt: đúng cấp của mình);
    `can_approve` = có ít nhất một cấp.
  - `can_access(branch)`: cho phép nếu xem toàn hệ thống, hoặc đúng chi nhánh của user.
  - `scope(filters)`: trả bộ lọc đã bị ép `branch_code` khi user không xem toàn hệ thống.
- `EXPORT_COLUMNS`: thứ tự và tiêu đề cột khi export lỗi DQ. `EXCLUSION_EXPORT_COLUMNS`: cột file xuất yêu cầu loại trừ
  (tiêu đề phải khớp `HEADER_ALIASES` để file xuất upload lại được, xem §9).

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
Không có → role theo nhóm AD (auth.group_roles), ưu tiên: LDAP_GROUP_ADMIN > LDAP_GROUP_APPROVER (QTDL)
           > LDAP_GROUP_BUSINESS > LDAP_GROUP_MANAGER > LDAP_GROUP_USER
           (không thuộc nhóm nào → AuthError); all_branches = role in HQ_ROLES; source="AD"
Sau đó ép buộc: admin → all_branches=True; branch_user, branch_manager → all_branches=False
Nếu không all_branches mà không có branch_code → AuthError
```

`get_current_user` khi gặp `AuthError` thì xóa session, đặt flash lỗi rồi raise `NotAuthenticated`.
`main.py` bắt exception này: với `/api/*` trả **401 JSON**, còn lại **redirect 303** tới `/login?next=<url hiện tại>`.
Nhờ đó khóa hoặc đổi quyền có hiệu lực ngay ở request kế tiếp.

### 5.4 Ma trận quyền và nơi kiểm tra

| Chức năng | admin | approver (QTDL) | business_approver | branch_manager | branch_user | Kiểm tra tại |
|---|:-:|:-:|:-:|:-:|:-:|---|
| Dashboard / API / export lỗi DQ | ✔ | ✔ | ✔ | | | dependency `require_error_viewer` (403) + `user.scope(filters)` |
| Cập nhật trạng thái lỗi | ✔ | | | | | `user.can_update_status` trong `workflow.update_status` |
| Khai báo / upload yêu cầu loại trừ (cho **mọi** chi nhánh) | ✔ | | | | ✔ | `user.can_request` trong `workflow.create_exclusions` |
| Hủy yêu cầu đang chờ | ✔ | | | | người gửi | `workflow.cancel_exclusion` (người gửi hủy được cả yêu cầu cho chi nhánh khác) |
| Duyệt / từ chối cấp LĐ phòng ban | ✔ | | | ✔ (CN mình) | | `workflow.decide_blocker` |
| Duyệt / từ chối cấp Nghiệp vụ | ✔ | | ✔ | | | `workflow.decide_blocker` |
| Duyệt / từ chối cấp QTDL | ✔ | ✔ | | | | `workflow.decide_blocker` |
| Thu hồi yêu cầu đã duyệt | ✔ | | | | | `user.is_admin` trong `workflow.revoke_exclusion` |
| Xem danh sách / xuất yêu cầu đã duyệt | ✔ | ✔ | ✔ | ✔ | ✔ | `_scope_conditions`: không `all_branches` → `branch_code = CN của user` **hoặc** `requested_by = user` |
| `/admin/*` (phân quyền, nhật ký, danh mục quy tắc) | ✔ | | | | | dependency `require_admin` (403) + `user.is_admin` trong `save_rule` / `replace_rules` |

**Nguyên tắc: quyền LUÔN được kiểm tra ở `workflow.py` / query phía server.** Template chỉ ẩn hoặc hiện nút cho tiện.
Phạm vi chi nhánh được kiểm tra **từng dòng** bằng `user.can_access(row.branch_code)` cho thao tác ghi,
và bằng `user.scope(filters)` (lỗi DQ) / `_exclusion_conditions` (yêu cầu loại trừ) cho truy vấn đọc.
`GET /` chuyển hướng theo quyền: `can_view_errors` → `/dashboard`, còn lại → `/exclusions`.

### 5.5 CSRF

- Mọi route POST thay đổi dữ liệu khai báo `dependencies=[Depends(verify_csrf)]`, kể cả upload multipart (`/exclusions/upload`).
- Mọi form POST trong template phải có `<input type="hidden" name="csrf_token" value="{{ csrf_token(request) }}">`.
- `verify_csrf` đọc `await request.form()` (Starlette cache lại form nên không xung đột với các tham số `Form(...)`) và so sánh bằng `secrets.compare_digest`.
- Sai token thì trả 403.
- **Ngoại lệ:** `POST /login` không có CSRF vì chưa có session.

## 6. Nghiệp vụ (`workflow.py`)

### 6.1 Yêu cầu loại trừ

```
create_exclusions (tay / Excel) ──▶ first_status(user): admin → Chờ duyệt nghiệp vụ; còn lại → Chờ LĐ phòng duyệt
Chờ <cấp> ──decide(approve)──▶ level.next   (ghi <key>_by/_by_name/_at; cấp cuối → Đã duyệt + decided_*)
Chờ <cấp> ──decide(reject, note bắt buộc)──▶ Từ chối   (decided_*)
Chờ <cấp> ──cancel_exclusion (người gửi / admin)──▶ Đã hủy
Đã duyệt ──revoke_exclusion (admin, note bắt buộc)──▶ Đã thu hồi
Mọi ghi chú (duyệt có ghi chú / từ chối / thu hồi) được NỐI vào decision_note qua _append_note.
```

`create_exclusions(db, user, items: list[ExclusionInput], source, upload_file)` kiểm tra **từng dòng** (`_check_item`):
- Chi nhánh bỏ trống → chi nhánh của user (admin chi nhánh `HO` không có trong danh mục nên sẽ báo "không tồn tại").
  **Mọi user được khai báo cho chi nhánh khác** (không ép phạm vi khi tạo; phạm vi chỉ áp khi xem / duyệt).
- Chi nhánh phải có trong `list_branches` (bảng lỗi DQ, so khớp không phân biệt hoa thường, lưu theo cách viết trong bảng lỗi).
  Mã quy tắc (chuyển chữ hoa) phải có trong danh mục `dq_rules` **đang dùng**; danh mục trống → `WorkflowError` chặn cả lô.
- `record_key` 1..100 ký tự; lý do ≥ `EXCLUSION_REASON_MIN_LENGTH`; `valid_to` **bắt buộc** và không ở quá khứ.
- **Chống trùng** theo khóa `(branch_code, rule_code, record_key)`: trùng dòng khác trong cùng lô, hoặc trùng yêu cầu
  **đã duyệt còn hiệu lực** (`_approved_valid`: *Đã duyệt* và `valid_to` NULL / ≥ hôm nay) → bỏ qua.
  Yêu cầu đang chờ (bất kỳ cấp) **không** chặn: một bản ghi có thể có nhiều yêu cầu chờ duyệt.
  Truy vấn yêu cầu đang chặn chia lô `_IN_CHUNK = 500` giá trị `IN` (SQL Server giới hạn 2100 tham số).
- Ghi **một** dòng audit cho cả lô (`EXCL_REQUEST` / `EXCL_UPLOAD`, target `LT#<id>` hoặc `LT#<min>..<max>`).

**Điều kiện duyệt / từ chối** — `decide_blocker(user, req)` (không truy vấn DB, dùng cả ở template để hiện checkbox / ổ khóa):
1. Trạng thái phải là một trạng thái chờ; cấp của trạng thái phải thuộc `user.approval_levels`.
2. `user.can_access(req.branch_code)` (LĐ phòng ban chỉ chi nhánh mình).
3. **Maker-checker:** không duyệt yêu cầu của chính mình (kể cả admin).
4. **Một người không duyệt 2 cấp** của cùng yêu cầu (`_approved_level_by` xem các cột `<key>_by`) — admin duyệt được mọi cấp
   nhưng vẫn cần người khác ở các cấp còn lại.

Thêm khi **duyệt** (trong `decide_exclusions`): quá `valid_to` → chặn; ở **cấp cuối**, bản ghi đã có yêu cầu khác đã duyệt còn hiệu lực
(`_approved_duplicate`; autoflush nên thấy cả yêu cầu vừa duyệt trong cùng lô) → chặn, để file xuất không trùng.

### 6.1b Danh mục mã quy tắc

- `save_rule(db, user, RuleInput, is_active)`: thêm / sửa một mã (audit `RULE_UPSERT`).
- `replace_rules(db, user, items, filename)`: **thay thế toàn bộ, tất cả hoặc không**: kiểm tra mọi dòng (`_check_rule`: mã khớp
  `RULE_CODE_RE` sau khi chữ hoa, tên 1..500 ký tự, không trùng mã trong file) — có lỗi thì raise `WorkflowError` (liệt kê tối đa 10)
  và không ghi gì. Hợp lệ: mã trong file → thêm / cập nhật tên + `is_active=True`; mã không có trong file → `is_active=False`
  (không xóa). File rỗng bị từ chối (tránh ngừng dùng toàn bộ). Audit `RULE_UPLOAD`.

Bất biến khác:
- **Maker-checker:** `req.requested_by == user.username` thì bỏ qua khi duyệt, kể cả khi user là admin.
- Điều kiện chặn duyệt / từ chối nằm ở `_decide_blocker`. Duyệt bị chặn nếu đã quá `valid_to`, hoặc bản ghi đã có yêu cầu khác
  đã duyệt còn hiệu lực (`_approved_duplicate`; autoflush nên thấy cả yêu cầu vừa duyệt trong cùng lô) → file xuất không trùng.
- Yêu cầu loại trừ **không đổi trạng thái** dòng nào trong `dq_errors`.

### 6.2 Trạng thái lỗi DQ

`update_status` (chỉ admin): `Chưa xử lý ⇄ Đang xử lý → Hoàn thành`. DONE ghi `resolved_date/by`, trạng thái khác xóa.

### 6.3 Quy ước API của tầng nghiệp vụ

- Thao tác hàng loạt trả `ActionResult(done: int, skipped: list[str])`.
  Mỗi phần tử `skipped` có dạng `"#<id>: <lý do>"` (duyệt) hoặc `"<label>: <lý do>"` (tạo; label là `Dòng <n>` của file Excel
  hoặc mã bản ghi khi nhập tay). **Dòng không hợp lệ được bỏ qua, không làm hỏng cả lô.**
- Lỗi chặn toàn bộ thao tác (sai quyền, thiếu lý do từ chối, danh sách rỗng) thì raise `WorkflowError(message cho người dùng)`.
- Mỗi hàm tự `db.commit()`. Bản ghi được nạp bằng `with_for_update()` (SQLite bỏ qua, DB thật thì khóa dòng).
- Mỗi thay đổi đều gọi `audit(db, username, ACTION, target, detail)`, trong cùng transaction.
  Các action đang dùng: `LOGIN, STATUS_UPDATE, EXCL_REQUEST, EXCL_UPLOAD, EXCL_APPROVE, EXCL_REJECT, EXCL_CANCEL, EXCL_REVOKE,
  EXCL_EXPORT, RULE_UPSERT, RULE_UPLOAD, PERM_UPSERT, PERM_DELETE, EXPORT` (`EXCL_APPROVE` / `EXCL_REJECT` ghi rõ cấp trong `detail`).
  **Thêm action mới thì nhớ thêm vào `AUDIT_ACTIONS` trong `admin_router.py`** để bộ lọc nhật ký hiển thị được.
  `target` theo dạng `DQ#<id>`, `LT#<id>`, `LT#<min>..<max>`, `XLSX`/`CSV`, hoặc username.
- `list_exclusions(db, user, tab, f, page, page_size)` với `tab` là `pending` (trạng thái chờ ở các cấp của user),
  `mine` hoặc `all`;
  `fetch_exclusions(db, user, f, limit)` cho file xuất (sắp theo `decided_at`).
- `count_pending_for(user)` đếm số yêu cầu user **duyệt được ngay**: đúng cấp, đúng phạm vi chi nhánh, không phải của mình,
  chưa duyệt cấp nào trước đó. Dùng cho badge trên menu.

## 7. Routes

| Method | Path | Quyền | Mô tả |
|---|---|---|---|
| GET | `/login` | — | Form đăng nhập; đã có session thì redirect `next` |
| POST | `/login` | — | Form: `username`, `password`, `next` (mặc định `/`) |
| POST | `/logout` | CSRF | Xóa session |
| GET | `/api/me` | login | `CurrentUser` JSON |
| GET | `/` | login | Redirect `/dashboard` (`HQ_ROLES`) hoặc `/exclusions` (branch_manager, branch_user) |
| GET | `/dashboard` | `require_error_viewer` | Query: các trường `DQFilter` + `page` |
| POST | `/dq/status` | CSRF, admin | Form: `ids` (nhiều giá trị), `new_status`, `next` |
| GET | `/api/dq-errors` | `require_error_viewer` | JSON `PagedResult`; `page_size` ≤ 500 |
| GET | `/export/excel` · `/export/csv` | `require_error_viewer` | Lỗi DQ, cùng query với dashboard |
| GET | `/exclusions` | login | Query: `tab`, `branch_code`, `rule_code`, `status`, `keyword`, `page`. Tab mặc định: có cấp duyệt → `pending`, còn lại → `mine`. Context `blockers` = `{id: decide_blocker(...)}` |
| GET | `/exclusions/new` | `can_request` | Trang khai báo (nhập tay + upload). Dòng mới mặc định `branch_code` = CN của user (nếu có trong danh mục), `valid_to` = `one_month_later(hôm nay)` |
| POST | `/exclusions/new` | CSRF, `can_request` | Bảng nhiều dòng: các trường `branch_code`, `rule_code`, `record_key`, `reason`, `valid_to` (ISO) gửi dạng **danh sách song song theo thứ tự dòng** (`list[str] = Form([])`), bỏ dòng chưa có quy tắc / mã bản ghi / lý do (chi nhánh, hiệu lực luôn có mặc định), ≤ `MAX_MANUAL_ROWS` (200). Label lỗi `Dòng <n>`. Không lỗi → redirect `?tab=mine`; có lỗi → **render lại form chỉ với các dòng lỗi** (kèm `error` từng dòng; 200 nếu có dòng đã gửi, 400 nếu không) |
| GET | `/exclusions/template` | login | File mẫu `.xlsx` (danh mục theo phạm vi user) |
| POST | `/exclusions/upload` | CSRF, `can_request` | multipart `file` (.xlsx, ≤ `EXCLUSION_UPLOAD_MAX_MB`) |
| POST | `/exclusions/approve` · `/exclusions/reject` | CSRF, `can_approve` | `ids`, `note`, `next` |
| POST | `/exclusions/{id}/cancel` | CSRF | `next` |
| POST | `/exclusions/{id}/revoke` | CSRF, admin | `note`, `next` |
| GET | `/exclusions/export/excel` · `/exclusions/export/csv` | login | Yêu cầu **Đã duyệt** (ép `status`), query: `branch_code`, `rule_code`, `decided_from`, `decided_to`, `active_only`, `keyword` |
| GET | `/admin/rules` | admin | Danh mục mã quy tắc (`keyword`, `show` = active / inactive), số yêu cầu theo mã |
| POST | `/admin/rules` | CSRF, admin | Thêm / sửa: `rule_code`, `rule_name`, `is_active` (checkbox) |
| GET | `/admin/rules/export` | admin | Tải danh mục `.xlsx` (cũng là file mẫu upload) |
| POST | `/admin/rules/upload` | CSRF, admin | multipart `file`: thay thế toàn bộ (tất cả hoặc không) |
| GET | `/admin`, `/admin/permissions` | admin | Danh sách phân quyền + nhật ký (`action`, `keyword`, `page`; 50 dòng/trang) |
| POST | `/admin/permissions` | CSRF, admin | Thêm hoặc sửa (upsert): `username`, `display_name`, `role`, `branch_code`, `all_branches` (checkbox), `is_active` (checkbox), `note` |
| POST | `/admin/permissions/{username}/delete` | CSRF, admin | Xóa phân quyền nội bộ, user quay về quyền theo AD |
| GET | `/health` | — | `{"status","data_source"}` |
| GET | `/docs` | — | Chỉ có khi `DEBUG=true` |

**Mẫu xử lý POST (PRG):** gọi workflow → `flash_result(..., limit=5)` (upload / nhập tay dùng `limit=10`) hoặc `flash(...)` → `redirect(safe_next(next))` (303).
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
  - Dữ liệu và cấu hình: `app_name`, `mock_ldap`, `severities`, `statuses`, `exclusion_statuses`, `pending_statuses`, `roles`, `reason_min_length`.
  - Class CSS cho badge: `severity_badge(v)`, `status_badge(v)`, `exclusion_badge(v)`.
  - Hàm tiện ích: `data_source()`, `csrf_token(request)`, `pop_flashes(request)`, `pending_exclusions(user)` (tự mở `SessionLocal` riêng), `page_url(path, params, page)`.
- **Phân trang:** `{% include "_pagination.html" %}`, cần `page`, `pages` và `params` (dict bộ lọc, không gồm `page`) trong context.
- **Chọn nhiều dòng** (JS chung ở cuối `base.html`), quy ước theo thuộc tính `data-group="<tên nhóm>"`:
  - `.row-check`: checkbox từng dòng; `.check-all`: ô chọn tất cả.
  - `.needs-selection`: nút tự disable khi chưa chọn dòng nào; `.selection-count`: hiển thị số dòng đã chọn.
  - Checkbox nằm trong bảng, **ngoài** form, gắn vào form bằng thuộc tính `form="bulkForm"` (dashboard, nhóm `err`, chỉ admin)
    hoặc `form="decideForm"` (trang loại trừ, nhóm `req`).
  - Nhiều nút submit dùng chung một form và đổi đích bằng `formaction`.
- ⚠️ **Modal không được đặt trong phần tử sticky hoặc có z-index** (ví dụ `.bulk-bar`), vì lớp nền mờ sẽ che mất modal.
  Hãy đặt modal ngoài form và gắn các trường vào form bằng `form="..."` (như `#revokeModal` trong `exclusions.html` đặt ngoài mọi form).
- Kiểm tra phía trình duyệt (lý do loại trừ, ghi chú từ chối) dùng JS `preventDefault` và class `is-invalid`.
- **Bảng khai báo `exclusion_new.html`:** mỗi dòng render bằng macro `row(r, n)`; JS clone dòng mới từ `<template id="rowTemplate">`
  (cùng macro, với `defaults`). Ô nhận diện cột qua `data-col`; thứ tự cột = thứ tự dán từ Excel = thứ tự cột file mẫu
  (chi nhánh, mã quy tắc, tên quy tắc, mã bản ghi, lý do, hiệu lực). Ô *Tên quy tắc* chỉ đọc, **không có `name`** (không gửi lên),
  JS điền từ `RULE_NAMES` (`rule_names | tojson`, khóa chữ hoa); khi dán, ô trống không ghi đè chi nhánh / hiệu lực mặc định.
  Mã quy tắc / chi nhánh dùng `<input list>` + `<datalist>` thay cho `<select>` để HTML không phình theo số dòng.
  Mọi dòng luôn gửi đủ các trường (kể cả rỗng) để danh sách song song khớp chỉ số.
  **Không dùng `required`** cho trường nằm trong modal ẩn của form có nhiều nút submit, vì trình duyệt sẽ chặn cả các nút submit khác.
  Server luôn kiểm tra lại.
- Màu sắc: `--dq-primary #1f4e78` (`.bg-dq`, `.btn-dq`).
- Menu: *Lỗi DQ* (chỉ `can_view_errors`), *Yêu cầu loại trừ* (badge số chờ duyệt), *Khai báo loại trừ* (chỉ `can_request`), *Danh mục quy tắc* và *Quản trị phân quyền* (chỉ admin).
- Bootstrap và Bootstrap Icons được tải từ **CDN jsdelivr**. Nếu LAN không ra được Internet thì phải tải về `static/` và sửa `base.html`.

## 9. Export

### 9.1 Lỗi DQ (`routers/export_router.py`)

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

### 9.2 Yêu cầu loại trừ (`routers/exclusion_files.py`)

- **File mẫu** (`build_template`): sheet `Yêu cầu loại trừ` (header dòng 1 theo `TEMPLATE_COLUMNS`; `TEMPLATE_FORMAT_ROWS` = 500 dòng đầu
  định dạng Text `@` để Excel không làm mất số 0 / đổi mã dài sang 1E+11; cột *Tên quy tắc DQ (tự hiện)* là công thức `VLOOKUP` sang
  sheet `Danh mục`), sheet `Danh mục` (toàn bộ chi nhánh + mã và tên quy tắc; là nguồn của DataValidation dropdown), sheet `Hướng dẫn`.
- **Đọc file** (`parse_upload`): openpyxl `read_only`, `data_only`. Lấy sheet `Yêu cầu loại trừ` nếu có, không thì sheet đầu.
  Dòng tiêu đề = dòng đầu tiên (trong 10 dòng) có cột *Mã bản ghi*; tên cột so theo `HEADER_ALIASES` sau khi chuẩn hóa
  (chữ thường, bỏ `*` và phần trong ngoặc), nên **thứ tự cột không quan trọng, cột thừa bị bỏ qua**.
  Bắt buộc có cột *Mã quy tắc DQ*, *Mã bản ghi*, *Lý do*, *Hiệu lực đến*. Dòng trống (xét **chỉ các cột được đọc**, nên cột công thức
  tên quy tắc không làm dòng thành "có dữ liệu") bị bỏ qua. Lỗi trả về được sắp theo số dòng. Ô số nguyên kiểu float (`12345678.0`) → `"12345678"`.
  Ngày nhận kiểu date của Excel hoặc chuỗi `dd/mm/yyyy`, `yyyy-mm-dd`, `dd-mm-yyyy`, `dd.mm.yyyy`.
  Hàm dùng chung `_read_rows` / `_find_header(rows, aliases, required, anchor)` / `_data_rows` cũng phục vụ file danh mục.
  Lỗi cả file → `UploadError`; lỗi ngày theo dòng → trả về trong danh sách lỗi và gộp với `skipped` của workflow.
- **File xuất** (`build_export_excel` / `build_export_csv`): cột theo `EXCLUSION_EXPORT_COLUMNS` (gồm người / ngày duyệt từng cấp),
  **header ở dòng 1** (cho hệ thống khác đọc thẳng), metadata ở sheet `Thông tin`. CSV nối các dòng của `reason` / `decision_note`
  bằng ` | ` để mỗi yêu cầu đúng một dòng. Router ép `status = Đã duyệt`, ghi audit `EXCL_EXPORT`.
  Tên file `Loai_tru_da_duyet_<ToanHeThong|BRANCH>_<yyyymmdd_HHMMSS>.<ext>`. Không có cờ "đã xuất".
- **File danh mục quy tắc** (`build_rules_excel` / `parse_rules_upload`): sheet `Danh mục quy tắc`, cột *Mã quy tắc DQ*, *Tên quy tắc DQ*
  (bắt buộc, nhận theo `RULE_HEADER_ALIASES`) + các cột tham khảo bị bỏ qua; sheet `Hướng dẫn`. Tối đa `RULES_UPLOAD_MAX_ROWS` = 5000.

## 10. CSDL & khởi tạo (`database.py`)

- `init_database()` chạy một lần (có khóa luồng). Được gọi trong lifespan của `main.py` và lười trong `get_db()`.
- **Chế độ mock** (`USE_MOCK_DATA=true`, hoặc `MOCK_DB=true`, mặc định):
  - Dùng file SQLite `MOCK_DATABASE_URL` (mặc định `./dq_mock.db`), `create_all` toàn bộ bảng.
  - Lần đầu sẽ seed từ `mock_data.generate_mock_dataset()`: 480 lỗi (chỉ 3 trạng thái), 10 chi nhánh,
    66 yêu cầu loại trừ (32 đã duyệt, 13 chờ LĐ phòng, 5 chờ nghiệp vụ, 7 chờ QTDL, 8 từ chối ở các cấp, 1 đã hủy) cho đúng
    mã bản ghi trong mô tả lỗi còn mở, với người / ngày duyệt từng cấp nhất quán; `valid_to` = ngày gửi + 30..180 ngày.
    Danh mục `dq_rules` (16 mã, `mock_rules()`) được nạp khi bảng trống.
  - **Dữ liệu được giữ lại giữa các lần chạy**; muốn làm mới thì chạy `reset-mock`.
  - `_init_mock` tự **nạp lại toàn bộ** nếu file mock thuộc phiên bản cũ: bảng `dq_exclusion_requests` thiếu cột (khi đó DROP rồi tạo
    lại bảng này), hoặc có lỗi DQ nhưng chưa có yêu cầu loại trừ. Nhờ vậy `dq_mock.db` cũ trên máy dev / VPS được nâng cấp khi khởi động.
- **Chế độ DB thật:**
  - Kết nối `DATABASE_URL`, sau đó `_check_dq_table`: bảng phải tồn tại và có đủ cột của `DQError`, gồm `resolved_date` và `resolved_by`.
  - Tiếp theo `create_all(tables=APP_TABLES)`, rồi `_missing_columns` cho từng bảng app: bảng có sẵn từ phiên bản cũ mà thiếu cột
    → `RuntimeError` nêu tên cột (create_all không ALTER).
  - Danh mục `dq_rules` **không** tự nạp ở DB thật: admin upload lần đầu (hoặc `init-db --seed` nạp danh mục mẫu).
  - Lỗi ở bất kỳ bước nào: nếu `DB_FALLBACK_TO_MOCK=true` thì chuyển sang mock (log exception); nếu `false` thì raise.
- `data_source()` trả `"mock"` hoặc `"database"`. Footer hiển thị badge theo giá trị này.
- SQLite có `check_same_thread=False`. Engine bật `pool_pre_ping`.
- `repository.keyword_condition` dùng `ilike` có escape `% _ \`. **SQLite `lower()` chỉ xử lý ký tự ASCII**,
  nên tìm "hà nội" sẽ không khớp "Hà Nội" (khác hoa thường ở ký tự có dấu). DB thật thì phụ thuộc collation.
- Driver cho DB thật đang để comment trong `requirements.txt`: `pyodbc`, `oracledb`, `psycopg2-binary`.

## 11. Công thức thay đổi thường gặp

**Thêm một trạng thái lỗi mới:**
1. `models.Status` và `MANUAL_STATUSES` nếu admin được đặt tay.
2. `routers/__init__.py`: `STATUS_BADGE`.
3. `dashboard.html`: thanh tiến độ (danh sách màu), KPI.
4. Quy tắc chuyển trạng thái trong `workflow.update_status`.
5. Có thể cần cập nhật `mock_data` và README.

**Thêm cột cho yêu cầu loại trừ:**
1. `models.ExclusionRequest`, `ExclusionRequestOut`; nếu cần xuất thì `EXCLUSION_EXPORT_COLUMNS` (thêm **sau** 6 cột đầu) + `EXPORT_WIDTHS`.
2. Nếu khai báo được: `ExclusionInput`, `_check_item`, form `exclusion_new.html`, `TEMPLATE_COLUMNS` + `HEADER_ALIASES` trong `exclusion_files.py`.
3. DB thật: `create_all` **không thêm cột** vào bảng đã có, cần `ALTER TABLE` thủ công (chưa có Alembic).

**Thêm / đổi cấp duyệt:**
1. `models.ExclusionStatus` (trạng thái chờ mới), `APPROVAL_LEVELS` (thứ tự + `next`), cột `<key>_by/_by_name/_at` trong
   `ExclusionRequest` và `ExclusionRequestOut`, `EXCLUSION_EXPORT_COLUMNS` + `EXPORT_WIDTHS` / `DATETIME_KEYS`.
2. `routers/__init__.py`: `EXCLUSION_BADGE`. `workflow.first_status` nếu đổi cấp bắt đầu.
3. Vai trò duyệt cấp đó (xem dưới), `mock_data._pick_outcome` / `_level_approver`, ma trận quyền, README.
4. DB thật: `ALTER TABLE dq_exclusion_requests` thêm cột.

**Thêm vai trò mới:**
1. `models.Role` và `ROLE_LABELS` (thứ tự khai báo = thứ tự cột ma trận quyền); `HQ_ROLES` nếu là vai trò Hội sở.
2. Các thuộc tính quyền của `CurrentUser`.
3. `auth.group_roles` (thứ tự ưu tiên nhóm AD) và cấu hình nhóm AD trong `config.py` / `.env.example`; `ROLE_SCOPES` trong `admin_router`.
4. Phần ép `all_branches` trong `resolve_user` và trong `admin_router._validate`.
5. Ma trận quyền trong `admin_permissions.html` (mảng 5 phần tử theo thứ tự cột) + JS `syncScope`, menu `base.html`,
   tài khoản `MOCK_USERS`, `login.html` và README.

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
| AD | `MOCK_LDAP`, `LDAP_SERVER`, `LDAP_USE_SSL`, `LDAP_PORT`, `LDAP_UPN_SUFFIX`, `LDAP_BASE_DN`, `LDAP_TIMEOUT`, `LDAP_BRANCH_ATTRIBUTE`, `LDAP_NESTED_GROUPS`, `LDAP_GROUP_ADMIN`, `LDAP_GROUP_APPROVER` (QTDL), `LDAP_GROUP_BUSINESS` (nghiệp vụ), `LDAP_GROUP_MANAGER` (LĐ phòng ban), `LDAP_GROUP_USER` |
| DB | `USE_MOCK_DATA` (alias `MOCK_DB`), `MOCK_DATABASE_URL`, `DB_FALLBACK_TO_MOCK`, `DATABASE_URL`, `DQ_TABLE_NAME`, `DQ_TABLE_SCHEMA`, `APP_TABLE_SCHEMA`, `DB_ECHO` |
| Khác | `PAGE_SIZE` (25), `EXPORT_MAX_ROWS` (100000, áp cho cả file xuất loại trừ), `EXCLUSION_REASON_MIN_LENGTH` (10; tên cũ `EXCEPTION_REASON_MIN_LENGTH` vẫn được đọc), `EXCLUSION_UPLOAD_MAX_ROWS` (2000), `EXCLUSION_UPLOAD_MAX_MB` (5) |

Tài khoản giả lập (`MOCK_LDAP=true`):

| Tài khoản | Mật khẩu | Nhóm | Chi nhánh |
|---|---|---|---|
| `admin` | `Admin@123` | DQ_ADMIN | HO |
| `approver` | `Approver@123` | DQ_APPROVER (QTDL) | HO |
| `business` | `Business@123` | DQ_BUSINESS | HO |
| `hn.manager` | `Manager@123` | DQ_MANAGER | HN001 |
| `hcm.manager` | `Manager@123` | DQ_MANAGER | HCM01 |
| `hn.user` | `User@123` | DQ_USER | HN001 |
| `hcm.user` | `User@123` | DQ_USER | HCM01 |
| `guest` | `Guest@123` | không có nhóm DQ, bị từ chối | DN001 |

Trong dữ liệu seed, các yêu cầu loại trừ do `hn.user`, `hcm.user` hoặc `<mã cn>.user` gửi; cấp LĐ phòng do `hn.manager`, `hcm.manager`
hoặc `<mã cn>.manager`, cấp nghiệp vụ do `business`, cấp QTDL do `approver` duyệt.

## 13. Bẫy đã gặp & lưu ý

- **`requirements.txt` chỉ được chứa ký tự ASCII.** pip trên Windows đọc file bằng cp1252 nên lỗi với chú thích tiếng Việt có dấu.
- `fastapi.testclient` phát `StarletteDeprecationWarning` (khuyên dùng `httpx2`). Cảnh báo này chỉ ảnh hưởng test, không ảnh hưởng app.
- `Identity()` trên cột PK dùng được cho SQLite, PostgreSQL, Oracle và SQL Server. Seed lỗi DQ vẫn INSERT id tường minh; seed yêu cầu loại trừ để DB tự sinh id.
- Flash message được HTML-escape khi render, nên ký tự `'` thành `&#39;`. Test so sánh chuỗi cần lưu ý điều này.
- Đổi quyền, khóa hoặc xóa phân quyền có hiệu lực ngay vì `resolve_user` chạy mỗi request. Đổi lại, mỗi request tốn thêm một truy vấn `db.get(UserPermission)`.
- `pending_exclusions()` trong menu mở thêm một DB session cho mỗi trang render. Chấp nhận được ở quy mô LAN.
- `list_branches` là `SELECT DISTINCT` trên bảng lỗi DQ, chạy ở mỗi lần mở trang loại trừ và mỗi lô tạo yêu cầu.
  Bảng lỗi thật rất lớn thì cần index trên `branch_code` (model đã khai báo `index=True`) hoặc thay bằng bảng danh mục chi nhánh.
- Vai trò `approver` (giá trị lưu trong `dq_user_permissions.role`) giữ nguyên từ bản phê duyệt 1 cấp và nay là **Phê duyệt QTDL**;
  đừng đổi giá trị enum này nếu không migrate dữ liệu phân quyền.
- Bỏ qua cấp LĐ phòng ban chỉ áp dụng khi **người gửi là admin** (`first_status`); không có cấu hình bỏ cấp theo chi nhánh.
- Trên máy dev, PATH hệ thống (Machine) vẫn trỏ Python 3.12, nên lệnh `python` / `uvicorn` có thể chưa phải 3.13. Luôn gọi `py -3.13` (và `py -3.13 -m uvicorn`).

## 14. Giới hạn hiện tại / hướng mở rộng

- Chưa có bộ test trong repo (xem §2) và chưa có migration tool (Alembic); schema được tạo bằng `create_all`.
- Chưa có thông báo email khi có yêu cầu hoặc khi được duyệt; file xuất không đánh dấu "đã xuất" (xuất theo bộ lọc, có thể trùng giữa các lần).
- Luồng duyệt cố định 3 cấp tuần tự; phê duyệt nghiệp vụ duyệt mọi quy tắc (chưa phân theo đơn vị phụ trách quy tắc).
- Tìm kiếm không phân biệt dấu tiếng Việt (ví dụ "ha noi" khớp "Hà Nội") chưa được hỗ trợ.
- Chưa có kiểm tra bản ghi có thật sự tồn tại trong hệ thống nguồn (chỉ kiểm tra mã quy tắc / chi nhánh).
- Nhánh LDAP thật chưa được kiểm thử với Domain Controller.
