@echo off
REM Test whether the .ivx load fails because the engine dir is under OneDrive.
REM Stages the engine to a plain local path and re-runs the self-test there.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator privileges - approve the prompt
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
setlocal EnableDelayedExpansion
set HERE=%~dp0
for %%I in ("%HERE%..") do set ROOT=%%~fI
set SRC=%ROOT%\_run\engine
set DST=C:\infovox230test
set PY=%ROOT%\addon\synthDrivers\infovox230\python32\python.exe

echo [*] Staging engine to local path %DST%
if not exist "%DST%" mkdir "%DST%"
copy /y "%SRC%\*.*" "%DST%\" >nul
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%DST%\Sx32w.dll" >nul

echo [*] Pointing engine at %DST% (HKLM 32-bit view) + engine log on
for %%K in ("HKLM\SOFTWARE\WOW6432Node\Babel-Infovox AB\Infovox 230" "HKLM\SOFTWARE\Babel-Infovox AB\Infovox 230") do (
  reg add "%%~K" /v LanguageDir   /t REG_SZ /d "%DST%" /f >nul
  reg add "%%~K" /v LicenseDir    /t REG_SZ /d "%DST%" /f >nul
  reg add "%%~K" /v LexiconDir    /t REG_SZ /d "%DST%" /f >nul
  reg add "%%~K" /v LogStartup    /t REG_SZ /d "on"    /f >nul
  reg add "%%~K" /v LogStartupDir /t REG_SZ /d "%DST%" /f >nul
)

echo [*] Importing voice table (Modes)
reg import "%ROOT%\_run\modes.reg" >nul 2>&1

echo [*] Running self-test from local dir...
echo(
"%PY%" "%ROOT%\host\infovox_host.py" --engine-dir "%DST%" --log "%DST%\selftest.log" --debug selftest "Hello. This is Infovox two thirty." "%DST%\first_speech.wav" --voice ""
echo     exit code: !errorlevel!
echo(
if exist "%DST%\first_speech.wav" echo [OK] first_speech.wav produced in %DST%
echo Logs in %DST% : selftest.log and IVX230_*.LOG
dir /b "%DST%\IVX230_*.LOG" 2>nul
copy /y "%DST%\selftest.log" "%ROOT%\_run\selftest_local.log" >nul 2>&1
copy /y "%DST%\IVX230_*.LOG" "%ROOT%\_run\" >nul 2>&1
echo(
pause
