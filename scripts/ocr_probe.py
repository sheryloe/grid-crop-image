"""내 PC Ollama로 그림 한 장의 글자를 읽어 보는 점검 도구.

사용법:
    py scripts/ocr_probe.py 그림.png [--model 모델이름] [--host http://127.0.0.1:11434]

앱의 '글자 읽기'와 같은 코드(gridcrop_core)를 쓰므로, 앱을 띄우지 않고
연결·모델·응답 시간을 확인할 때 쓴다. 그림은 지정한 Ollama 주소로만 보낸다.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gridcrop_core as core  # noqa: E402


SAMPLE_LINES = [
    "주간 작업 보고 2026-10-13",
    "완료: 4칸·9칸 자동 분할, 작업 기록 롤링",
    "남은 일: 실행 파일 빌드 확인",
    "Grid Crop Studio v2  /  OCR test 12345",
]


def make_sample(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("malgun.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    image = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(SAMPLE_LINES):
        draw.text((30, 30 + index * 62), line, fill="black", font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"시험 그림을 만들었습니다: {path}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Ollama 글자 읽기 점검")
    parser.add_argument("image", type=Path)
    parser.add_argument("--model", default="", help="비우면 그림 읽기 모델을 자동으로 고른다")
    parser.add_argument("--host", default=core.DEFAULT_OLLAMA_HOST)
    parser.add_argument("--timeout", type=int, default=core.OCR_TIMEOUT_SEC)
    parser.add_argument("--skip-check", action="store_true", help="모델 능력 확인 없이 바로 요청(오류 경로 점검용)")
    parser.add_argument("--make-sample", action="store_true", help="image 경로에 한글·영문 글자가 든 시험 그림을 새로 만든다")
    args = parser.parse_args()

    if args.make_sample:
        make_sample(args.image)
    try:
        image, _ = core.open_image_file(args.image)
    except Exception as exc:
        print(f"그림을 열지 못했습니다: {core.describe_error(exc)}")
        return 1
    print(f"그림: {args.image.name} ({image.width} x {image.height})")
    started = time.perf_counter()
    try:
        client = core.OllamaClient(args.host, timeout=args.timeout)
        models = client.list_models()
        print(f"설치된 모델: {', '.join(models) or '(없음)'}")
        model = args.model if args.skip_check else client.pick_vision_model(args.model)
        print(f"쓰는 모델: {model}")
        text = client.read_text(model, image)
    except core.OcrError as exc:
        print(f"실패 ({time.perf_counter() - started:.1f}초):\n{exc}")
        return 2
    print(f"걸린 시간: {time.perf_counter() - started:.1f}초")
    print("----- 읽은 글자 -----")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
