"""Đóng gói bản sạch để cài offline trên máy Windows công ty (chạy trên máy dev có Internet):

    py -3.13 deploy\\windows\\dong_goi.py
    py -3.13 deploy\\windows\\dong_goi.py --out D:\\release --no-python

Kết quả: <out>\\dqcontrol_<yyyyMMdd>\\ (mã nguồn + wheels + bộ cài Python + hướng dẫn) và file .zip cùng tên.
Chỉ copy đúng các file cần: không .git, .venv, .env, *.db, __pycache__, file deploy VPS.
"""
import argparse
import shutil
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
APP_DIRS = ("routers", "templates", "static")
APP_FILES = ("requirements.txt", ".env.example", "README.md")
DRIVERS = ("pyodbc", "oracledb", "psycopg2-binary")
# Wheels cho Windows 64-bit + CPython 3.13, tải được cả khi đóng gói trên máy khác
PIP_TARGET = ["--only-binary=:all:", "--platform", "win_amd64", "--python-version", "3.13", "--implementation", "cp"]


def pip_download(dest: Path, *args: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "download", "-q", "-d", str(dest), *PIP_TARGET, *args], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Đóng gói DQ Dashboard cho máy Windows không có Internet")
    parser.add_argument("--out", type=Path, default=REPO.parent / "dqcontrol_release")
    parser.add_argument("--python-version", default="3.13.5")
    parser.add_argument("--no-python", action="store_true", help="không kèm bộ cài Python")
    args = parser.parse_args()

    out = args.out / f"dqcontrol_{date.today():%Y%m%d}"
    cache = args.out / "_cache"
    print(f"Đóng gói {REPO} -> {out}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cache.mkdir(parents=True, exist_ok=True)

    # 1. Mã nguồn ứng dụng
    for f in REPO.glob("*.py"):
        shutil.copy2(f, out)
    for d in APP_DIRS:
        shutil.copytree(REPO / d, out / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in APP_FILES:
        shutil.copy2(REPO / f, out)

    # 2. Hướng dẫn deploy (đặt cạnh main.py)
    for f in HERE.glob("*.md"):
        shutil.copy2(f, out)

    # 3. Wheels
    print("Tải wheels...")
    pip_download(out / "wheels", "-r", str(REPO / "requirements.txt"))
    pip_download(out / "wheels" / "drivers", *DRIVERS)

    # 4. Bộ cài Python
    if not args.no_python:
        installer = f"python-{args.python_version}-amd64.exe"
        cached = cache / installer
        if not cached.exists():
            print(f"Tải {installer}...")
            urllib.request.urlretrieve(f"https://www.python.org/ftp/python/{args.python_version}/{installer}", cached)
        shutil.copy2(cached, out)

    # 5. Nén (xóa zip cũ trước: ghi đè trực tiếp đôi khi lỗi trên Windows khi file đang bị quét)
    out.with_suffix(".zip").unlink(missing_ok=True)
    zip_path = Path(shutil.make_archive(str(out), "zip", root_dir=out.parent, base_dir=out.name))
    n_wheels = len(list((out / "wheels").glob("*.whl")))
    print(f"Xong: {zip_path} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB, {n_wheels} wheels + "
          f"{len(list((out / 'wheels' / 'drivers').glob('*.whl')))} wheels driver)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
