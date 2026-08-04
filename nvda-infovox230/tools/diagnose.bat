@echo off
REM ==========================================================================
REM  Infovox 230 -- elevated diagnostic. Registers the engine (populates its
REM  mode table), points it at the staged files, turns on the engine's OWN
REM  startup log, and runs the self-test. Self-elevates via UAC.
REM  Run bringup.bat once first (to stage files + fetch 32-bit Python).
REM ==========================================================================
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Requesting administrator privileges - please approve the prompt
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
setlocal EnableDelayedExpansion
set HERE=%~dp0
for %%I in ("%HERE%..") do set ROOT=%%~fI
set RUN=%ROOT%\_run
set ENG=%RUN%\engine
set PY=%ROOT%\addon\synthDrivers\infovox230\python32\python.exe

echo(
echo === Infovox 230 diagnose - elevated ===
echo ROOT=%ROOT%
if not exist "%ENG%\Ivx230nt.dll" (
  echo [!] Engine not staged at %ENG% -- run bringup.bat first.
  pause & exit /b 1
)

echo [*] Copying dongle emulator to SysWOW64 so every loader resolves Sx32w.dll
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%WINDIR%\SysWOW64\Sx32w.dll" >nul

echo [*] Setting engine paths + enabling the engine's startup log (HKLM, 32-bit view)
for %%K in ("HKLM\SOFTWARE\WOW6432Node\Babel-Infovox AB\Infovox 230" "HKLM\SOFTWARE\Babel-Infovox AB\Infovox 230") do (
  reg add "%%~K" /v LanguageDir   /t REG_SZ /d "%ENG%" /f >nul
  reg add "%%~K" /v LicenseDir    /t REG_SZ /d "%ENG%" /f >nul
  reg add "%%~K" /v LexiconDir    /t REG_SZ /d "%ENG%" /f >nul
  reg add "%%~K" /v LogStartup    /t REG_SZ /d "on"    /f >nul
  reg add "%%~K" /v LogStartupDir /t REG_SZ /d "%RUN%" /f >nul
)

echo [*] Registering the engine (regsvr32, 32-bit) -- populates the mode table
pushd "%ENG%"
%WINDIR%\SysWOW64\regsvr32.exe /s "%ENG%\Ivx230nt.dll"
echo     regsvr32 exit code: !errorlevel!
popd

echo [*] Running self-test...
echo(
"%PY%" "%ROOT%\host\infovox_host.py" --engine-dir "%ENG%" --log "%RUN%\selftest.log" --debug selftest "Hello. This is Infovox two thirty, speaking." "%RUN%\first_speech.wav" --voice ""
echo(
echo     self-test exit code: !errorlevel!
echo(
echo [*] Exporting registry state for inspection
reg export "HKLM\SOFTWARE\WOW6432Node\Babel-Infovox AB\Infovox 230" "%RUN%\reg_babel_wow.reg" /y >nul 2>nul
reg export "HKLM\SOFTWARE\Babel-Infovox AB\Infovox 230" "%RUN%\reg_babel.reg" /y >nul 2>nul
reg export "HKLM\SOFTWARE\WOW6432Node\Microsoft\Speech" "%RUN%\reg_speech_wow.reg" /y >nul 2>nul
reg export "HKLM\SOFTWARE\WOW6432Node\Voice" "%RUN%\reg_voice_wow.reg" /y >nul 2>nul
echo(
echo === logs written to %RUN% ===
echo   selftest.log  reg_babel_wow.reg  reg_speech_wow.reg
dir /b "%RUN%\IVX230_*.LOG" 2>nul
if exist "%RUN%\first_speech.wav" echo   [OK] first_speech.wav was produced -- play it!
echo(
pause
