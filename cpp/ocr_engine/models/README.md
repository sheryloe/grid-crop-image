# OCR 모델 배치 경로

`ocr_trt_runner`는 기본적으로 이 폴더에서 아래 파일을 찾습니다.

- `detector.engine`
- `recognizer.engine`

실제 TensorRT OCR을 사용하려면 엔진 파일을 생성해서 이 경로에 배치하세요.
개발 중 placeholder 결과를 허용하려면 `--allow-placeholder` 옵션을 사용합니다.
