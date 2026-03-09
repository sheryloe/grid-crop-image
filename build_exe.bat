@echo off
setlocal
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoCropSplitter --collect-all PIL app.py
