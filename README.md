# DQ Dashboard – Yêu cầu loại trừ Chất lượng Dữ liệu (mạng nội bộ)

Ứng dụng FastAPI + Jinja2 + Bootstrap 5:
- Đăng nhập bằng Active Directory, phân quyền theo nhóm AD và có trang quản trị phân quyền nội bộ.
- **Khai báo yêu cầu loại trừ** (nhập tay hoặc upload file Excel theo mẫu): loại trừ một bản ghi khỏi một quy tắc DQ.
- **Phê duyệt 3 cấp**: Lãnh đạo phòng ban (chi nhánh) → Phê duyệt nghiệp vụ → Phê duyệt QTDL, và **xuất ngược** các yêu cầu
  đã duyệt ra Excel/CSV để hệ thống DQ xử lý tiếp.
- **Danh mục mã quy tắc** do Quản trị DQ cập nhật (thêm / sửa / ngừng dùng, upload Excel thay thế toàn bộ).
- Dashboard lỗi DQ chỉ dành cho Quản trị DQ, Phê duyệt QTDL và Phê duyệt nghiệp vụ; cấp chi nhánh không xem lỗi.

## Cấu trúc thư mục

```
.
├── main.py                 # Khởi chạy FastAPI, middleware (session, gzip, security headers), handler lỗi, routers
├── config.py               # Đọc cấu hình từ biến môi trường / .env (AD, DB, session...)
├── database.py             # Engine/Session, khởi tạo bảng, nạp dữ liệu giả lập, fallback; CLI init-db / reset-mock
├── repository.py           # Truy vấn lỗi DQ: tìm kiếm, lọc, thống kê; danh mục chi nhánh (bảng lỗi) / mã quy tắc (dq_rules)
├── workflow.py             # Nghiệp vụ: cập nhật trạng thái, luồng yêu cầu loại trừ, nhật ký hệ thống
├── auth.py                 # Xác thực AD (ldap3), tính quyền hiệu lực (AD + nội bộ), CSRF
├── models.py               # SQLAlchemy models + Pydantic schemas + enum trạng thái / vai trò
├── mock_data.py            # 480 lỗi DQ + yêu cầu loại trừ giả lập + tài khoản AD giả lập
├── routers/
│   ├── __init__.py         # Jinja2Templates, flash message, helper dùng chung
│   ├── auth_router.py      # GET/POST /login, POST /logout, GET /api/me
│   ├── dq_router.py        # GET /dashboard, POST /dq/status, GET /api/dq-errors
│   ├── exclusion_router.py # /exclusions: danh sách, khai báo, upload, duyệt, từ chối, hủy, thu hồi, xuất file
│   ├── exclusion_files.py  # File mẫu Excel, đọc file upload, dựng file xuất yêu cầu đã duyệt
│   ├── admin_router.py     # /admin/permissions: phân quyền nội bộ + nhật ký; /admin/rules: danh mục mã quy tắc
│   └── export_router.py    # GET /export/excel, GET /export/csv
├── templates/
│   ├── base.html           # Layout chung, menu, header User / Role / Chi nhánh, flash message
│   ├── login.html
│   ├── dashboard.html      # KPI, bộ lọc, bảng lỗi, thao tác hàng loạt, nút xuất file
│   ├── exclusions.html     # Danh sách yêu cầu loại trừ, phê duyệt / từ chối hàng loạt, xuất file đã duyệt
│   ├── exclusion_new.html  # Khai báo loại trừ: nhập tay + upload Excel
│   ├── admin_permissions.html
│   ├── admin_rules.html    # Danh mục mã quy tắc: thêm / sửa / ngừng dùng, tải về, upload thay thế
│   ├── error.html          # Trang 403 / 404
│   └── _pagination.html
├── static/css/app.css
├── Dockerfile              # Image production
├── deploy/                 # docker-compose.yml chạy trên VPS (sau edge-nginx)
├── .github/workflows/deploy.yml  # CI/CD: build image -> GHCR -> deploy VPS
├── requirements.txt
└── .env.example
```

## Cài đặt & chạy

```powershell
# Cài thẳng vào Python 3.13 của máy (không dùng venv). Linux: dùng python3.13 thay cho py -3.13
py -3.13 -m pip install -r requirements.txt
copy .env.example .env            # chỉnh sửa cấu hình

py -3.13 -m uvicorn main:app --host 0.0.0.0 --port 8080
```

### Cài offline (máy không có Internet)

Trên máy có mạng, tải sẵn toàn bộ thư viện (Windows 64-bit, Python 3.13) vào thư mục `wheels/`:

```powershell
py -3.13 -m pip download -r requirements.txt -d wheels --only-binary=:all:
py -3.13 -m pip download pyodbc oracledb psycopg2-binary -d wheels\drivers --only-binary=:all:   # driver CSDL (tùy chọn)
```

Copy cả thư mục project (gồm `wheels/`) sang máy đích, cài Python 3.13 64-bit, rồi chạy:

```powershell
py -3.13 -m pip install --no-index --find-links wheels -r requirements.txt
py -3.13 -m pip install --no-index --find-links wheels\drivers pyodbc      # hoặc oracledb / psycopg2-binary
```

Máy khác trong LAN truy cập: `http://<IP-máy-chủ>:8080` (xem IP bằng `ipconfig`).
Trên Windows cần mở firewall (PowerShell quyền Admin):

```powershell
New-NetFirewallRule -DisplayName "DQ Dashboard 8080" -Direction Inbound -Protocol TCP -LocalPort 8080 -Action Allow -Profile Domain,Private
```

Chạy nhiều tiến trình cho nhiều người dùng đồng thời: `py -3.13 -m uvicorn main:app --host 0.0.0.0 --port 8080 --workers 4`
(bắt buộc đặt `SECRET_KEY` cố định, nếu không mỗi worker có khóa khác nhau và session sẽ không hợp lệ).

## Deploy production (VPS, https://dq.tuanhm.pro)

Bản trên VPS là **bản demo**: dùng tài khoản và dữ liệu giả lập (`MOCK_LDAP=true`, `USE_MOCK_DATA=true`),
mật khẩu như bảng ở mục *Chế độ dev / offline*. Ai biết mật khẩu trong README đều đăng nhập được, kể cả `admin`,
nên **không đưa dữ liệu thật lên bản này**.

Luồng: push lên `main` (hoặc bấm *Run workflow*) → `.github/workflows/deploy.yml` build image từ `Dockerfile`,
đẩy lên `ghcr.io/tuanhm0803/dqcontrol` → SSH vào VPS `72.60.43.33`, copy `deploy/docker-compose.yml` vào `/opt/dqcontrol`,
ghi `app.env` rồi chạy `docker compose up -d` → kiểm tra `https://dq.tuanhm.pro/health`.

HTTPS do proxy dùng chung **`edge-nginx`** (repo `tuanhm_edge_proxy`, thư mục `/opt/edge` trên VPS) đảm nhận.
Proxy này route `dq.tuanhm.pro` tới container `dq-app:8080` qua mạng Docker `edge-network`, còn `edge-certbot`
tự xin và gia hạn chứng chỉ Let's Encrypt. Container `dq-app` không mở cổng nào ra host.

### GitHub Secrets (Settings → Secrets and variables → Actions)

| Secret | Bắt buộc | Giá trị |
|---|:-:|---|
| `VPS_HOST` | ✔ | `72.60.43.33` |
| `VPS_USERNAME` | ✔ | `root` |
| `VPS_SSH_KEY` | ✔ | Private key SSH vào VPS (dùng chung giá trị với repo `tuanhm_edge_proxy`) |
| `SECRET_KEY` | ✔ | `py -3.13 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `VPS_PORT` | | `22` (mặc định) |
| `VPS_KNOWN_HOSTS` | | Kết quả `ssh-keyscan 72.60.43.33` (khuyến nghị; bỏ trống thì workflow tự quét) |
| `APP_ENV_EXTRA` | | Biến môi trường thêm cho app, mỗi dòng `KEY=VALUE` (ghi đè giá trị mặc định) |

### Vận hành trên VPS

```bash
cd /opt/dqcontrol
docker compose ps
docker compose logs -f app
docker compose exec app python database.py reset-mock && docker compose restart app   # làm mới dữ liệu demo
docker logs edge-certbot                                                              # tình trạng chứng chỉ
```

Dữ liệu SQLite nằm trong volume `dq-data`, deploy lại không làm mất.
Rollback: đổi `APP_IMAGE` trong `/opt/dqcontrol/.env` sang tag commit cũ (`ghcr.io/tuanhm0803/dqcontrol:<sha>`)
rồi chạy `docker compose up -d`, hoặc chạy lại workflow của commit đó trên GitHub.

## Chế độ dev / offline

Mặc định `MOCK_LDAP=true` và `USE_MOCK_DATA=true`, nên chạy được ngay mà không cần AD hay CSDL.
Ở chế độ này dữ liệu giả lập được nạp vào file SQLite `dq_mock.db` trong lần chạy đầu.
Các thay đổi (trạng thái, yêu cầu loại trừ, phân quyền) được giữ lại giữa các lần khởi động.
Muốn làm mới dữ liệu: `py -3.13 database.py reset-mock`.

| Tài khoản  | Mật khẩu       | Nhóm AD     | Vai trò                                     |
|------------|----------------|-------------|---------------------------------------------|
| `admin`    | `Admin@123`    | DQ_ADMIN    | Quản trị DQ – toàn hệ thống                 |
| `approver` | `Approver@123` | DQ_APPROVER | Phê duyệt QTDL – toàn hệ thống              |
| `business` | `Business@123` | DQ_BUSINESS | Phê duyệt nghiệp vụ – toàn hệ thống         |
| `hn.manager` | `Manager@123` | DQ_MANAGER | Lãnh đạo phòng ban chi nhánh HN001        |
| `hcm.manager` | `Manager@123` | DQ_MANAGER | Lãnh đạo phòng ban chi nhánh HCM01       |
| `hn.user`  | `User@123`     | DQ_USER     | User chi nhánh HN001                        |
| `hcm.user` | `User@123`     | DQ_USER     | User chi nhánh HCM01                        |
| `guest`    | `Guest@123`    | —           | Bị từ chối                                  |

## Phân quyền

### Vai trò và chức năng

| Chức năng | Quản trị DQ | Phê duyệt QTDL | Phê duyệt nghiệp vụ | LĐ phòng ban | User chi nhánh |
|---|:-:|:-:|:-:|:-:|:-:|
| Xem dashboard lỗi DQ, xuất Excel/CSV lỗi | ✔ | ✔ | ✔ | | |
| Cập nhật trạng thái xử lý lỗi | ✔ | | | | |
| Khai báo / upload / hủy yêu cầu loại trừ (mọi chi nhánh) | ✔ | | | | ✔ |
| Duyệt / từ chối cấp 1 – LĐ phòng ban | ✔ | | | ✔ (chi nhánh mình) | |
| Duyệt / từ chối cấp 2 – Nghiệp vụ | ✔ | | ✔ | | |
| Duyệt / từ chối cấp 3 – QTDL (cấp cuối) | ✔ | ✔ | | | |
| Thu hồi yêu cầu loại trừ đã duyệt | ✔ | | | | |
| Xem và xuất yêu cầu loại trừ đã duyệt | ✔ | ✔ | ✔ | ✔ | ✔ |
| Danh mục mã quy tắc, phân quyền, nhật ký | ✔ | | | | |
| Phạm vi dữ liệu | Toàn hệ thống | Toàn hệ thống hoặc 1 CN | Toàn hệ thống hoặc 1 CN | 1 chi nhánh | 1 chi nhánh |

Sau khi đăng nhập, Quản trị DQ / Phê duyệt QTDL / Phê duyệt nghiệp vụ vào Dashboard lỗi DQ; cấp chi nhánh vào thẳng trang *Yêu cầu loại trừ*.
Vai trò *Phê duyệt QTDL* chính là vai trò "Người phê duyệt" của bản trước (cùng mã `approver`, cùng nhóm AD `LDAP_GROUP_APPROVER`).

### Nguồn quyền

1. **Phân quyền nội bộ** (trang *Quản trị phân quyền*, bảng `dq_user_permissions`) có ưu tiên cao nhất.
   Admin đổi được vai trò, chi nhánh và phạm vi xem của từng tài khoản, hoặc **khóa** tài khoản.
   Quyền được tính lại ở mỗi request, nên thay đổi có hiệu lực ngay mà người dùng không phải đăng nhập lại.
2. Nếu không có phân quyền nội bộ, quyền được xét theo **nhóm AD** với thứ tự ưu tiên
   `LDAP_GROUP_ADMIN` → `LDAP_GROUP_APPROVER` (QTDL) → `LDAP_GROUP_BUSINESS` (nghiệp vụ) → `LDAP_GROUP_MANAGER` (LĐ phòng ban)
   → `LDAP_GROUP_USER`.
   Mã chi nhánh lấy từ thuộc tính AD `LDAP_BRANCH_ATTRIBUTE`.
3. Không thuộc nhóm nào và không có phân quyền nội bộ thì bị từ chối.

Phạm vi chi nhánh được áp ở phía server cho mọi truy vấn và thao tác: dashboard, API, export, yêu cầu loại trừ.
Người dùng sửa URL hay form cũng không thao tác được trên chi nhánh khác.
Admin không thể tự hạ quyền, tự khóa hay tự xóa phân quyền của chính mình.

## Yêu cầu loại trừ

Mỗi yêu cầu loại trừ **một bản ghi** (số CIF / số tài khoản / số hợp đồng...) khỏi **một quy tắc DQ** của **một chi nhánh**:

| Trường | Bắt buộc | Ghi chú |
|---|:-:|---|
| Mã chi nhánh | ✔ | Mặc định = chi nhánh của người khai báo, **sửa được** sang chi nhánh khác (bỏ trống trong file = chi nhánh của mình) |
| Mã quy tắc DQ | ✔ | Phải có trong **danh mục mã quy tắc** và đang dùng (xem mục *Danh mục mã quy tắc*). **Tên quy tắc** tự hiện bên cạnh |
| Mã bản ghi | ✔ | Tối đa 100 ký tự, giữ nguyên số 0 đầu |
| Lý do loại trừ | ✔ | Tối thiểu `EXCLUSION_REASON_MIN_LENGTH` ký tự (mặc định 10) |
| Hiệu lực đến | ✔ | Từ hôm nay trở đi; form nhập trực tiếp điền sẵn **1 tháng** kể từ hôm nay |

### Khai báo (menu *Khai báo loại trừ*)

- **Nhập trực tiếp:** bảng nhiều dòng, **mỗi dòng một yêu cầu** (chi nhánh, mã quy tắc + tên quy tắc, mã bản ghi, lý do, hiệu lực),
  gửi tất cả cùng lúc (tối đa 200 dòng). Dòng mới có sẵn chi nhánh của bạn và hiệu lực 1 tháng. Có nút thêm dòng, *nhân bản dòng* (giữ quy tắc / lý do / hiệu lực, chỉ cần nhập mã bản ghi mới), xóa dòng,
  và **dán nhiều dòng copy từ Excel** vào bất kỳ ô nào. Dòng hợp lệ được gửi ngay; dòng lỗi được giữ lại trên form, tô đỏ kèm lý do để sửa và gửi lại.
- **Upload Excel:** tải *file mẫu* (có sẵn dropdown mã quy tắc / chi nhánh, cột tên quy tắc tự hiện bằng công thức và sheet hướng dẫn),
  điền mỗi dòng một bản ghi rồi upload.
  Chỉ nhận `.xlsx`, tối đa `EXCLUSION_UPLOAD_MAX_ROWS` dòng (2000) và `EXCLUSION_UPLOAD_MAX_MB` MB (5).
- Dòng sai (thiếu cột, mã quy tắc không có trong danh mục / đã ngừng dùng, chi nhánh không tồn tại, thiếu hoặc sai ngày hiệu lực...), trùng dòng khác trong cùng lần gửi,
  hoặc **trùng một yêu cầu *Đã duyệt* còn hiệu lực** cho cùng chi nhánh + quy tắc + mã bản ghi sẽ bị bỏ qua và báo theo số dòng;
  các dòng hợp lệ vẫn được gửi.
- Yêu cầu **đang chờ duyệt không chặn** gửi thêm: cùng một bản ghi có thể có nhiều yêu cầu chờ duyệt. Khi duyệt, nếu bản ghi đã có
  một yêu cầu được duyệt còn hiệu lực thì các yêu cầu sau bị bỏ qua (file xuất không bị trùng).

### Luồng phê duyệt (3 cấp, tuần tự)

```
  Khai báo (User chi nhánh)                         Khai báo (Quản trị DQ)
            │                                                │
            ▼                                                │  bỏ qua cấp 1
  Chờ LĐ phòng duyệt ── LĐ phòng ban của chi nhánh duyệt ──┐ │
                                                           ▼ ▼
                                                Chờ duyệt nghiệp vụ ── Phê duyệt nghiệp vụ duyệt ──┐
                                                                                                   ▼
                                                                        Chờ duyệt QTDL ── Phê duyệt QTDL duyệt ──> Đã duyệt
  Ở bất kỳ cấp nào: từ chối (bắt buộc ghi chú) ──> Từ chối;  người gửi / admin hủy ──> Đã hủy
  Đã duyệt ── Quản trị DQ thu hồi (bắt buộc ghi chú) ──> Đã thu hồi
```

- Quản trị DQ duyệt được mọi cấp. **Không ai duyệt yêu cầu của chính mình, và một người không duyệt 2 cấp của cùng yêu cầu.**
- LĐ phòng ban chỉ duyệt yêu cầu của chi nhánh mình (theo chi nhánh ghi trên yêu cầu).
- Trang *Yêu cầu loại trừ* có 3 tab: *Chờ tôi duyệt* (chỉ yêu cầu đang ở cấp của bạn), *Yêu cầu của tôi*, *Tất cả / Lịch sử*.
  Cột *Tiến trình duyệt* hiện người / thời điểm duyệt từng cấp; cột *Ghi chú* là nhật ký ghi chú của các cấp.
  Tick chọn nhiều yêu cầu để duyệt hoặc từ chối hàng loạt; yêu cầu bạn không duyệt được có biểu tượng khóa (di chuột để xem lý do).
- Badge trên menu đếm số yêu cầu bạn duyệt được ngay.
- Yêu cầu đã quá ngày *Hiệu lực đến* thì không duyệt được nữa.
- Yêu cầu bị từ chối / hủy / thu hồi, hoặc đã hết hiệu lực, có thể được khai báo lại.
- User chi nhánh xem được yêu cầu của chi nhánh mình **và** các yêu cầu do chính mình gửi cho chi nhánh khác.

### Xuất yêu cầu đã duyệt để xử lý tiếp

Nút **Xuất yêu cầu đã duyệt** trên trang *Yêu cầu loại trừ* xuất Excel/CSV các yêu cầu *Đã duyệt* theo bộ lọc:
chi nhánh, mã quy tắc, khoảng ngày duyệt hoàn tất (ngày QTDL duyệt), *chỉ yêu cầu còn hiệu lực* (mặc định bật). Không đánh dấu "đã xuất", nên xuất lại bao nhiêu lần cũng được.

- Sheet dữ liệu có **tiêu đề ở dòng 1** để hệ thống khác đọc thẳng; metadata (phạm vi, bộ lọc, người xuất) nằm ở sheet *Thông tin*.
- Cột: Mã chi nhánh, Mã quy tắc DQ, Tên quy tắc DQ, Mã bản ghi, Lý do loại trừ, Hiệu lực đến, Mã yêu cầu, Người gửi, Ngày gửi,
  người duyệt + ngày duyệt của từng cấp (LĐ phòng ban, Nghiệp vụ, QTDL), Ghi chú duyệt. Tiêu đề cột giống file mẫu nên file xuất
  cũng upload lại được.
- CSV mã hóa UTF-8 có BOM để Excel mở đúng tiếng Việt; mỗi yêu cầu đúng một dòng (ghi chú nhiều dòng được nối bằng ` | `).

## Danh mục mã quy tắc (menu *Danh mục quy tắc*, chỉ Quản trị DQ)

- **Thêm / sửa** từng mã (mã chỉ gồm chữ, số, `_ . -`, tự chuyển chữ hoa; tên bắt buộc), bật / tắt **Đang dùng**.
  Mã *Ngừng dùng* không khai báo loại trừ mới được, nhưng yêu cầu cũ vẫn hiển thị tên.
- **Tải danh mục (.xlsx)**: file hiện tại, đồng thời là file mẫu để upload.
- **Upload thay thế toàn bộ**: mọi mã trong file được thêm / cập nhật tên và chuyển *Đang dùng*; mã đang có mà **không có trong file
  chuyển Ngừng dùng** (không xóa). Chỉ cần một dòng sai (thiếu tên, mã sai định dạng, trùng mã) thì cả file bị từ chối, danh mục giữ nguyên.
- Danh mục trống thì người dùng không khai báo được yêu cầu nào. Ở chế độ giả lập danh mục được nạp sẵn 16 mã;
  với CSDL thật, admin cần upload danh mục lần đầu.

## Trạng thái lỗi DQ (dashboard)

`Chưa xử lý` ⇄ `Đang xử lý` → `Hoàn thành`. Chỉ **Quản trị DQ** cập nhật được (tick nhiều dòng trên dashboard);
khi chuyển sang *Hoàn thành* thì ghi *Ngày xử lý* và người xử lý. Yêu cầu loại trừ không làm thay đổi trạng thái lỗi.

**Nhật ký** được ghi vào `dq_audit_log` cho các thao tác: đăng nhập, cập nhật trạng thái, khai báo / upload / duyệt / từ chối / hủy /
thu hồi / xuất yêu cầu loại trừ, cập nhật / upload danh mục quy tắc, phân quyền, xuất file lỗi.

## Kết nối CSDL thật

1. Bỏ comment driver tương ứng trong `requirements.txt` và chạy lại `py -3.13 -m pip install -r requirements.txt`.
2. Trong `.env`: `USE_MOCK_DATA=false`, `DATABASE_URL=...`, `DQ_TABLE_NAME`, `DQ_TABLE_SCHEMA`, `APP_TABLE_SCHEMA`.
3. Nếu bảng thật có tên cột khác, sửa tham số đầu của `mapped_column(...)` trong `models.py`.
4. **Bảng lỗi DQ cần thêm 2 cột** để lưu ngày và người xử lý. Tài khoản kết nối cần quyền `UPDATE`
   trên các cột `status`, `resolved_date`, `resolved_by`:

   ```sql
   -- SQL Server
   ALTER TABLE dq_errors ADD resolved_date DATE NULL, resolved_by NVARCHAR(100) NULL;
   -- Oracle
   ALTER TABLE dq_errors ADD (resolved_date DATE, resolved_by VARCHAR2(100));
   -- PostgreSQL
   ALTER TABLE dq_errors ADD COLUMN resolved_date DATE, ADD COLUMN resolved_by VARCHAR(100);
   ```

   Khi khởi động, ứng dụng kiểm tra các cột này và báo lỗi rõ ràng nếu còn thiếu.
5. Bốn bảng của ứng dụng (`dq_rules`, `dq_exclusion_requests`, `dq_user_permissions`, `dq_audit_log`) được **tự tạo** khi khởi động.
   Tài khoản cần quyền `CREATE TABLE`, hoặc DBA tạo trước. Bảng `dq_exception_requests` của phiên bản cũ không còn được dùng
   (ứng dụng không tự xóa; DBA có thể xóa). Nếu bảng của app đã có từ phiên bản cũ mà thiếu cột (vd. các cột duyệt nhiều cấp
   `manager_*`, `business_*`, `dq_*`), ứng dụng báo rõ tên cột khi khởi động; DBA cần `ALTER TABLE` thêm cột.
   Danh mục chi nhánh lấy từ bảng lỗi DQ (`SELECT DISTINCT`); danh mục mã quy tắc do admin upload (bảng `dq_rules`).
6. Muốn thử nhanh với CSDL trống: `py -3.13 database.py init-db --seed`. Lệnh này tạo toàn bộ bảng và nạp dữ liệu mẫu
   (kể cả danh mục mã quy tắc mẫu).
7. Nhóm AD mới: `LDAP_GROUP_BUSINESS` (mặc định `DQ_BUSINESS`) và `LDAP_GROUP_MANAGER` (mặc định `DQ_MANAGER`);
   hoặc gán vai trò bằng phân quyền nội bộ.

Nếu không kết nối được CSDL hoặc bảng thiếu cột mà `DB_FALLBACK_TO_MOCK=true`, ứng dụng ghi log lỗi và chuyển sang dữ liệu giả lập
(footer hiển thị badge "Dữ liệu giả lập"). Ở môi trường thật nên đặt `false` để lỗi hiện rõ ngay khi khởi động.

## Ghi chú bảo mật

- Dùng LDAPS (`LDAP_USE_SSL=true`, cổng 636): bind SIMPLE qua LDAP thường gửi mật khẩu dạng rõ trên mạng.
- Mật khẩu rỗng bị chặn trước khi bind (AD chấp nhận "unauthenticated bind" với mật khẩu rỗng).
- Mọi form thay đổi dữ liệu đều có CSRF token. Cookie session dùng `SameSite=Lax`.
- Đặt `SECRET_KEY` cố định; nếu chạy sau reverse proxy HTTPS thì bật `SESSION_HTTPS_ONLY=true`.
