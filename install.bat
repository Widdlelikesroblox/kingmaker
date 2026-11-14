@echo off
rem Kingmaker installer for Windows.
rem Finds Python, compiles the fast C engine if gcc is available, and creates Kingmaker.bat.
cd /d "%~dp0"
set "PYCMD="

echo.
echo ==^> Looking for Python 3.10 or newer

rem Try the official "py" launcher first, then "python". Each one is run for real, because the
rem Microsoft Store shortcut exists on PATH but is not a working Python.
py -3 -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PYCMD=py -3"
if defined PYCMD goto found

python -c "import sys; sys.exit(0 if sys.version_info[:2] >= (3,10) else 1)" >nul 2>nul
if not errorlevel 1 set "PYCMD=python"
if defined PYCMD goto found

echo.
echo No working Python 3.10 or newer was found.
echo.
echo   1. Download Python from https://www.python.org/downloads/windows/
echo   2. In the installer, tick "Add python.exe to PATH" and keep "tcl/tk and IDLE" ticked.
echo   3. Close this window and run install.bat again.
echo.
echo If you already installed Python, the Windows Store shortcut may be getting in the way.
echo Open Settings, Apps, Advanced app settings, App execution aliases, and turn off
echo "App Installer python.exe" and "App Installer python3.exe".
echo.
pause
exit /b 1

:found
echo Using %PYCMD%
%PYCMD% --version

%PYCMD% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Tkinter is missing. Reinstall Python and keep "tcl/tk and IDLE" ticked.
  pause
  exit /b 1
)

echo.
echo ==^> Building the C engine
where gcc >nul 2>nul
if errorlevel 1 (
  echo No gcc found, so the app will use the slower Python engine.
  echo For full strength install a C compiler, for example by running:
  echo     winget install BrechtSanders.WinLibs.POSIX.UCRT
  echo then open a new window and run install.bat again.
) else (
  %PYCMD% build_native.py
)

echo.
echo ==^> Creating launcher
> Kingmaker.bat echo @echo off
>> Kingmaker.bat echo cd /d "%%~dp0"
>> Kingmaker.bat echo %PYCMD% run.py
echo Done. Start Kingmaker by double-clicking Kingmaker.bat
pause
