@echo off
REM Import the reconstructed Infovox voice table, then run the self-test.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator privileges - approve the prompt
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
setlocal EnableDelayedExpansion
set HERE=%~dp0
for %%I in ("%HERE%..") do set ROOT=%%~fI
set RUN=%ROOT%\_run
set ENG=%RUN%\engine
set PY=%ROOT%\addon\synthDrivers\infovox230\python32\python.exe

echo [*] Importing voice table modes.reg
reg import "%RUN%\modes.reg"
echo     import exit code: !errorlevel!

echo [*] Running self-test...
echo(
"%PY%" "%ROOT%\host\infovox_host.py" --engine-dir "%ENG%" --log "%RUN%\selftest.log" --debug selftest "Hello. This is Infovox two thirty, speaking through N V D A." "%RUN%\first_speech.wav" --voice ""
echo     self-test exit code: !errorlevel!
echo(
if exist "%RUN%\first_speech.wav" echo [OK] first_speech.wav produced - play it!
dir /b "%RUN%\IVX230_*.LOG" 2>nul
echo(
pause
