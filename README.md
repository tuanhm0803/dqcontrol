# DQ Dashboard – Quản lý lỗi Chất lượng Dữ liệu (mạng nội bộ)

Ứng dụng FastAPI + Jinja2 + Bootstrap 5:
- Đăng nhập bằng Active Directory, phân quyền theo nhóm AD và có trang quản trị phân quyền nội bộ.
- Cập nhật trạng thái xử lý lỗi, với luồng **yêu cầu và phê duyệt ngoại lệ**.
- Xuất báo cáo Excel/CSV theo đúng bộ lọc đang xem.

## Cấu trúc thư mục

```
.
├── main.py                 # Khởi chạy FastAPI, middleware (session, gzip, security headers), handler lỗi, routers
├── config.py               # Đọc cấu hình từ biến môi trường / .env (AD, DB, session...)
├── database.py             # Engine/Session, khởi tạo bảng, nạp dữ liệu giả lập, fallback; CLI init-db / reset-mock
├── repository.py           # Truy vấn lỗi DQ: tìm kiếm, lọc, thống kê, danh sách chi nhánh
├── workflow.py             # Nghiệp vụ: cập nhật trạng thái, luồng ngoại lệ, nhật ký hệ thống
├── auth.py                 # Xác thực AD (ldap3), tính quyền hiệu lực (AD + nội bộ), CSRF
├── models.py               # SQLAlchemy models + Pydantic schemas + enum trạng thái / vai trò
├── mock_data.py            # 480 lỗi DQ + lịch sử ngoại lệ giả lập + tài khoản AD giả lập
├── routers/
│   ├── __init__.py         # Jinja2Templates, flash message, helper dùng chung
│   ├── auth_router.py      # GET/POST /login, POST /logout, GET /api/me
│   ├── dq_router.py        # GET /dashboard, POST /dq/status, GET /api/dq-errors
│   ├── exception_router.py # /exceptions: danh sách, gửi yêu cầu, duyệt, từ chối, hủy, thu hồi
│   ├── admin_router.py     # /admin/permissions: phân quyền nội bộ + nhật ký hệ thống
│   └── export_router.py    # GET /export/excel, GET /export/csv
├── templates/
│   ├── base.html           # Layout chung, menu, header User / Role / Chi nhánh, flash message
│   ├── login.html
│   ├── dashboard.html      # KPI, bộ lọc, bảng lỗi, thao tác hàng loạt, nút xuất file
│   ├── exceptions.html     # Danh sách yêu cầu ngoại lệ, phê duyệt / từ chối hàng loạt
│   ├── admin_permissions.html
│   ├── error.html          # Trang 403 / 404
│   └── _pagination.html
├── static/css/app.css
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

## Chế độ dev / offline

Mặc định `MOCK_LDAP=true` và `USE_MOCK_DATA=true`, nên chạy được ngay mà không cần AD hay CSDL.
Ở chế độ này dữ liệu giả lập được nạp vào file SQLite `dq_mock.db` trong lần chạy đầu.
Các thay đổi (trạng thái, ngoại lệ, phân quyền) được giữ lại giữa các lần khởi động.
Muốn làm mới dữ liệu: `py -3.13 database.py reset-mock`.

| Tài khoản  | Mật khẩu       | Nhóm AD     | Vai trò                                     |
|------------|----------------|-------------|---------------------------------------------|
| `admin`    | `Admin@123`    | DQ_ADMIN    | Quản trị DQ – toàn hệ thống                 |
| `approver` | `Approver@123` | DQ_APPROVER | Người phê duyệt – toàn hệ thống             |
| `hn.user`  | `User@123`     | DQ_USER     | User chi nhánh HN001                        |
| `hcm.user` | `User@123`     | DQ_USER     | User chi nhánh HCM01                        |
| `guest`    | `Guest@123`    | —           | Bị từ chối                                  |

## Phân quyền

### Vai trò và chức năng

| Chức năng                                | Quản trị DQ | Người phê duyệt | User chi nhánh |
|------------------------------------------|:-----------:|:---------------:|:--------------:|
| Xem dashboard, xuất Excel/CSV            | ✔           | ✔               | ✔              |
| Cập nhật trạng thái xử lý                | ✔           |                 | ✔              |
| Gửi / hủy yêu cầu ngoại lệ               | ✔           |                 | ✔              |
| Phê duyệt / từ chối ngoại lệ             | ✔           | ✔               |                |
| Thu hồi ngoại lệ đã duyệt                | ✔           |                 |                |
| Quản trị phân quyền, xem nhật ký         | ✔           |                 |                |
| Phạm vi dữ liệu                          | Toàn hệ thống | Toàn hệ thống hoặc 1 chi nhánh | 1 chi nhánh |

### Nguồn quyền

1. **Phân quyền nội bộ** (trang *Quản trị phân quyền*, bảng `dq_user_permissions`) có ưu tiên cao nhất.
   Admin đổi được vai trò, chi nhánh và phạm vi xem của từng tài khoản, hoặc **khóa** tài khoản.
   Quyền được tính lại ở mỗi request, nên thay đổi có hiệu lực ngay mà người dùng không phải đăng nhập lại.
2. Nếu không có phân quyền nội bộ, quyền được xét theo **nhóm AD** với thứ tự ưu tiên
   `LDAP_GROUP_ADMIN` → `LDAP_GROUP_APPROVER` → `LDAP_GROUP_USER`.
   Mã chi nhánh lấy từ thuộc tính AD `LDAP_BRANCH_ATTRIBUTE`.
3. Không thuộc nhóm nào và không có phân quyền nội bộ thì bị từ chối.

Phạm vi chi nhánh được áp ở phía server cho mọi truy vấn và thao tác: dashboard, API, export, ngoại lệ.
Người dùng sửa URL hay form cũng không thao tác được trên chi nhánh khác.
Admin không thể tự hạ quyền, tự khóa hay tự xóa phân quyền của chính mình.

## Trạng thái lỗi & luồng phê duyệt ngoại lệ

```
                 cập nhật thủ công
  Chưa xử lý  <────────────────────>  Đang xử lý  ────────>  Hoàn thành  (ghi Ngày xử lý)
      │                                   │
      └──────── gửi yêu cầu ngoại lệ ─────┘   (User chi nhánh / Admin, bắt buộc nhập lý do)
                        │
                        ▼
              Chờ duyệt ngoại lệ ── từ chối (bắt buộc ghi chú) / người gửi hủy ──> về trạng thái trước đó
                        │
                        │ phê duyệt (Người phê duyệt / Admin, không được tự duyệt yêu cầu của mình)
                        ▼
              Ngoại lệ đã duyệt  (ghi Ngày phê duyệt)  ── Admin thu hồi ──> về trạng thái trước đó
```

- **Cột "Ngày xử lý / Phê duyệt NL"** cùng người thực hiện được ghi khi lỗi chuyển sang *Hoàn thành* hoặc *Ngoại lệ đã duyệt*.
  Cột này bị xóa khi lỗi mở lại, bị từ chối hoặc bị thu hồi. Cột cũng có trong file Excel/CSV.
- **Thao tác hàng loạt:** tick chọn nhiều dòng trên Dashboard để cập nhật trạng thái hoặc gửi yêu cầu ngoại lệ.
  Trên trang *Ngoại lệ*, tick chọn nhiều yêu cầu để phê duyệt hoặc từ chối. Dòng không hợp lệ được bỏ qua và báo lý do.
- Toàn bộ lịch sử yêu cầu nằm ở bảng `dq_exception_requests`. Bấm vào badge trạng thái ngoại lệ trên Dashboard để xem lịch sử của lỗi đó.
- **Nhật ký** được ghi vào `dq_audit_log` cho các thao tác: đăng nhập, cập nhật trạng thái, ngoại lệ, phân quyền, xuất file.

## Kết nối CSDL thật

1. Bỏ comment driver tương ứng trong `requirements.txt` và chạy lại `py -3.13 -m pip install -r requirements.txt`.
2. Trong `.env`: `USE_MOCK_DATA=false`, `DATABASE_URL=...`, `DQ_TABLE_NAME`, `DQ_TABLE_SCHEMA`, `APP_TABLE_SCHEMA`.
3. Nếu bảng thật có tên cột khác, sửa tham số đầu của `mapped_column(...)` trong `models.py`.
4. **Bảng lỗi DQ cần thêm 2 cột** để lưu ngày và người xử lý / phê duyệt. Tài khoản kết nối cần quyền `UPDATE`
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
5. Ba bảng của ứng dụng (`dq_exception_requests`, `dq_user_permissions`, `dq_audit_log`) được **tự tạo** khi khởi động.
   Tài khoản cần quyền `CREATE TABLE`, hoặc DBA tạo trước.
6. Muốn thử nhanh với CSDL trống: `py -3.13 database.py init-db --seed`. Lệnh này tạo toàn bộ bảng và nạp dữ liệu mẫu.

Nếu không kết nối được CSDL hoặc bảng thiếu cột mà `DB_FALLBACK_TO_MOCK=true`, ứng dụng ghi log lỗi và chuyển sang dữ liệu giả lập
(footer hiển thị badge "Dữ liệu giả lập"). Ở môi trường thật nên đặt `false` để lỗi hiện rõ ngay khi khởi động.

## Ghi chú bảo mật

- Dùng LDAPS (`LDAP_USE_SSL=true`, cổng 636): bind SIMPLE qua LDAP thường gửi mật khẩu dạng rõ trên mạng.
- Mật khẩu rỗng bị chặn trước khi bind (AD chấp nhận "unauthenticated bind" với mật khẩu rỗng).
- Mọi form thay đổi dữ liệu đều có CSRF token. Cookie session dùng `SameSite=Lax`.
- Đặt `SECRET_KEY` cố định; nếu chạy sau reverse proxy HTTPS thì bật `SESSION_HTTPS_ONLY=true`.
