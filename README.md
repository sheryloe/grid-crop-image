# Grid Crop Image

`Grid Crop Image`는 한 장의 큰 이미지 위에서 여러 개의 크롭 영역을 직접 드래그로 지정하고, 잘라낸 결과물을 자동으로 저장할 수 있는 Windows용 데스크톱 도구입니다.

현재 프로그램은 아래 흐름에 맞춰 설계되어 있습니다.

1. 이미지 열기
2. 필요하면 확대 또는 축소
3. 드래그로 여러 개의 사각형 영역 지정
4. `설정` 버튼으로 현재 영역 확정
5. `분할 시작` 버튼으로 일괄 저장
6. 원본 이미지와 같은 폴더에 결과 파일 자동 저장

## 주요 기능

- 드래그 기반 크롭 영역 선택
- 사각형 영역 개수 제한 없이 추가 가능
- 확대, 축소, `100%`, `맞춤` 배율 지원
- `Ctrl + 마우스 휠` 확대/축소 단축키 지원
- 기존 사각형을 드래그해서 위치 이동 가능
- `Delete` 키 또는 마우스 오른쪽 클릭으로 선택 영역 삭제
- 현재 크롭 레이아웃을 `JSON`으로 저장
- 저장한 크롭 레이아웃 다시 불러오기
- 원본 이미지와 같은 폴더에 자동 저장
- `PyInstaller` 기반 Windows `.exe` 빌드 지원

## 프로그램 UI

현재 프로그램 버튼은 한글로 표시됩니다.

주요 버튼:

- `이미지 열기`
- `설정 저장`
- `설정 불러오기`
- `확대`
- `축소`
- `100%`
- `맞춤`
- `선택 삭제`
- `전체 초기화`
- `설정`
- `분할 시작`

## 실행 환경

- Windows 10 이상 권장
- Python 3.11 이상
- `pip`

## 설치 방법

```powershell
git clone https://github.com/sheryloe/grid-crop-image.git
cd grid-crop-image
python -m pip install -r requirements.txt
```

## 소스 코드 실행

```powershell
python app.py
```

## 사용 방법

### 1. 이미지 열기

상단의 `이미지 열기` 버튼을 눌러 로컬 이미지를 선택합니다.

지원 형식:

- `png`
- `jpg`
- `jpeg`
- `bmp`
- `gif`
- `webp`
- `tif`
- `tiff`

### 2. 필요한 배율로 조정

세부 영역을 정확하게 잡아야 할 때는 확대해서 작업하는 것이 편합니다.

- `확대` 버튼으로 확대
- `축소` 버튼으로 축소
- `100%` 버튼으로 원본 배율 복귀
- `맞춤` 버튼으로 캔버스에 맞게 보기
- `Ctrl + 마우스 휠`로 빠른 줌 조절

### 3. 크롭 영역 만들기

- 빈 공간에서 마우스를 드래그하면 새 사각형이 생성됩니다.
- 원하는 만큼 반복해서 여러 영역을 지정할 수 있습니다.
- 이미 만든 사각형은 다시 드래그해서 위치를 옮길 수 있습니다.

### 4. 영역 확정

사각형 배치를 끝낸 뒤 `설정` 버튼을 누릅니다.

이 단계에서 좌표가 정리되고 `분할 시작` 버튼이 활성화됩니다.

### 5. 일괄 저장

`분할 시작` 버튼을 누르면 현재 지정한 모든 영역이 잘려서 저장됩니다.

결과 파일은 원본 이미지와 같은 폴더에 자동으로 생성됩니다.

## 출력 파일명

예시:

```text
test_rect_01.png
test_rect_02.png
test_rect_03.png
```

같은 이름의 파일이 이미 존재하면 뒤에 번호를 붙여 충돌을 피합니다.

## 설정 저장 / 불러오기

현재 작업 중인 크롭 레이아웃을 `JSON` 파일로 저장할 수 있습니다.

저장되는 정보:

- 원본 이미지 경로
- 원본 이미지 크기
- 현재 줌 배율
- 사각형 좌표 목록
- 설정 완료 상태

사용 흐름:

1. 이미지 열기
2. 크롭 영역 지정
3. `설정 저장` 클릭
4. 생성된 `json` 파일 저장
5. 이후 `설정 불러오기` 클릭
6. 이전 작업 상태 복원

원본 이미지 경로가 그대로 존재하면 설정을 불러오는 동안 자동으로 함께 열립니다.

## Windows exe 빌드 방법

빌드용 의존성 설치:

```powershell
python -m pip install -r requirements-build.txt
```

빌드 실행:

```powershell
build_exe.bat
```

빌드 결과:

```text
dist\AutoCropSplitter.exe
```

직접 PyInstaller 명령으로 실행해도 됩니다.

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoCropSplitter --collect-all PIL app.py
```

## 프로젝트 파일 구성

- `app.py`: 메인 GUI 프로그램
- `requirements.txt`: 실행용 의존성
- `requirements-build.txt`: 빌드용 의존성
- `build_exe.bat`: exe 빌드 스크립트
- `test.png`: 샘플 이미지

## 문제 해결

### 실행 시 Pillow 오류가 나는 경우

```powershell
python -m pip install -r requirements.txt
```

### `분할 시작` 버튼이 비활성화된 경우

사각형을 추가하거나 이동한 뒤 반드시 `설정` 버튼을 한 번 눌러야 합니다.

### exe 빌드가 실패하는 경우

```powershell
python -m pip install -r requirements-build.txt
build_exe.bat
```

## 검증

이 프로젝트는 아래 항목까지 확인했습니다.

- `python -m py_compile app.py`
- 사각형 크롭 저장 테스트
- 설정 저장 / 불러오기 테스트
- 줌 동작 테스트
- `PyInstaller` 기반 Windows `.exe` 빌드 테스트
