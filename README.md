# grid-crop-image

`grid-crop-image` is a lightweight Windows desktop tool for splitting one image into multiple crop regions.
It is built for screenshot slicing, clipboard paste workflows, repeated blog asset production, and saving crop layouts as JSON.

## What It Does

- Open local images and crop multiple regions in one session.
- Paste an image directly from the clipboard with `Ctrl+V`.
- Save and reload crop layouts as JSON.
- Export cropped regions in order with collision-safe filenames.
- Run batch processing with one saved layout.
- Build a Windows executable with `PyInstaller`.

## Tech Stack

- Python 3.11+
- Tkinter
- Pillow
- PyInstaller

## Run Locally

```bash
py -m pip install -r requirements.txt
py app.py
```

## Build EXE

```bash
build_exe.bat
```

The build script now:

- checks `python` and `pip`
- bootstraps `pip` with `ensurepip` if needed
- installs missing build dependencies automatically
- falls back to `dist_builds\YYYYMMDD_HHMMSS\...` if the previous build is locked

The default output path is:

```text
dist\AutoCropSplitter\AutoCropSplitter.exe
```

## Repository Structure

- `app.py`: main Tkinter application
- `build_exe.bat`: Windows build entry point
- `AutoCropSplitter.spec`: PyInstaller spec for the stable onedir build
- `config/pages-seo.json`: metadata used to generate GitHub Pages assets
- `templates/index.template.html`: GitHub Pages template
- `scripts/generate_pages_assets.py`: regenerates root landing-page assets

## GitHub Pages

This repository uses the root directory as the GitHub Pages source.
Generated files live at the repository root:

- `index.html`
- `robots.txt`
- `sitemap.xml`
- `site.webmanifest`
- `.nojekyll`

To regenerate them:

```bash
py scripts/generate_pages_assets.py
```
