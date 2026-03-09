# Grid Crop Image

`Grid Crop Image` is a Windows desktop tool for splitting one large image into multiple smaller images by drawing crop rectangles directly on top of the image.

The current app is focused on the workflow below:

1. Open an image
2. Zoom in or out if needed
3. Drag multiple crop rectangles
4. Click `Apply`
5. Click `Export`
6. Save all cropped files automatically next to the original image

## Features

- Drag-based crop selection
- Unlimited crop rectangles
- Zoom in, zoom out, reset to `100%`, and fit-to-view
- `Ctrl + Mouse Wheel` zoom shortcut
- Move existing rectangles by dragging
- Delete rectangles with `Delete` key or right click
- Save crop layouts as `JSON`
- Load saved crop layouts later
- Export all crop results to the same folder as the source image
- Build a standalone Windows `.exe` with PyInstaller

## UI Language

The current application UI is labeled in Korean, but the workflow is straightforward:

- open image
- save layout
- load layout
- zoom in
- zoom out
- fit to canvas
- clear all rectangles
- apply crop layout
- export cropped images

## Requirements

- Windows 10 or later
- Python 3.11 or later
- `pip`

## Installation

```powershell
git clone https://github.com/sheryloe/grid-crop-image.git
cd grid-crop-image
python -m pip install -r requirements.txt
```

## Run From Source

```powershell
python app.py
```

## How To Use

### 1. Open an image

Click the open-image button and choose a local file.

Supported formats:

- `png`
- `jpg`
- `jpeg`
- `bmp`
- `gif`
- `webp`
- `tif`
- `tiff`

### 2. Zoom if needed

You can inspect detailed regions before selecting crop areas.

- Click zoom in
- Click zoom out
- Click `100%`
- Click fit-to-view
- Or use `Ctrl + Mouse Wheel`

### 3. Draw crop rectangles

- Drag on an empty area to create a new rectangle
- Repeat as many times as needed
- Drag an existing rectangle to move it

### 4. Apply the crop layout

Click the apply-layout button after you finish placing rectangles.

This normalizes rectangle coordinates and enables export.

### 5. Export cropped images

Click the export button.

All cropped files are saved in the same folder as the source image.

## Output Naming

Example output names:

```text
test_rect_01.png
test_rect_02.png
test_rect_03.png
```

If a file name already exists, the app adds a numeric suffix automatically.

## Save And Load Crop Layouts

The app can save the current crop layout as a `JSON` file.

Saved data includes:

- source image path
- source image size
- zoom level
- rectangle coordinates
- configured state

Typical flow:

1. Open an image
2. Draw rectangles
3. Click the save-layout button
4. Save the generated `json` file
5. Later click the load-layout button
6. Reload the same crop layout

If the original image path still exists, it opens automatically while loading the saved config.

## Build A Windows EXE

Install build dependencies:

```powershell
python -m pip install -r requirements-build.txt
```

Build the executable:

```powershell
build_exe.bat
```

Build output:

```text
dist\AutoCropSplitter.exe
```

You can also build directly with PyInstaller:

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoCropSplitter --collect-all PIL app.py
```

## Project Files

- `app.py`: main GUI application
- `requirements.txt`: runtime dependencies
- `requirements-build.txt`: build dependencies
- `build_exe.bat`: build script
- `test.png`: sample image

## Troubleshooting

### Pillow import error

```powershell
python -m pip install -r requirements.txt
```

### Export button stays disabled

Click the apply-layout button after adding, moving, or deleting rectangles.

### EXE build fails

```powershell
python -m pip install -r requirements-build.txt
build_exe.bat
```

## Verification

This project has been checked with:

- `python -m py_compile app.py`
- crop rectangle export test
- config save/load test
- zoom behavior test
- Windows `.exe` build with PyInstaller
