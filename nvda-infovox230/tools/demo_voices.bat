@echo off
REM Longer demo: speak a phrase in each language + each formant voice, and also
REM copy first_speech.wav back, so Claude can verify and Josh can listen.
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
set DEMO=C:\infovox230test\demo
set PY=%ROOT%\addon\synthDrivers\infovox230\python32\python.exe

if not exist "%DEMO%" mkdir "%DEMO%"

echo [*] Ensuring patched engine + emulator are in place
copy /y "%ROOT%\addon\synthDrivers\infovox230\engine\Ivx230nt.dll" "%PROG%\Ivx230nt.dll" >nul
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%PROG%\Sx32w.dll" >nul
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%WINDIR%\SysWOW64\Sx32w.dll" >nul

echo [*] Synthesizing all languages and voices...
echo(
"%PY%" "%ROOT%\host\infovox_host.py" --engine-dir "%PROG%" --keep-registry --log "%OUT%\demo.log" --debug speakmany "%DEMO%"
echo     exit code: !errorlevel!
echo(
echo [*] Copying WAVs back to %OUT% for review
copy /y "C:\infovox230test\first_speech.wav" "%OUT%\first_speech.wav" >nul 2>&1
copy /y "%DEMO%\all_voices.wav" "%OUT%\all_voices.wav" >nul 2>&1
copy /y "%DEMO%\*.wav" "%OUT%\demo_clips\" >nul 2>&1
if not exist "%OUT%\demo_clips" mkdir "%OUT%\demo_clips"
xcopy /y /q "%DEMO%\*.wav" "%OUT%\demo_clips\" >nul 2>&1
echo Done. all_voices.wav is the combined demo; play it.
echo(
pause
