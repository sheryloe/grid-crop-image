"""다른 PC에 줄 배포본(zip)을 만든다.

    py scripts/make_release.py               # build_exe.bat로 빌드한 뒤 묶기
    py scripts/make_release.py --skip-build  # 이미 있는 dist\\AutoCropSplitter를 묶기만

결과: release\\AutoCropSplitter-<판>.zip
  AutoCropSplitter\\AutoCropSplitter.exe
  AutoCropSplitter\\_internal\\...
  AutoCropSplitter\\사용안내.txt   (scripts\\사용안내.txt에 판 번호를 넣은 것)

판 번호는 gridcrop_core.__version__ 한 곳에서 가져온다.
빌드할 때 임시 파일은 저장소 안 .scratch\\tmp에 쓰도록 TMP·TEMP를 바꿔 넘긴다.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gridcrop_core as core  # noqa: E402

APP_NAME = "AutoCropSplitter"
DIST_DIR = ROOT / "dist" / APP_NAME
RELEASE_DIR = ROOT / "release"
GUIDE_SOURCE = Path(__file__).resolve().parent / "사용안내.txt"
GUIDE_NAME = "사용안내.txt"
# 실행 중 생기는 파일은 배포본에 넣지 않는다(빌드 폴더에서 시험 삼아 실행했을 때 생긴 것)
SKIP_NAMES = {".crop_history.jsonl", ".grid_crop_ocr.json", ".gcs_write_probe"}


def run_build() -> None:
    scratch_tmp = ROOT / ".scratch" / "tmp"
    scratch_tmp.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TMP=str(scratch_tmp), TEMP=str(scratch_tmp))
    print("빌드합니다(build_exe.bat)...")
    result = subprocess.run(["cmd", "/c", str(ROOT / "build_exe.bat")], cwd=ROOT, env=env)
    if result.returncode != 0:
        raise SystemExit("빌드에 실패했습니다. 위 출력을 확인하세요.")


def guide_text(version: str) -> bytes:
    text = GUIDE_SOURCE.read_text(encoding="utf-8").replace("{version}", version)
    # 메모장에서 바로 읽히도록 BOM이 붙은 UTF-8, 줄 바꿈은 CRLF
    return ("﻿" + text.replace("\r\n", "\n").replace("\n", "\r\n")).encode("utf-8")


def make_zip(version: str, dist_dir: Path = DIST_DIR, release_dir: Path = RELEASE_DIR) -> Path:
    exe = dist_dir / f"{APP_NAME}.exe"
    if not exe.is_file():
        raise SystemExit(f"실행 파일이 없습니다: {exe}\n먼저 빌드하세요(--skip-build 없이 실행).")
    release_dir.mkdir(parents=True, exist_ok=True)
    target = release_dir / f"{APP_NAME}-{version}.zip"
    partial = target.with_name(target.name + ".part")
    count = 0
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(dist_dir.rglob("*")):
            if not path.is_file() or path.name in SKIP_NAMES:
                continue
            archive.write(path, f"{APP_NAME}/{path.relative_to(dist_dir).as_posix()}")
            count += 1
        archive.writestr(f"{APP_NAME}/{GUIDE_NAME}", guide_text(version))
    os.replace(partial, target)
    print(f"파일 {count + 1}개를 묶었습니다.")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="배포 zip 만들기")
    parser.add_argument("--skip-build", action="store_true", help="빌드는 건너뛰고 지금 dist 폴더를 묶는다")
    args = parser.parse_args(argv)
    version = core.__version__
    if not args.skip_build:
        run_build()
    target = make_zip(version)
    size_mb = target.stat().st_size / (1024 * 1024)
    print(f"배포본: {target} ({size_mb:.1f}MB, 판 {version})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
