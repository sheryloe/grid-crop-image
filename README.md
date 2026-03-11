# Grid Crop Image

`Grid Crop Image`는 한 장의 이미지를 여러 개의 사각형 영역으로 나눠 저장하는 Windows용 Tkinter 도구입니다.  
파일을 직접 열 수도 있고, 화면 캡처 후 클립보드 이미지를 바로 붙여넣어 분할할 수도 있습니다.

## 핵심 기능

- 이미지 파일 열기 지원
- `Ctrl + V` 클립보드 이미지 붙여넣기 지원
- 드래그로 여러 개의 크롭 박스 생성
- 기존 박스 이동, 삭제, 전체 초기화 지원
- 확대, 축소, 100%, 맞춤 보기 지원
- 저장 폴더 별도 선택 지원
- 박스 번호와 저장 파일 번호 1:1 유지
- 작업 레이아웃 JSON 저장 / 불러오기 지원
- PyInstaller 기반 단일 exe 빌드 지원

## 실행 환경

- Windows 10 이상 권장
- Python 3.11 이상
- `pip`

## 설치

### 1. 소스 받기

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

## exe 빌드

### 1. 빌드 의존성 설치

```powershell
python -m pip install -r requirements-build.txt
```

### 2. 빌드 실행

```powershell
build_exe.bat
```

빌드가 끝나면 아래 파일이 생성됩니다.

```text
dist\AutoCropSplitter.exe
```

직접 PyInstaller로 빌드해도 됩니다.

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoCropSplitter --collect-all PIL app.py
```

## 사용 방법

### 1. 이미지 불러오기

아래 두 방법 중 하나를 사용합니다.

- `이미지 열기`: 로컬 이미지 파일 선택
- `클립보드 붙여넣기` 또는 `Ctrl + V`: 캡처 이미지 바로 불러오기

지원 형식:

- `png`
- `jpg`
- `jpeg`
- `bmp`
- `gif`
- `webp`
- `tif`
- `tiff`

### 2. 배율 조정

정밀하게 영역을 잡아야 할 때는 확대해서 작업하면 됩니다.

- `확대`
- `축소`
- `100%`
- `맞춤`
- `Ctrl + 마우스 휠`

### 3. 크롭 박스 만들기

- 빈 영역에서 마우스를 드래그하면 새 박스가 생성됩니다.
- 박스는 원하는 만큼 계속 추가할 수 있습니다.
- 이미 만든 박스는 다시 드래그해서 위치를 옮길 수 있습니다.
- 선택한 박스는 `Delete` 키 또는 마우스 오른쪽 클릭으로 삭제할 수 있습니다.
- `전체 초기화`를 누르면 현재 박스를 모두 지웁니다.

### 4. 저장 폴더 선택

`폴더 선택` 버튼으로 결과 이미지를 저장할 위치를 지정합니다.

- 파일을 직접 연 경우: 원본 이미지 폴더가 기본값으로 설정됩니다.
- 클립보드 이미지를 붙여넣은 경우: 저장 전 폴더를 직접 선택해야 합니다.

### 5. 박스 확정

`설정` 버튼을 누르면 현재 박스 목록을 저장 대상으로 확정합니다.

- 이 단계가 끝나야 `분할 시작` 버튼이 활성화됩니다.
- 화면에 보이는 박스 번호 순서가 저장 파일 번호와 동일하게 유지됩니다.

### 6. 분할 저장

`분할 시작` 버튼을 누르면 확정된 모든 박스를 개별 파일로 저장합니다.

예시:

```text
test_rect_01.png
test_rect_02.png
test_rect_03.png
```

같은 이름의 파일이 이미 있으면 뒤에 번호를 붙여 충돌을 피합니다.

## 설정 저장 / 불러오기

현재 작업 상태를 JSON으로 저장할 수 있습니다.

저장되는 정보:

- 원본 이미지 경로
- 이미지 입력 방식
- 저장 폴더
- 원본 이미지 크기
- 현재 줌 배율
- 사각형 좌표 목록
- 설정 완료 상태

불러오기 동작:

- 원본 파일 경로가 살아 있으면 자동으로 다시 엽니다.
- 클립보드 이미지 기반 설정은 같은 크기의 이미지를 다시 붙여넣은 뒤 불러오는 것이 가장 안전합니다.
- 이미지 크기가 다르면 비율에 맞춰 좌표를 보정합니다.

## 주요 단축키

- `Ctrl + V`: 클립보드 이미지 붙여넣기
- `Ctrl + 마우스 휠`: 확대 / 축소
- `Shift + 마우스 휠`: 가로 스크롤
- `Delete`: 선택 박스 삭제
- `Esc`: 현재 드래그 취소

## 프로젝트 파일 구성

- `app.py`: 메인 GUI 프로그램
- `requirements.txt`: 실행 의존성
- `requirements-build.txt`: 빌드 의존성
- `build_exe.bat`: exe 빌드 스크립트
- `test.png`: 샘플 이미지

## 문제 해결

### Pillow 오류가 나는 경우

```powershell
python -m pip install -r requirements.txt
```

### `분할 시작` 버튼이 비활성화된 경우

다음 항목을 확인하세요.

- 박스를 하나 이상 만들어야 합니다.
- 박스를 수정한 뒤에는 `설정`을 다시 눌러야 합니다.
- 저장 폴더가 있어야 합니다.
- 클립보드 이미지를 붙여넣은 경우 저장 폴더를 직접 선택해야 합니다.

### exe 빌드가 실패하는 경우

```powershell
python -m pip install -r requirements-build.txt
build_exe.bat
```

실행 중인 `AutoCropSplitter.exe`가 있으면 종료한 뒤 다시 빌드해야 합니다.

## 검증

현재 코드 기준으로 아래 항목을 확인했습니다.

- `python -m py_compile app.py`
- Python 소스 실행 확인
- PyInstaller exe 빌드 확인
- 클립보드 붙여넣기 / 저장 폴더 / JSON 설정 흐름 반영
