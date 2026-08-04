@echo off
REM Run our PATCHED engine against the installer's own setup (its registry Modes,
REM its Lang\*.ivx, its license). Decisive test of dongle-bypass + correct data.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator privileges - approve the prompt
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
setlocal EnableDelayedExpansion
set HERE=%~dp0
for %%I in ("%HERE%..") do set ROOT=%%~fI
set OUT=%ROOT%\_run
set PROG=C:\Program\Infovox 230
set LOGD=C:\infovox230test
set PY=%ROOT%\addon\synthDrivers\infovox230\python32\python.exe

if not exist "%PROG%\Ivx230nt.dll" (
  echo [!] %PROG% not found -- run the installer first.
  pause & exit /b 1
)
if not exist "%LOGD%" mkdir "%LOGD%"

echo [*] Backing up + swapping in the patched engine DLL
if not exist "%PROG%\Ivx230nt.dll.orig" copy /y "%PROG%\Ivx230nt.dll" "%PROG%\Ivx230nt.dll.orig" >nul
copy /y "%ROOT%\addon\synthDrivers\infovox230\engine\Ivx230nt.dll" "%PROG%\Ivx230nt.dll"
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%PROG%\Sx32w.dll" >nul
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%WINDIR%\SysWOW64\Sx32w.dll" >nul
echo [*] MD5 of the engine that will load (expect 7abfe68c3796f90768400b8fd29dca32):
certutil -hashfile "%PROG%\Ivx230nt.dll" MD5 | find /i /v "hash" | find /i /v "certutil"

echo [*] Enabling engine startup log
reg add "HKLM\SOFTWARE\WOW6432Node\Babel-Infovox AB\Infovox 230" /v LogStartup    /t REG_SZ /d "on"     /f >nul
reg add "HKLM\SOFTWARE\WOW6432Node\Babel-Infovox AB\Infovox 230" /v LogStartupDir /t REG_SZ /d "%LOGD%" /f >nul

echo [*] Running self-test (patched engine + installer registry, keep-registry)
echo(
"%PY%" "%ROOT%\host\infovox_host.py" --engine-dir "%PROG%" --keep-registry --log "%OUT%\selftest_installed.log" --debug selftest "Hello. This is Infovox two thirty, finally speaking." "%LOGD%\first_speech.wav" --voice ""
echo     exit code: !errorlevel!
echo(
if exist "%LOGD%\first_speech.wav" echo [OK] first_speech.wav produced in %LOGD%
copy /y "%LOGD%\IVX230_*.LOG" "%OUT%\" >nul 2>&1
echo Logs copied to %OUT%
echo(
pause
