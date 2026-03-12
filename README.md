# Grid Crop Image - Windows 이미지 크롭 및 분할 도구

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)
![GUI](https://img.shields.io/badge/GUI-Tkinter-FFCC33)
![Imaging](https://img.shields.io/badge/Image-Pillow-4C8CBF)

`Grid Crop Image`는 스크린샷 자르기, 클립보드 이미지 붙여넣기, 다중 사각형 크롭, 순차 파일 저장 작업을 빠르게 처리할 수 있는 Windows 이미지 크롭 프로그램입니다. Tkinter와 Pillow로 만든 가벼운 데스크톱 앱으로, 한 장의 이미지를 여러 개의 직사각형 영역으로 나눠 저장하거나 같은 크롭 레이아웃을 JSON 설정 파일로 재사용할 수 있습니다.

`Grid Crop Image` is a Windows image crop and split tool for screenshot clipping, clipboard image paste, manual multi-region cropping, and sequential export. You can open a local image, paste an image with `Ctrl + V`, draw multiple crop boxes, save the layout as JSON, and export each selected area as a separate file.

실행 창 제목과 EXE 이름은 `Auto Crop Splitter`이며, 저장소 이름은 `grid-crop-image`입니다.

## Table of Contents

- [왜 Grid Crop Image가 필요한가](#왜-grid-crop-image가-필요한가)
- [핵심 기능](#핵심-기능)
- [이런 작업에 적합합니다](#이런-작업에-적합합니다)
- [빠른 시작](#빠른-시작)
- [사용 방법](#사용-방법)
- [지원 형식](#지원-형식)
- [JSON 설정 저장과 불러오기](#json-설정-저장과-불러오기)
- [단축키](#단축키)
- [Windows EXE 빌드](#windows-exe-빌드)
- [GitHub Pages 및 SEO 자동화](#github-pages-및-seo-자동화)
- [문제 해결](#문제-해결)
- [FAQ](#faq)
- [프로젝트 구조](#프로젝트-구조)
- [검증](#검증)
- [License](#license)

## 왜 Grid Crop Image가 필요한가

이미지 분할 작업은 단순해 보이지만 반복되면 시간이 많이 듭니다. 특히 아래 같은 상황에서는 일반 편집기보다 `Grid Crop Image` 같은 전용 도구가 훨씬 빠릅니다.

- 포토샵 같은 무거운 툴 없이 스크린샷을 여러 장으로 잘라 저장하고 싶을 때
- 캡처한 이미지를 클립보드에서 바로 붙여넣어 분할하고 싶을 때
- 웹툰 컷, 긴 세로 이미지, 문서 캡처 이미지를 구간별로 나누고 싶을 때
- 같은 크롭 좌표를 반복해서 재사용해야 할 때
- 결과 파일명을 순서대로 정리해 저장하고 싶을 때

검색 관점에서 보면 이 프로젝트는 아래 니즈에 맞는 도구입니다.

- Windows 이미지 크롭 프로그램
- 스크린샷 자르기 도구
- clipboard image crop tool
- multi-region image splitter
- JSON crop layout saver

## 핵심 기능

- `png`, `jpg`, `jpeg`, `bmp`, `gif`, `webp`, `tif`, `tiff` 이미지 열기
- `Ctrl + V` 클립보드 이미지 붙여넣기
- 클립보드에 복사된 파일 목록에서 첫 번째 지원 이미지 자동 감지
- 여러 개의 크롭 사각형 생성, 이동, 삭제, 전체 초기화
- `확대`, `축소`, `100%`, `맞춤` 보기 지원
- `Ctrl + 마우스휠` 확대/축소, `Shift + 마우스휠` 가로 스크롤
- 작업 상태를 JSON 설정 파일로 저장 및 불러오기
- 이미지 크기가 달라졌을 때 좌표 비율 자동 보정
- 저장 폴더 직접 선택
- 확정된 사각형 순서대로 파일 저장
- 중복 파일명 충돌 자동 방지
- PyInstaller 기반 Windows EXE 빌드 지원

## 이런 작업에 적합합니다

`Grid Crop Image`는 아래 같은 사용자에게 특히 잘 맞습니다.

- 블로그용 스크린샷을 여러 장으로 나눠 업로드하는 사용자
- 긴 이미지나 세로 이미지를 구간별로 저장해야 하는 사용자
- 반복적인 이미지 분할 작업을 자동화하고 싶은 사용자
- 클립보드 이미지를 바로 붙여넣어 작업하고 싶은 사용자
- Python으로 실행하거나 EXE로 배포 가능한 가벼운 이미지 유틸리티를 찾는 사용자

## 빠른 시작

### 1. 저장소 클론

```powershell
git clone https://github.com/sheryloe/grid-crop-image.git
cd grid-crop-image
```

### 2. 실행 의존성 설치

```powershell
python -m pip install -r requirements.txt
```

### 3. 앱 실행

```powershell
python app.py
```

## 실행 환경

- Windows 10 이상 권장
- Python 3.11 이상
- `pip`

## 사용 방법

### 1. 이미지 불러오기

다음 중 하나를 사용하면 됩니다.

- `이미지 열기` 버튼으로 로컬 이미지 선택
- `Ctrl + V`로 클립보드 이미지 붙여넣기

클립보드 동작 방식:

- 클립보드에 실제 이미지 데이터가 있으면 바로 로드합니다.
- 클립보드에 파일이 복사돼 있으면 지원 형식 중 첫 번째 이미지를 엽니다.
- 클립보드에서 불러온 이미지는 원본 파일 경로가 없기 때문에 저장 전에 출력 폴더를 직접 지정하는 것이 안전합니다.

### 2. 저장 폴더 선택

- 파일에서 연 이미지는 기본적으로 원본 폴더를 저장 위치로 사용합니다.
- 클립보드에서 불러온 이미지는 `폴더 선택`으로 저장 위치를 직접 지정하는 것을 권장합니다.

### 3. 화면 보기 조정

다음 기능을 지원합니다.

- `확대`
- `축소`
- `100%`
- `맞춤`
- `Ctrl + 마우스휠` 확대/축소
- `Shift + 마우스휠` 가로 스크롤

### 4. 크롭 영역 만들기와 수정

- 빈 영역에서 드래그하면 새 사각형이 생성됩니다.
- 기존 사각형을 드래그하면 위치를 이동할 수 있습니다.
- `Delete` 키 또는 마우스 오른쪽 버튼으로 선택한 사각형을 삭제할 수 있습니다.
- `전체 초기화`를 누르면 모든 사각형이 제거됩니다.
- 새 사각형을 만드는 중 `Esc`를 누르면 현재 드래그를 취소합니다.

### 5. 저장 순서 확정

사각형 배치를 마친 뒤 `설정` 버튼을 누르세요.

- 확정된 사각형 목록 순서가 결과 파일 순서가 됩니다.
- 이미지, 사각형, 저장 폴더가 모두 준비되고 `설정`까지 눌러야 `분할 시작` 버튼이 활성화됩니다.

### 6. 분할 이미지 저장

`분할 시작`을 누르면 확정된 사각형마다 개별 이미지 파일이 생성됩니다.

저장 파일명 예시:

```text
sample_rect_01.png
sample_rect_02.png
sample_rect_03.png
```

저장 규칙:

- 파일에서 불러온 이미지는 가능하면 원본 확장자를 유지합니다.
- 클립보드에서 온 이미지는 원본 확장자가 없으므로 기본적으로 `.png`로 저장됩니다.
- 같은 이름의 파일이 이미 있으면 `_1`, `_2` 같은 접미사를 붙여 덮어쓰기를 피합니다.

## 지원 형식

입력 지원 형식:

- `png`
- `jpg`
- `jpeg`
- `bmp`
- `gif`
- `webp`
- `tif`
- `tiff`

출력 규칙:

- 원본 파일 기반 입력이면 가능하면 원본 확장자를 유지합니다.
- 클립보드 기반 입력이면 기본 출력은 `.png`입니다.

## JSON 설정 저장과 불러오기

현재 작업 상태를 JSON 파일로 저장할 수 있습니다.

저장되는 정보:

- 원본 이미지 경로
- 원본 이미지 입력 방식 (`file` 또는 `clipboard`)
- 저장 폴더
- 원본 이미지 크기
- 현재 줌 배율
- 설정 확정 여부
- 크롭 사각형 좌표 목록

불러오기 동작:

- 저장된 원본 이미지 경로가 아직 존재하면 자동으로 다시 엽니다.
- 클립보드 기반 설정인데 원본 이미지가 없으면 먼저 이미지를 다시 붙여넣거나 직접 열어야 합니다.
- 저장 당시 이미지 크기와 현재 이미지 크기가 다르면 좌표를 비율에 맞게 자동 보정합니다.

기본 설정 파일명:

```text
<source_name>_crop_config.json
```

## 단축키

- `Ctrl + V`: 클립보드 이미지 붙여넣기
- `Ctrl + 마우스휠`: 확대/축소
- `Shift + 마우스휠`: 가로 스크롤
- `Delete`: 선택한 사각형 삭제
- `Esc`: 현재 생성 중인 사각형 취소

## Windows EXE 빌드

### 1. 빌드 의존성 설치

```powershell
python -m pip install -r requirements-build.txt
```

### 2. 빌드 실행

```powershell
build_exe.bat
```

빌드 결과물:

```text
dist\AutoCropSplitter.exe
```

직접 PyInstaller로 빌드할 수도 있습니다.

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoCropSplitter --collect-all PIL app.py
```

## GitHub Pages 및 SEO 자동화

이 저장소는 GitHub Pages와 Search Console 세팅도 명령어 기반으로 다시 만들 수 있도록 정리돼 있습니다.

핵심 구조:

- `config/pages-seo.json`: 사이트 제목, 설명, 키워드, repo 메타데이터, 검증 파일 정보
- `templates/index.template.html`: Pages 랜딩 페이지 템플릿
- `scripts/generate_pages_assets.py`: `index.html`, `robots.txt`, `sitemap.xml`, `site.webmanifest`, `.nojekyll` 생성
- `scripts/update_github_repo_metadata.ps1`: GitHub repo description, homepage, topics, Pages source 갱신
- `scripts/request_search_console_verification.ps1`: Search Console HTML 파일 검증 토큰 요청 및 파일 생성
- `scripts/submit_search_console.ps1`: Search Console 속성 추가 및 sitemap 제출

대표 명령:

```powershell
python scripts/generate_pages_assets.py
powershell -ExecutionPolicy Bypass -File scripts\update_github_repo_metadata.ps1
powershell -ExecutionPolicy Bypass -File scripts\request_search_console_verification.ps1
powershell -ExecutionPolicy Bypass -File scripts\submit_search_console.ps1
```

자세한 설정 흐름은 `GITHUB_PAGES_SEARCH_CONSOLE_SETUP.md`에 정리돼 있습니다.

## 문제 해결

### 클립보드 붙여넣기가 동작하지 않을 때

다음을 확인하세요.

- `python -m pip install -r requirements.txt`로 Pillow가 정상 설치됐는지
- 클립보드에 실제 이미지 또는 지원 형식 이미지 파일이 들어 있는지
- Pillow의 클립보드 기능을 사용할 수 있는 Windows 환경인지

### `분할 시작` 버튼이 비활성화될 때

다음 조건이 모두 만족돼야 합니다.

- 이미지가 열려 있음
- 사각형이 하나 이상 있음
- 최근 편집 이후 `설정` 버튼을 다시 눌렀음
- 유효한 저장 폴더가 선택돼 있음

### 설정 불러오기가 실패할 때

가능한 원인:

- 저장된 원본 이미지 경로가 더 이상 존재하지 않음
- 클립보드 기반 설정을 불러오기 전에 원본 이미지를 다시 붙여넣지 않음
- JSON 파일이 손상됐거나 UTF-8 형식이 아님

### EXE 빌드가 실패할 때

다음 순서로 다시 확인하세요.

```powershell
python -m pip install -r requirements-build.txt
build_exe.bat
```

`dist\AutoCropSplitter.exe`가 실행 중이면 종료한 뒤 다시 빌드해야 합니다.

## FAQ

### Grid Crop Image는 어떤 작업에서 가장 효율적인가요

스크린샷 자르기, 긴 이미지 분할, 다중 영역 크롭, 반복 크롭 레이아웃 저장 같은 작업에서 가장 효율적입니다.

### 클립보드 이미지 붙여넣기가 왜 중요한가요

캡처 후 파일 저장 없이 바로 작업을 이어갈 수 있기 때문입니다. 반복 작업에서는 이 한 단계 차이가 체감상 꽤 큽니다.

### JSON 설정 저장은 어떤 상황에서 유용한가요

비슷한 레이아웃의 이미지를 반복해서 잘라야 할 때 유용합니다. 한 번 잡아둔 좌표를 다시 불러와 재사용할 수 있기 때문입니다.

### Grid Crop Image는 어떤 기술로 만들어졌나요

Tkinter 기반 GUI와 Pillow 이미지 처리 라이브러리를 사용했습니다. Windows에서 가볍게 실행되는 Python 이미지 유틸리티라는 점이 특징입니다.

## 프로젝트 구조

- `app.py`: 메인 Tkinter GUI 애플리케이션
- `requirements/`: 실행 및 빌드 의존성 실제 정의 파일
- `requirements.txt`: 실행 의존성 설치용 호환 엔트리 파일
- `requirements-build.txt`: 빌드 의존성 설치용 호환 엔트리 파일
- `build_exe.bat`: PyInstaller 기반 EXE 빌드 스크립트
- `AutoCropSplitter.spec`: PyInstaller 스펙 파일
- `config/pages-seo.json`: GitHub Pages 및 SEO 설정값
- `templates/index.template.html`: GitHub Pages 랜딩 페이지 템플릿
- `scripts/`: Pages 생성, GitHub 메타데이터, Search Console 자동화 스크립트
- `index.html`, `robots.txt`, `sitemap.xml`, `site.webmanifest`: GitHub Pages 공개 파일
- `test.png`: 저장소에 포함된 샘플 이미지
- `notion/cropimage/`: 티스토리/노션용 글 초안

## 검증

현재 코드 기준 기본 검증 명령:

```powershell
python -m py_compile app.py
```

## License

현재 저장소에는 별도의 라이선스 파일이 포함돼 있지 않습니다. 외부 배포나 수정본 공개가 필요하다면 먼저 명시적인 라이선스를 추가하는 것이 좋습니다.
