# Grid Crop Studio

`Grid Crop Studio` is a Windows desktop app for quickly cutting one image into many saved parts.
It is built for screenshot cleanup, repeated blog asset production, batch cropping, reusable layouts, and optional OCR workflows.

## What It Does

- Open a photo from disk or paste one with `Ctrl+V`
- Draw several crop areas on one screen
- Move, resize, delete, and confirm crop areas
- Auto-create evenly split grid areas
- Save crop layouts as JSON and load them again later
- Reuse one saved layout across many files in batch mode
- Retry only failed batch files
- Save crop, batch, and OCR job history into `.crop_history.jsonl`
- Browse saved work in the history viewer
- Optionally run a C++ OCR worker and import OCR model ZIP files

## Main Buttons

- `사진 열기`: choose a source image file
- `붙여넣기`: paste an image from the clipboard
- `저장`: save the current crop layout as JSON
- `불러오기`: load a saved crop layout
- `여러 장`: apply one layout to many images
- `다시`: rerun only failed batch items
- `기록`: open the history viewer
- `글자 읽기`: run the optional OCR flow
- `모델 넣기`: import a prepared OCR model ZIP
- `저장 폴더`: choose the export folder
- `현재 폴더`: set the current working folder as the export folder
- `화면 맞춤`: fit the source image to the canvas
- `지우기`: remove the selected crop area
- `전체 지우기`: clear every crop area
- `칸 나누기`: create an even grid of crop areas
- `확정`: lock the current crop areas for export
- `잘라서 저장`: export the selected crop results

## Desktop Workflow

1. Open or paste an image.
2. Choose an output folder.
3. Draw crop areas or create them with `칸 나누기`.
4. Press `확정`.
5. Press `잘라서 저장`.

For repeated work:

- save the layout with `저장`
- load it later with `불러오기`
- use `여러 장` for batch processing

## Run Locally

```bash
py -m pip install -r requirements.txt
py app.py
```

## Build The EXE

```bash
build_exe.bat
```

The build flow now:

- checks Python and pip
- bootstraps pip with `ensurepip` if required
- installs missing build dependencies automatically
- avoids the common mistake of launching the temporary `build\...` EXE
- falls back to a timestamped `dist_builds\...` folder if the main output is locked

Primary executable:

```text
dist\AutoCropSplitter\AutoCropSplitter.exe
```

Important:

- run the program from `dist\AutoCropSplitter\AutoCropSplitter.exe`
- do not run `build\AutoCropSplitter\AutoCropSplitter.exe`
- if you see a Python DLL load error from `build\...`, you launched the wrong file

## Optional OCR

The desktop UI can call an optional C++ OCR runner.

Build it with:

```bash
cmake -S cpp/ocr_engine -B cpp/ocr_engine/build -DUSE_TENSORRT=ON
cmake --build cpp/ocr_engine/build --config Release
```

Expected model location:

- `cpp/ocr_engine/models`
- required files: `detector.engine`, `recognizer.engine`

If you already have ONNX models and `trtexec`, you can build TensorRT engines with:

```bash
bash cpp/ocr_engine/scripts/build_trt_engines.sh detector.onnx recognizer.onnx cpp/ocr_engine/models
```

To prepare a portable OCR ZIP for the app:

```bash
bash cpp/ocr_engine/scripts/package_portable_model.sh /path/detector.engine /path/recognizer.engine ./portable_ocr_model.zip
```

## Repository Guide

- `app.py`: main desktop UI
- `build_exe.bat`: Windows build entry
- `AutoCropSplitter.spec`: PyInstaller packaging spec
- `WIKI.md`: quick product guide and workflow notes
- `FEATURE_TRADEOFF_MATRIX.md`: product tradeoff notes
- `PRODUCT_UPGRADE_PLAN.md`: roadmap notes
- `cpp/ocr_engine/`: optional C++ OCR worker
- `config/pages-seo.json`: GitHub Pages metadata
- `templates/index.template.html`: Pages template
- `scripts/generate_pages_assets.py`: regenerates `index.html`, `robots.txt`, `sitemap.xml`, and `site.webmanifest`

## GitHub Pages

This repository uses the root directory as the GitHub Pages source.

Public docs:

- site: `https://sheryloe.github.io/grid-crop-image/`
- README: `https://github.com/sheryloe/grid-crop-image/blob/main/README.md`
- wiki: `https://github.com/sheryloe/grid-crop-image/blob/main/WIKI.md`

Generated root files:

- `index.html`
- `robots.txt`
- `sitemap.xml`
- `site.webmanifest`
- `.nojekyll`

Regenerate them with:

```bash
py scripts/generate_pages_assets.py
```
