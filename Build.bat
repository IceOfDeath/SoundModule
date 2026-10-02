@echo off
setlocal
cd /d "%~dp0"
if not exist Build mkdir Build
where python >nul 2>nul
if errorlevel 1 (
  echo Download python firstly!
  start "" "https://www.python.org/downloads/"
  pause
  exit /b 1
)
python -m pip install --upgrade pip
python -m pip install -r Assets\requirements.txt
if errorlevel 1 (
  echo.
  echo Dependency installation failed. See the error above.
  pause
  exit /b 1
)
if exist Build\Matchasoundmodule.exe del /q Build\Matchasoundmodule.exe
python -m PyInstaller --noconfirm --clean --onefile --windowed --name Matchasoundmodule --icon "%CD%\Assets\app.ico" --add-data "%CD%\Assets\Reasons.json;Assets" --distpath Build --workpath .pyinstaller-build --specpath .pyinstaller-build Soundplay.py
set "BUILD_ERROR=%ERRORLEVEL%"
if exist .pyinstaller-build rmdir /s /q .pyinstaller-build
if not "%BUILD_ERROR%"=="0" (
  echo.
  echo Build failed. PyInstaller exit code: %BUILD_ERROR%
  pause
  exit /b %BUILD_ERROR%
)
echo Build complete: Build\Matchasoundmodule.exe
pause
