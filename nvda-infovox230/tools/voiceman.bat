@echo off
REM ==========================================================================
REM  Launch the Infovox Voice Manager (IvxVoiceMan.exe) with the engine env set
REM  so it can detect the languages and register the voice modes. Self-elevates
REM  (needed to write voices under HKLM). Run diagnose.bat once first.
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
set PROJ=%ROOT%\..
set RUN=%ROOT%\_run
set ENG=%RUN%\engine

echo [*] Ensuring dongle emulator is in SysWOW64
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%WINDIR%\SysWOW64\Sx32w.dll" >nul

echo [*] Ensuring engine paths are set (HKLM 32-bit view)
for %%K in ("HKLM\SOFTWARE\WOW6432Node\Babel-Infovox AB\Infovox 230" "HKLM\SOFTWARE\Babel-Infovox AB\Infovox 230") do (
  reg add "%%~K" /v LanguageDir /t REG_SZ /d "%ENG%" /f >nul
  reg add "%%~K" /v LicenseDir  /t REG_SZ /d "%ENG%" /f >nul
  reg add "%%~K" /v LexiconDir  /t REG_SZ /d "%ENG%" /f >nul
  reg add "%%~K" /v LogStartup    /t REG_SZ /d "on"    /f >nul
  reg add "%%~K" /v LogStartupDir /t REG_SZ /d "%RUN%" /f >nul
)

echo [*] Copying the Voice Manager next to the engine and launching it
copy /y "%PROJ%\IvxVoiceMan.exe" "%ENG%\IvxVoiceMan.exe" >nul 2>nul
if not exist "%ENG%\IvxVoiceMan.exe" copy /y "%ROOT%\..\IvxVoiceMan.exe" "%ENG%\IvxVoiceMan.exe" >nul 2>nul
pushd "%ENG%"
echo(
echo === Launching Voice Manager. In its window, look for the available
echo === languages/voices and an option to Add / Install / Register them,
echo === then close it. Tell Claude what you see.
echo(
start "" "%ENG%\IvxVoiceMan.exe"
popd
pause
