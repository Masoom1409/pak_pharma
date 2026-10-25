@echo off
SETLOCAL EnableDelayedExpansion
TITLE PakPharma POS - Automated Windows 10/11 Build & Installer Pipeline

echo ============================================================================
echo  PakPharma POS - Windows Executable ^& Installer Build Pipeline (v1.0.0)
echo ============================================================================

cd /d "%~dp0\.."

echo [1/5] Checking Python 3.11+ installation...
python --version
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Python 3 is not installed or not on PATH on this build machine.
    exit /b 1
)

echo [2/5] Creating isolated virtual environment (.venv_build)...
if not exist ".venv_build" (
    python -m venv .venv_build
)
call .venv_build\Scripts\activate.bat

echo [3/5] Installing required dependencies (PySide6, ReportLab, OpenPyXL, PyInstaller)...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo [4/5] Running Automated Acceptance Test Suite (20 Acceptance Criteria)...
python -m unittest discover -s tests -p "test_*.py" -v
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: Acceptance test suite failed! Aborting Windows build.
    exit /b 1
)

echo [5/5] Building standalone PakPharmaPOS.exe via PyInstaller...
pyinstaller --noconfirm --clean installer\PakPharmaPOS.spec
IF %ERRORLEVEL% NEQ 0 (
    echo ERROR: PyInstaller build failed!
    exit /b 1
)

echo Checking for Inno Setup 6 Compiler (ISCC.exe)...
set "ISCC_PATH=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if exist "%ISCC_PATH%" (
    echo Compiling Windows Setup Wizard (PakPharmaPOS_Setup_v1.0.0.exe)...
    "%ISCC_PATH%" installer\PakPharmaPOS_Installer.iss
    echo SUCCESS: Installer created at dist_installer\PakPharmaPOS_Setup_v1.0.0.exe
) else (
    echo NOTE: Inno Setup 6 not found at default path.
    echo Standalone folder distribution is ready at: dist\PakPharmaPOS\PakPharmaPOS.exe
    echo Install Inno Setup 6 and run ISCC.exe installer\PakPharmaPOS_Installer.iss to build the Setup EXE.
)

echo ============================================================================
echo  Build Complete!
echo ============================================================================
ENDLOCAL
