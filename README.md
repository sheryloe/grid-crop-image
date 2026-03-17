# grid-crop-image

`grid-crop-image`는 스크린샷을 빠르게 분할하고 크롭하기 위한 Windows용 이미지 작업 도구입니다.
클립보드 붙여넣기, 다중 선택, JSON 레이아웃 재사용을 중심으로 설계했습니다.

- 저장소: `https://github.com/sheryloe/grid-crop-image`
- GitHub Pages: `https://sheryloe.github.io/grid-crop-image/`

## 서비스 개요

- 블로그 작성, QA 기록, 문서 캡처 작업에서 반복되는 이미지 분할 과정을 줄여줍니다.
- 복잡한 편집기보다 “빠른 자르기 도구”에 집중합니다.

## 핵심 기능

- 로컬 이미지 열기와 `Ctrl + V` 클립보드 붙여넣기
- 여러 영역을 동시에 선택해 크롭
- JSON 레이아웃으로 반복 작업 재사용
- PyInstaller 기반 Windows EXE 빌드 지원

## 기술 스택

- Python 3.11+
- Tkinter
- Pillow
- PyInstaller

## 실행 방법

```bash
py -m pip install -r requirements.txt
py app.py
```

EXE 빌드는 아래 배치 파일을 사용합니다.

```bash
build_exe.bat
```

## 디렉터리

- `app.py`: 메인 GUI 엔트리
- `config/`, `templates/`: 설정과 보조 자산
- `scripts/`, `notion/`: 운영 문서 및 스크립트

## 다음 단계

- 크롭 프리셋 저장
- 다중 파일 배치 처리
- Undo/Redo와 세션 자동 저장
- OCR 보조 기능 검토
## Clone And Run

- No `.env` file is required for the current desktop utility build.
- Build and run the app with the local toolchain documented in this repository.

## Current TODO

- Batch processing.
- Undo and redo.
- OCR-assisted review output.

## Blog Image Prompt Workflow

- Generate one multi-panel image from an image API prompt, then split it into several blog assets with `grid-crop-image`.
- This is useful for traffic-focused blog production because one paid image response can be reused as multiple thumbnail or inline images.
- In practice, a 2x2 or 3x3 prompt result can be cut into separate post images to reduce image API cost.
