# Image production của DQ Dashboard (build bởi .github/workflows/deploy.yml)
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # SQLite dữ liệu giả lập và file bằng chứng nằm trong volume /data để giữ lại giữa các lần deploy
    MOCK_DATABASE_URL=sqlite:////data/dq_mock.db \
    EVIDENCE_DIR=/data/evidence

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Chạy bằng user thường, chỉ có quyền ghi vào /data
RUN useradd --system --uid 1000 --no-create-home dq \
    && mkdir -p /data && chown dq:dq /data
USER dq
VOLUME ["/data"]

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"

# 1 worker: SQLite + nạp dữ liệu giả lập lần đầu không an toàn khi nhiều tiến trình cùng chạy.
# --proxy-headers để lấy IP thật của người dùng từ edge-nginx (cổng 8080 chỉ mở trong edge-network).
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
