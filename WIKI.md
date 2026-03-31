# Grid Crop Studio Wiki

## Overview

`Grid Crop Studio` is a Windows image cutting workspace for people who repeatedly slice screenshots, blog images, store listings, or card-style layouts.

It is focused on:

- fast crop selection
- reusable JSON layouts
- repeated batch output
- simple history tracking
- optional OCR expansion

## Quick Start

1. Press `사진 열기` or `붙여넣기`
2. Press `저장 폴더`
3. Draw one or more crop areas
4. Press `확정`
5. Press `잘라서 저장`

## Main Screens

### Top Action Area

- `사진 가져오기`: `사진 열기`, `붙여넣기`, `저장`, `불러오기`
- `작업 실행`: `여러 장`, `다시`, `기록`, `글자 읽기`, `모델 넣기`
- `화면 조절`: `화면 맞춤`, `지우기`, `전체 지우기`, `칸 나누기`, `확정`

### Work Canvas

- draw crop areas directly on the main canvas
- drag inside an area to move it
- drag handles to resize it
- use `Shift` to keep a square
- use `Ctrl + mouse wheel` to zoom

### Right Info Panel

- current image summary
- crop area count
- output folder shortcut buttons
- action-focused status hints

## Reusable Layouts

Use `저장` to save crop areas as JSON.

Saved layouts can be:

- loaded later with `불러오기`
- reused in `여러 장`
- scaled to match different image sizes when needed

## Batch Processing

Use `여러 장` when one crop layout needs to be applied to many image files.

Batch mode supports:

- file list input
- folder scan input
- current layout or JSON layout source
- output folder selection
- optional subfolder creation per source image
- failed item retry with `다시`

## History

The program saves work history to:

```text
.crop_history.jsonl
```

It stores:

- single export jobs
- batch export jobs
- OCR jobs

The history viewer can filter by:

- date
- job type
- OCR text
- sort order

## OCR

The `글자 읽기` button is optional.

It requires:

- a built C++ OCR runner
- OCR model files in `cpp/ocr_engine/models`

The app can also import a prepared OCR ZIP through `모델 넣기`.

## Build Notes

Use:

```bash
build_exe.bat
```

Run the packaged app from:

```text
dist\AutoCropSplitter\AutoCropSplitter.exe
```

Do not run the temporary executable under `build\`.

## Public Docs

- GitHub Pages: `https://sheryloe.github.io/grid-crop-image/`
- README: `https://github.com/sheryloe/grid-crop-image/blob/main/README.md`
- This wiki file: `https://github.com/sheryloe/grid-crop-image/blob/main/WIKI.md`
