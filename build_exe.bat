@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "APP_NAME=AutoCropSplitter"
set "SPEC_FILE=%APP_NAME%.spec"
set "TARGET_DIR=%CD%\dist\%APP_NAME%"
set "TARGET_EXE=%TARGET_DIR%\%APP_NAME%.exe"
set "FALLBACK_DIST="
set "OUTPUT_EXE=%TARGET_EXE%"

echo [1/5] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo Python is not installed or not available in PATH.
    exit /b 1
)

echo [2/5] Checking pip...
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo pip is missing. Bootstrapping with ensurepip...
    python -m ensurepip --upgrade
    if errorlevel 1 (
        echo Failed to bootstrap pip.
        exit /b 1
    )
)

echo [3/5] Checking build dependencies...
set "NEEDS_INSTALL="
for %%M in (PIL PyInstaller) do (
    python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('%%M') else 1)" >nul 2>&1
    if errorlevel 1 set "NEEDS_INSTALL=1"
)

if defined NEEDS_INSTALL (
    echo Missing dependency detected. Installing requirements-build.txt...
    python -m pip install --disable-pip-version-check -r requirements-build.txt
    if errorlevel 1 (
        echo Failed to install required packages.
        exit /b 1
    )
) else (
    echo Build dependencies already installed.
)

echo [4/5] Checking whether the previous build can be replaced...
powershell -NoProfile -Command "if (Get-Process -Name '%APP_NAME%' -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo Running %APP_NAME%.exe detected.
    echo Build will continue in a new output folder.
    call :set_fallback_dist
)

if not defined FALLBACK_DIST if exist "%TARGET_DIR%" (
    powershell -NoProfile -Command "if (Test-Path -LiteralPath '%TARGET_DIR%') { Remove-Item -LiteralPath '%TARGET_DIR%' -Recurse -Force -ErrorAction SilentlyContinue }" >nul 2>&1
    if exist "%TARGET_DIR%" (
        echo Could not replace "%TARGET_DIR%".
        echo Build will continue in a new output folder.
        call :set_fallback_dist
    )
)

echo [5/5] Building executable...
if exist "%SPEC_FILE%" (
    if defined FALLBACK_DIST (
        python -m PyInstaller --noconfirm --clean --distpath "%FALLBACK_DIST%" "%SPEC_FILE%"
    ) else (
        python -m PyInstaller --noconfirm --clean "%SPEC_FILE%"
    )
) else (
    if defined FALLBACK_DIST (
        python -m PyInstaller --noconfirm --clean --distpath "%FALLBACK_DIST%" --windowed --name "%APP_NAME%" --collect-all PIL app.py
    ) else (
        python -m PyInstaller --noconfirm --clean --windowed --name "%APP_NAME%" --collect-all PIL app.py
    )
)

if errorlevel 1 (
    echo Build failed.
    exit /b 1
)

if defined FALLBACK_DIST set "OUTPUT_EXE=%FALLBACK_DIST%\%APP_NAME%\%APP_NAME%.exe"
echo Build completed: "%OUTPUT_EXE%"
exit /b 0

:set_fallback_dist
if defined FALLBACK_DIST exit /b 0
for /f %%I in ('powershell -NoProfile -Command "(Get-Date).ToString(\"yyyyMMdd_HHmmss\")"') do set "BUILD_STAMP=%%I"
set "FALLBACK_DIST=%CD%\dist_builds\%BUILD_STAMP%"
exit /b 0
