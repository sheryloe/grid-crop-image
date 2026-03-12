# grid-crop-image

Tkinter와 Pillow로 만든 Windows 이미지 크롭 도구로, 스크린샷 붙여넣기, 다중 영역 선택, JSON 레이아웃 재사용을 지원합니다.

- Repository: https://github.com/sheryloe/grid-crop-image
- Landing page: https://sheryloe.github.io/grid-crop-image/
- Audience: 스크린샷 작업이 많은 개발자, 블로거, 문서 작성자, QA 담당자

## Search Summary
Windows 이미지 크롭 및 분할 작업을 빠르게 처리하는 도구

## Problem This Repo Solves
스크린샷이나 UI 캡처를 여러 조각으로 반복 분할할 때, 범용 편집기는 속도가 느리고 동일한 레이아웃 재사용이 어렵습니다.

## Key Features
- 로컬 이미지 열기와 `Ctrl + V` 클립보드 붙여넣기
- 다중 크롭 영역 지정과 순차 내보내기
- JSON 설정 저장/불러오기로 반복 레이아웃 재사용
- PyInstaller 기반 Windows 단일 EXE 빌드 지원

## User Flow
- 이미지 열기 또는 클립보드 붙여넣기
- 여러 크롭 영역 지정
- 순차 저장 또는 레이아웃 JSON 재사용

## Tech Stack
- Python 3.11+
- Tkinter
- Pillow
- PyInstaller

## Quick Start
- `py -m pip install -r requirements.txt`로 의존성을 설치합니다.
- `py app.py`로 프로그램을 실행합니다.
- 배포용 EXE는 `build_exe.bat`로 생성합니다.

## Repository Structure
- `app.py`: 메인 GUI 엔트리
- `config/`, `templates/`: 설정 및 보조 자산
- `scripts/`, `notion/`: 운영 문서와 스크립트

## Search Keywords
`windows image crop tool`, `grid crop image`, `screenshot split tool`, `이미지 분할 프로그램`, `윈도우 크롭 도구`

## FAQ
### Grid Crop Image는 무엇에 적합한가요?
스크린샷 클립, 블로그용 이미지 분할, 반복 레이아웃 내보내기에 특히 적합합니다.

### Windows EXE로 빌드할 수 있나요?
가능합니다. PyInstaller 기반 `build_exe.bat`가 포함돼 있습니다.

### 왜 JSON 레이아웃이 중요한가요?
같은 위치를 반복 크롭하는 작업에서 시간을 크게 줄여주기 때문입니다.
