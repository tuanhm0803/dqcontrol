# CLAUDE.md

**Đọc [ARCHITECTURE.md](ARCHITECTURE.md) trước khi làm việc.** File đó mô tả đầy đủ kiến trúc, quy ước và các bẫy của dự án;
chỉ mở file code khi cần chi tiết cụ thể.

Quy tắc bắt buộc:
- Sau khi thay đổi kiến trúc, luồng nghiệp vụ, route, bảng / cột hoặc quy ước, **cập nhật ARCHITECTURE.md** (và README.md nếu ảnh hưởng người dùng).
- Luôn chạy bằng venv: `.\.venv\Scripts\python.exe`, `.\.venv\Scripts\uvicorn.exe` (lệnh `python` trên máy có thể là 3.12).
- Giao diện, thông báo lỗi, log, comment viết tiếng Việt có dấu; riêng `requirements.txt` chỉ dùng ASCII.
