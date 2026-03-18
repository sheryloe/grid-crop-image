# grid-crop-image

`grid-crop-image`는 반복적인 이미지 분할 및 저장 작업을 자동화하여 생산성을 높여주는 Windows용 이미지 유틸리티입니다.
단순한 스크린샷 분할을 넘어, 그리드 자동 생성과 강력한 배치 처리 기능으로 대량의 이미지도 효율적으로 관리할 수 있습니다.

- 저장소: `https://github.com/sheryloe/grid-crop-image`
- GitHub Pages: `https://sheryloe.github.io/grid-crop-image/`

## 서비스 개요

블로그 포스팅, 문서 작업, QA 기록 등에서 반복되는 이미지 분할 및 저장 과정을 혁신적으로 단축합니다. 복잡한 편집기 대신, "빠르고 강력한 분할 전문 도구"에 집중하여 사용자가 더 중요한 작업에 집중할 수 있도록 돕습니다.

## 핵심 기능

### 1. 빠른 이미지 입력
- **파일 열기**: 로컬 이미지 파일을 빠르게 불러옵니다.
- **클립보드 붙여넣기 (`Ctrl+V`)**: 화면 캡처 후, 별도의 저장 없이 클립보드에서 이미지를 바로 붙여넣어 작업을 시작할 수 있습니다.

### 2. 직관적인 분할 영역 편집
- **자유로운 생성 및 이동**: 마우스 드래그로 분할 영역을 만들고 자유롭게 이동할 수 있습니다.
- **정교한 크기 조절**: 각 영역의 모서리와 경계에 있는 핸들을 드래그하여 크기를 정교하게 조절할 수 있습니다.
- **비율 유지 및 정사각형 생성**: `Shift` 키를 누른 채 드래그하면 정사각형을 만들거나, 크기 조절 시 원래 비율을 유지할 수 있습니다.

### 3. 자동 분할 기능
- **그리드 생성**: 행(Rows), 열(Columns), 간격(Padding)을 지정하면 전체 이미지를 균일한 격자로 자동 분할합니다. AI로 생성된 콜라주 이미지 등을 한 번에 자를 때 매우 유용합니다.

### 4. 강력한 다중 파일 배치 처리
- **대량 작업 자동화**: 하나의 분할 규칙(현재 설정 또는 JSON 파일)을 여러 이미지 파일에 한 번에 적용하여 자동으로 분할 및 저장합니다.
- **체계적인 결과물 관리**: 처리 시 '하위 폴더 생성' 옵션을 선택하면, 각 원본 이미지의 이름으로 폴더가 생성되고 그 안에 결과물이 저장되어 파일 관리가 용이합니다.

### 5. 설정 저장 및 재사용
- **JSON으로 규칙 저장/불러오기**: 자주 사용하는 분할 영역 레이아웃을 JSON 파일로 저장하고 언제든지 다시 불러와 사용할 수 있습니다.
- **자동 크기 보정**: 설정 파일의 이미지 크기와 현재 작업 중인 이미지의 크기가 달라도, 비율에 맞춰 분할 영역 좌표를 자동으로 보정합니다.

## 주요 사용 사례: AI 이미지 분할 및 블로그 자산화

Midjourney, DALL-E 등 이미지 생성 AI로 만든 2x2, 3x3 콜라주 이미지를 `grid-crop-image`의 **그리드 생성** 및 **배치 처리** 기능으로 한 번에 분할하여 여러 개의 블로그용 이미지 자산으로 만들 수 있습니다. 이는 유료 이미지 API 호출 비용을 절감하고 콘텐츠 생산성을 극대화하는 효과적인 워크플로입니다.

## 기술 스택

- Python 3.11+
- Tkinter
- Pillow

## 실행 방법

```bash
py -m pip install -r requirements.txt
py app.py
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
