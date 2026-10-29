# Hướng dẫn deploy DQ Dashboard trên máy Windows công ty

Không cần quyền Administrator, không cần Internet. Chỉ gồm: cài Python → cài thư viện → tạo `.env` → chạy `uvicorn`.

## Gói gồm

- Mã nguồn ứng dụng (`main.py`, `routers\`, `templates\`, `static\`...).
- `wheels\`: thư viện Python cho Windows 64-bit + Python 3.13. `wheels\drivers\`: driver CSDL (tùy chọn).
- `python-3.13.5-amd64.exe`: bộ cài Python.

## 1. Giải nén

Giải nén `dqcontrol_<ngày>.zip` vào thư mục của bạn, ví dụ `D:\dqcontrol` (nên đặt đường dẫn không dấu, không khoảng trắng).

## 2. Cài Python 3.13 (bỏ qua nếu lệnh `py -3.13 --version` đã chạy được)

Chạy `python-3.13.5-amd64.exe`:
- **Bỏ tích** *Use admin privileges when installing py.exe*.
- Tích *Add python.exe to PATH*.
- Bấm **Install Now**: Python cài vào thư mục của user, không cần quyền Administrator.

Mở cửa sổ Command Prompt **mới**, kiểm tra: `py -3.13 --version` → `Python 3.13.5`.

## 3. Cài thư viện

```
cd /d D:\dqcontrol
py -3.13 -m pip install --no-index --find-links wheels -r requirements.txt
```

Chỉ khi kết nối CSDL thật, cài thêm driver tương ứng (SQL Server: `pyodbc`, Oracle: `oracledb`, PostgreSQL: `psycopg2-binary`):

```
py -3.13 -m pip install --no-index --find-links wheels\drivers pyodbc
```

## 4. Tạo file cấu hình `.env`

```
copy .env.example .env
py -3.13 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Mở `.env` bằng Notepad, dán chuỗi vừa in ra vào sau `SECRET_KEY=`.

Mặc định `.env` ở **chế độ chạy thử** (tài khoản AD giả lập + dữ liệu giả lập), chạy được ngay.
Khi dùng thật, sửa: `MOCK_LDAP=false` + các biến `LDAP_*`, `USE_MOCK_DATA=false` + `DATABASE_URL`, `DB_FALLBACK_TO_MOCK=false`
(giải thích từng biến trong `.env` và `README.md`, mục *Kết nối CSDL thật*).

## 5. Chạy

```
cd /d D:\dqcontrol
py -3.13 -m uvicorn main:app --host 0.0.0.0 --port 8080
```

Mở trình duyệt: `http://localhost:8080`. Chế độ chạy thử đăng nhập bằng `admin` / `Admin@123`
(danh sách tài khoản thử hiện trên trang đăng nhập). Dừng: `Ctrl+C` hoặc đóng cửa sổ.

Ứng dụng chạy khi cửa sổ lệnh còn mở; tắt máy / đóng cửa sổ thì chạy lại lệnh ở bước 5.

## Lưu ý

- **Máy khác truy cập** `http://<IP-máy-này>:8080`: lần đầu chạy, Windows có thể hỏi cho phép qua firewall. Không có quyền
  Administrator thì có thể không mở được, khi đó chỉ dùng trên chính máy này (`http://localhost:8080`), hoặc nhờ IT mở cổng 8080.
- Cổng 8080 đã bị dùng: đổi `--port 8090` (hoặc số khác).
- Với CSDL thật, lần đầu đăng nhập bằng tài khoản quản trị → menu **Danh mục quy tắc** → upload danh mục mã quy tắc
  (danh mục trống thì người dùng chưa khai báo loại trừ được).
- Trình duyệt cần truy cập được `cdn.jsdelivr.net` (giao diện tải Bootstrap từ đây).
- **File bằng chứng** người dùng đính kèm (ảnh / PDF) được lưu trong thư mục `evidence\` cạnh ứng dụng (đổi bằng `EVIDENCE_DIR`
  trong `.env`). Thư mục này chứa dữ liệu thật: sao lưu định kỳ cùng CSDL / `dq_mock.db`.

## Cập nhật phiên bản mới

Dừng ứng dụng, giải nén gói mới đè lên thư mục cũ (**giữ lại** `.env`, `dq_mock.db` và thư mục `evidence\`), chạy lại bước 3 và bước 5.
