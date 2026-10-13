# Grid Crop Studio

한 장의 사진을 여러 조각으로 빠르게 잘라 저장하는 윈도우 데스크톱 프로그램입니다.
화면 캡처 정리, 블로그 그림 반복 작업, AI로 한 장에 4칸·9칸으로 그린 그림 나누기, 여러 장 일괄 자르기, 캡처 속 글자 읽기에 씁니다.

## 할 수 있는 일

- 사진 열기, `Ctrl+V`로 캡처 붙여넣기(복사한 그림 파일도 됨), 실행 파일 위에 사진 끌어 놓기
- 한 화면에 자를 영역 여러 개 그리기 · 옮기기 · 크기 바꾸기 · 지우기 · 확정
- **AI 그림 빠르게 나누기**: 「4칸」「9칸」 한 번으로 2×2·3×3 영역을 만들고 확정, 저장 폴더가 있으면 바로 저장
  - 칸 사이 흰 여백이나 테두리가 있으면 찾아서 그 선을 기준으로 자르고, 못 찾으면 같은 간격으로 자릅니다
- 칸 나누기: 행·열·여백을 넣어 같은 간격 영역 만들기(여백 자동 찾기 선택 가능)
- 영역 배치를 JSON으로 저장하고 다시 불러오기(크기가 다른 사진에는 비율대로 맞춤)
- 여러 장: 파일·폴더로 사진을 모아 한 번에 자르기
  - 규칙: 지금 창의 확정 영역 / 저장한 배치 파일 / AI 그림 자동 나누기(4칸·9칸, 사진마다 여백 찾기)
  - 실패한 사진만 「다시」로 다시 돌리기
- **글자 읽기**: 내 PC의 Ollama 그림 읽기 모델로 영역(없으면 사진 전체)의 글자를 읽어 결과창에 보여 주고, 복사·텍스트 파일 저장
  - 그림은 내 PC(또는 사내망) Ollama 주소로만 보내고 외부 인터넷으로 보내지 않습니다
  - 고급 선택: 직접 빌드한 C++ 실행기(`cpp/ocr_engine`)
- **작업 기록**: 한 장·여러 장·글자 읽기 작업을 `.crop_history.jsonl`에 남기고 「기록」 창에서 날짜·종류·읽은 글자로 찾기
  - 5MB가 넘으면 `.crop_history.1.jsonl`… 로 넘겨 최근 3개까지 보관, 깨진 줄은 건너뜀, 최근 200건부터 읽고 「더 보기」
- 설치 없이 쓰는 실행 파일(`build_exe.bat`)

## 주요 버튼

| 버튼 | 하는 일 |
| --- | --- |
| 사진 열기 / 붙여넣기 | 사진 파일을 열거나 클립보드 그림을 가져옵니다 |
| 저장 / 불러오기 | 지금 영역 배치를 JSON으로 저장하거나 불러옵니다 |
| 여러 장 / 다시 | 여러 사진을 한 번에 자르고, 실패한 사진만 다시 돌립니다 |
| 기록 | 작업 기록 창을 엽니다 |
| 글자 읽기 / 읽기 설정 | 글자를 읽고, Ollama 주소·모델·기다리는 시간과 C++ 실행기 선택을 정합니다 |
| - / + / 100% / 화면 맞춤 | 확대·축소 |
| 지우기 / 전체 지우기 / 칸 나누기 / 확정 | 그림 위 영역을 다룹니다 |
| 4칸 / 9칸 | AI 그림을 2×2·3×3으로 바로 나눕니다 |
| 저장 폴더 / 현재 폴더 | 조각을 저장할 폴더를 정합니다 |
| 잘라서 저장 | 확정한 영역을 잘라 저장합니다(`이름_rect_01.png` …) |

## 쓰는 순서

1. 사진을 열거나 붙여넣습니다.
2. 저장 폴더를 정합니다(파일로 연 사진은 그 폴더가 기본).
3. 영역을 그리거나 「칸 나누기」「4칸」「9칸」을 누릅니다.
4. 「확정」 후 「잘라서 저장」을 누릅니다(「4칸」「9칸」은 확정까지 한 번에).

## 글자 읽기 준비(Ollama)

1. [Ollama](https://ollama.com)를 설치하고 켜 둡니다(기본 주소 `http://127.0.0.1:11434`).
2. 그림을 읽을 수 있는 모델을 받습니다. 예:

   ```bash
   ollama pull qwen2.5vl:7b
   ```

3. 「읽기 설정」 → 「모델 찾기」로 그림 읽기 모델을 고릅니다. 비워 두면 그림을 읽을 수 있는 모델을 자동으로 고릅니다.

모델 목록에서 그림 읽기 능력(`vision`)이 없는 모델은 고르지 않습니다. 글만 다루는 모델은 그림을 받아도 "이미지를 볼 수 없다"고만 답하기 때문입니다.
Ollama가 꺼져 있거나 모델이 없으면 무엇을 하면 되는지 한글로 안내합니다.

명령줄 점검: `py scripts/ocr_probe.py 그림.png [--model 모델] [--make-sample]`

## 실행

```bash
py -m pip install -r requirements.txt
py app.py [사진 경로] [--quick-grid 4칸|9칸]
```

## 시험

```bash
py -m unittest discover -s tests
```

칸 나누기·거터 찾기, 배치 파일 해석, 작업 기록 롤링·깨진 줄, Ollama 요청 조립·오류 안내(내 PC 시험 서버), 화면 연결부(창 숨김)를 확인합니다.

## 실행 파일 만들기

```bash
build_exe.bat
```

- 파이썬·pip 확인, 빠진 빌드 도구(`requirements-build.txt`) 자동 설치
- 결과: `dist\AutoCropSplitter\AutoCropSplitter.exe`
- 이전 결과가 실행 중이라 바꿀 수 없으면 `dist_builds\날짜_시각\` 에 만듭니다
- `build\` 아래 임시 실행 파일은 실행하지 마세요(파이썬 DLL 오류가 납니다)

작업 기록·글자 읽기 설정은 실행 파일(또는 `app.py`)이 있는 폴더에 저장하고, 그 폴더에 쓸 수 없으면 사용자 폴더의 `.grid_crop_studio`에 저장합니다.

## 다른 PC용 배포본

```bash
py scripts/make_release.py               # 빌드 후 묶기
py scripts/make_release.py --skip-build  # 지금 dist 폴더만 묶기
```

- 결과: `release\AutoCropSplitter-<판>.zip` (exe, `_internal`, `사용안내.txt`)
- 판 번호는 `gridcrop_core.__version__` 한 곳에 두고 창 제목에도 보입니다.
- 안내서 원본은 `scripts/사용안내.txt`(`{version}` 자리에 판 번호가 들어갑니다).

## C++ 실행기(고급, 선택)

```bash
cmake -S cpp/ocr_engine -B cpp/ocr_engine/build -DUSE_TENSORRT=ON
cmake --build cpp/ocr_engine/build --config Release
```

- 모델 위치: `cpp/ocr_engine/models` (`detector.engine`, `recognizer.engine`)
- 「읽기 설정」 → 「모델 넣기」로 ZIP에서 두 파일을 넣을 수 있습니다
- 지금 저장소의 C++ 실행기는 실제 인식 대신 자리표시 결과만 냅니다. 실제 글자 읽기는 Ollama 방식을 쓰세요.

## 저장소 구성

- `app.py`: 화면(Tkinter)
- `gridcrop_core.py`: 화면 없이 시험하는 핵심 처리(칸·거터, 배치 파일, 작업 기록, Ollama 요청)
- `tests/`: 단위 시험
- `scripts/ocr_probe.py`: 글자 읽기 점검 도구
- `scripts/make_grid_samples.py`, `scripts/measure_grid.py`: 4칸·9칸 여백 찾기 시험 그림 만들기·측정
- `scripts/make_release.py`, `scripts/사용안내.txt`: 배포 zip 만들기
- `build_exe.bat`, `AutoCropSplitter.spec`: 실행 파일 빌드
- `WIKI.md`: 사용 안내
- `cpp/ocr_engine/`: 선택형 C++ 실행기
- `config/pages-seo.json`, `templates/index.template.html`, `scripts/generate_pages_assets.py`: GitHub Pages

## GitHub Pages

- 사이트: `https://sheryloe.github.io/grid-crop-image/`
- README: `https://github.com/sheryloe/grid-crop-image/blob/main/README.md`
- 위키: `https://github.com/sheryloe/grid-crop-image/blob/main/WIKI.md`

`index.html`, `robots.txt`, `sitemap.xml`, `site.webmanifest`는 `py scripts/generate_pages_assets.py`로 다시 만듭니다.
