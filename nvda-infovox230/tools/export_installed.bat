@echo off
REM Export whatever the Infovox installer wrote, so Claude can read the correct
REM voice/mode definitions and file layout.
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

echo [*] Exporting Babel-Infovox registry trees
reg export "HKLM\SOFTWARE\WOW6432Node\Babel-Infovox AB\Infovox 230" "%OUT%\installed_babel_wow.reg" /y >nul 2>&1
reg export "HKLM\SOFTWARE\Babel-Infovox AB\Infovox 230" "%OUT%\installed_babel.reg" /y >nul 2>&1
reg export "HKLM\SOFTWARE\WOW6432Node\Voice\TextToSpeech" "%OUT%\installed_voice.reg" /y >nul 2>&1

echo [*] Recording install locations found in the registry
for %%K in ("HKLM\SOFTWARE\WOW6432Node\Babel-Infovox AB\Infovox 230") do (
  reg query "%%~K" /v LanguageDir 2>nul
)

echo [*] Listing the installed program folder if present
for %%D in ("C:\Program\Infovox 230" "C:\Program Files (x86)\Infovox 230" "C:\Program Files\Infovox 230" "%ProgramFiles(x86)%\Infovox 230") do (
  if exist "%%~D" (
    echo FOUND: %%~D
    dir /b "%%~D" > "%OUT%\installed_dir_listing.txt" 2>nul
    echo (listing saved^)
  )
)
echo(
echo Exports written to %OUT% : installed_babel_wow.reg, installed_voice.reg, installed_dir_listing.txt
echo(
pause
