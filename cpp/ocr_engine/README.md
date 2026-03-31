# C++ OCR Engine (TensorRT-ready)

이 디렉터리는 Python UI와 연동되는 **C++ OCR 실행기**(`ocr_trt_runner`)를 제공합니다.

## 목표
- Python 앱은 크롭/워크플로우 UI 담당
- OCR 추론은 C++(TensorRT) 실행기로 분리해 경량/고성능 실행

## 빌드

```bash
cmake -S cpp/ocr_engine -B cpp/ocr_engine/build -DUSE_TENSORRT=ON
cmake --build cpp/ocr_engine/build --config Release
```

빌드 결과 예시:
- Windows: `cpp/ocr_engine/build/Release/ocr_trt_runner.exe`
- Linux/macOS: `cpp/ocr_engine/build/ocr_trt_runner`

## 실행

```bash
./ocr_trt_runner --input-dir ./samples --output-json ./ocr_result.json --model-dir ./models
```

개발 중 모델이 아직 없으면:

```bash
./ocr_trt_runner --input-dir ./samples --output-json ./ocr_result.json --model-dir ./models --allow-placeholder
```

## TensorRT 적용 포인트
- `src/ocr_pipeline.cpp` 의 `#ifdef USE_TENSORRT` 구간에
  - 엔진 로드
  - 실행 컨텍스트 생성
  - 전/후처리 및 디코딩
  코드를 채우면 됩니다.

실 모델 경로에서는 `models/detector.engine`, `models/recognizer.engine`를 사용하도록 되어 있습니다.
엔진 파일이 없고 `--allow-placeholder`를 주지 않으면 실행이 실패합니다.

## 휴대용 모델 ZIP 만들기

앱의 `모델 가져오기` 버튼으로 바로 넣을 수 있도록 ZIP 생성:

```bash
bash scripts/package_portable_model.sh /path/detector.engine /path/recognizer.engine ./portable_ocr_model.zip
```
