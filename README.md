# 그리드 크롭 이미지 고도화 프로젝트 (grid-crop-image)

`grid-crop-image`는 단일 이미지/다중 이미지에서 반복 크롭 작업을 빠르게 처리하기 위한 Windows 중심 데스크톱 도구입니다.  
기본 크롭/배치 기능에 더해, 작업 이력 추적(JSONL)과 C++ OCR 연동 경로(TensorRT-ready)까지 포함한 구조로 확장되어 있습니다.

---

## 1. 주요 기능

### 이미지 크롭 워크플로우
- 로컬 이미지 열기
- `Ctrl+V` 클립보드 이미지 붙여넣기
- 다중 사각형 지정(이동/리사이즈/삭제)
- 그리드 자동 생성
- 단일 이미지 분할 저장
- 저장된 레이아웃(JSON) 저장/불러오기

### 배치 처리
- 저장된 레이아웃을 여러 이미지에 반복 적용
- 옵션에 따라 출력 하위 폴더 생성
- 대량 이미지 자동 분할
- 실패 파일만 모아서 `실패 재시도`로 재실행

### 이력 관리 (JSONL + 뷰어)
- `.crop_history.jsonl` 파일에 split/batch/ocr 작업 이력 누적
- 이력 뷰어에서 탭 전환 방식으로 상세 조회
  - `이력 목록` 탭
  - `OCR 결과` 탭
  - `상세 JSON` 탭
- 필터/탐색 기능
  - 시작일/종료일
  - 작업유형(single/batch/ocr)
  - OCR 텍스트 검색
  - 정렬(최신순/오래된순/저장개수순)
  - 빠른 기간(오늘/7일/30일)
  - OCR confidence 임계값 슬라이더

### OCR 연동 (선택 기능)
- UI 버튼 `OCR (C++/TRT)`로 외부 C++ 실행기 호출
- `모델 가져오기`로 ZIP에서 엔진 파일(`detector.engine`, `recognizer.engine`) 적용
- OCR 결과를 UI 미리보기 + 이력(details.ocr)로 저장

---

## 2. 기술 스택

- Python 3.11+
- Tkinter (Desktop UI)
- Pillow (이미지 처리)
- PyInstaller (Windows EXE 패키징)
- C++17 (선택 OCR 실행기)
- CMake 3.20+ (선택 OCR 실행기 빌드)

---

## 3. 로컬 실행

```bash
py -m pip install -r requirements.txt
py app.py
```

---

## 4. EXE 빌드

```bash
build_exe.bat
```

`build_exe.bat` 동작:
- `python`, `pip` 가용성 확인
- 필요 시 `ensurepip`로 pip 부트스트랩
- 누락된 빌드 의존성 자동 설치
- 빌드 폴더 잠금 시 `dist_builds\YYYYMMDD_HHMMSS\...`로 폴백

기본 산출물:
```text
dist\AutoCropSplitter\AutoCropSplitter.exe
```

주의:
- `build\AutoCropSplitter\...` 경로의 EXE는 PyInstaller 작업 산출물(임시)입니다.
- **실행은 반드시 `dist\AutoCropSplitter\AutoCropSplitter.exe`에서** 하세요.
- `Failed to load Python DLL ...\build\...\python313.dll` 오류는 보통 build 폴더 EXE를 실행했을 때 발생합니다.

문제 해결(실행 시 `library/module not found`):
- 최신 코드 기준 `AutoCropSplitter.spec`는 Pillow 하위 모듈/동적 라이브러리를 명시 수집합니다.
- 빌드 전 기존 산출물(`dist/`, `build/`)을 삭제 후 재빌드 권장.
- 명령행에서 직접 빌드 시에도 `--collect-all PIL --collect-submodules PIL` 옵션을 유지하세요.

---

## 5. C++ OCR Runner 빌드/연동 (선택)

### 5.1 빌드
```bash
cmake -S cpp/ocr_engine -B cpp/ocr_engine/build -DUSE_TENSORRT=ON
cmake --build cpp/ocr_engine/build --config Release
```

앱에서 OCR 실행기 탐색 경로:
- `bin/ocr_trt_runner(.exe)`
- `cpp/ocr_engine/build/ocr_trt_runner(.exe)`

모델 기본 경로:
- `cpp/ocr_engine/models`
- 필수 파일: `detector.engine`, `recognizer.engine`

### 5.2 모델 엔진 생성 (ONNX -> TensorRT)
`trtexec`가 설치되어 있다면:
```bash
bash cpp/ocr_engine/scripts/build_trt_engines.sh detector.onnx recognizer.onnx cpp/ocr_engine/models
```

### 5.3 휴대용 모델 ZIP 가져오기
1. 앱 실행
2. 툴바 `모델 가져오기` 클릭
3. ZIP 선택 (`detector.engine`, `recognizer.engine` 포함)

---

## 6. 이력 파일 포맷 개요

이력은 JSON Lines 형식(`.crop_history.jsonl`)으로 저장됩니다. 항목 예시:

- 공통 필드
  - `timestamp`, `job_type`, `source_images`, `output_dir`
  - `saved_paths`, `saved_count`, `rectangles_count`
- OCR 작업 추가 필드
  - `details.ocr.result_file`
  - `details.ocr.items_count`
  - `details.ocr.items_preview[]` (`file`, `text`, `confidence`)

---

## 7. 현재 상태/주의사항

- C++ OCR 모듈은 TensorRT 통합 지점을 포함한 **scaffold**입니다.
- 환경/모델 준비 상태에 따라 placeholder/개발 모드 동작이 섞일 수 있습니다.
- 실제 운영용 정확도/속도 최적화는 모델 전처리/후처리와 엔진 튜닝이 추가로 필요합니다.

---

## 8. 저장소 구조

- `app.py`: 메인 Tkinter 앱
- `build_exe.bat`: Windows 빌드 엔트리
- `AutoCropSplitter.spec`: PyInstaller 스펙
- `PRODUCT_UPGRADE_PLAN.md`: 제품 고도화/로드맵 문서
- `cpp/ocr_engine/`: C++ OCR 실행기 프로젝트
  - `CMakeLists.txt`
  - `include/ocr_pipeline.hpp`
  - `src/main.cpp`, `src/ocr_pipeline.cpp`
  - `models/MODEL_MANIFEST.json`
  - `scripts/build_trt_engines.sh`
  - `scripts/package_portable_model.sh`
- `scripts/generate_pages_assets.py`: GitHub Pages 산출물 재생성
- `templates/index.template.html`: Pages 템플릿

---

## 9. GitHub Pages

루트 디렉터리를 GitHub Pages 소스로 사용합니다. 생성 파일:
- `index.html`
- `robots.txt`
- `sitemap.xml`
- `site.webmanifest`
- `.nojekyll`

재생성:
```bash
py scripts/generate_pages_assets.py
```
