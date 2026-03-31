# grid-crop-image

`grid-crop-image` is a Windows desktop tool for repeated image crop workflows.
It supports manual multi-rectangle cropping, clipboard paste, saved JSON layouts, batch reuse, job history, and an optional C++ OCR runner path.

## Features

- Open a local image and define multiple crop rectangles in one session.
- Paste an image from the clipboard with `Ctrl+V`.
- Move, resize, delete, and save crop regions.
- Generate grid-based crop regions automatically.
- Export cropped files with collision-safe output names.
- Save and reload layouts as JSON.
- Apply one saved layout to many images in batch mode.
- Retry only failed batch items from the previous run.
- Record crop, batch, and OCR jobs in `.crop_history.jsonl`.
- Browse history with filters for date, job type, OCR text, confidence, and sort order.
- Optionally call a C++ OCR runner from the desktop UI.
- Import OCR model ZIP packages containing `detector.engine` and `recognizer.engine`.

## Tech Stack

- Python 3.11+
- Tkinter
- Pillow
- PyInstaller
- C++17 for the optional OCR runner
- CMake 3.20+ for the optional OCR runner build

## Run Locally

```bash
py -m pip install -r requirements.txt
py app.py
```

## Build The Windows EXE

```bash
build_exe.bat
```

The build script:

- checks that `python` is available
- bootstraps `pip` with `ensurepip` when needed
- installs missing build dependencies from `requirements-build.txt`
- falls back to `dist_builds\YYYYMMDD_HHMMSS\...` if the main output folder is locked by a running process

Primary output:

```text
dist\AutoCropSplitter\AutoCropSplitter.exe
```

Important:

- Run the app from `dist\AutoCropSplitter\AutoCropSplitter.exe`.
- Do not run `build\AutoCropSplitter\AutoCropSplitter.exe`.
- If you see `Failed to load Python DLL ...\build\...\python313.dll`, you are almost certainly launching the temporary build artifact instead of the packaged EXE in `dist`.

If you rebuild after dependency or packaging issues:

- remove old `dist\` and `build\` outputs first
- keep Pillow collection enabled in `AutoCropSplitter.spec`
- keep `--collect-all PIL --collect-submodules PIL` if you build manually with PyInstaller

## Batch Processing And History

- Batch mode can reuse a saved JSON layout across many source images.
- Failed items are tracked so the toolbar `Retry Failed` flow can rerun only the failed subset.
- Job history is appended to `.crop_history.jsonl`.
- History entries can include crop metadata, saved output paths, and OCR previews.

## Optional C++ OCR Runner

Build the OCR runner:

```bash
cmake -S cpp/ocr_engine -B cpp/ocr_engine/build -DUSE_TENSORRT=ON
cmake --build cpp/ocr_engine/build --config Release
```

The app looks for the OCR executable in:

- `bin/ocr_trt_runner(.exe)`
- `cpp/ocr_engine/build/ocr_trt_runner(.exe)`

Expected model directory:

- `cpp/ocr_engine/models`
- required files: `detector.engine`, `recognizer.engine`

If `trtexec` is already installed, you can build TensorRT engine files with:

```bash
bash cpp/ocr_engine/scripts/build_trt_engines.sh detector.onnx recognizer.onnx cpp/ocr_engine/models
```

You can package a portable model ZIP with:

```bash
bash cpp/ocr_engine/scripts/package_portable_model.sh /path/detector.engine /path/recognizer.engine ./portable_ocr_model.zip
```

Current status:

- `cpp/ocr_engine` is a TensorRT-ready scaffold, not a finished production OCR pipeline.
- Placeholder and integration scaffolding are present so the Python UI can hand work off to a native runner.
- Real deployment still needs model-specific preprocessing, postprocessing, engine loading, and runtime tuning.

## Repository Layout

- `app.py`: main Tkinter desktop application
- `build_exe.bat`: Windows build entry point
- `AutoCropSplitter.spec`: PyInstaller spec with Pillow collection hooks
- `FEATURE_TRADEOFF_MATRIX.md`: product tradeoff notes
- `PRODUCT_UPGRADE_PLAN.md`: roadmap and productization notes
- `cpp/ocr_engine/`: optional C++ OCR runner project
- `config/pages-seo.json`: GitHub Pages metadata source
- `templates/index.template.html`: Pages template
- `scripts/generate_pages_assets.py`: regenerates root Pages assets
- `scripts/update_github_repo_metadata.ps1`: repository metadata helper

## GitHub Pages

This repository uses the root directory as the GitHub Pages source.
Generated assets live at the repository root:

- `index.html`
- `robots.txt`
- `sitemap.xml`
- `site.webmanifest`
- `.nojekyll`

Regenerate them with:

```bash
py scripts/generate_pages_assets.py
```
