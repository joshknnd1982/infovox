@echo off
REM Self-contained (no-admin) test: host writes the voice table to HKCU itself,
REM engine reads HKCU (patched), speaks. Also copies the installer's .ivx into
REM the add-on so it can be bundled.
setlocal EnableDelayedExpansion
set HERE=%~dp0
for %%I in ("%HERE%..") do set ROOT=%%~fI
set OUT=%ROOT%\_run
set ENGADDON=%ROOT%\addon\synthDrivers\infovox230\engine
set MODES=%ROOT%\addon\synthDrivers\infovox230\modes.json
set PROG=C:\Program\Infovox 230
set ENG=C:\infovox230sc

set PY=
if exist "%ROOT%\addon\synthDrivers\infovox230\python32\python.exe" set "PY=%ROOT%\addon\synthDrivers\infovox230\python32\python.exe"
if not defined PY (py -3-32 -c "import struct,sys;sys.exit(0 if struct.calcsize('P')==4 else 1)" 2>nul && set "PY=py -3-32")
if not defined PY ( echo [!] No 32-bit Python found. & pause & exit /b 3 )

echo [*] Pulling installer voice data into the add-on
if exist "%PROG%\Lang" copy /y "%PROG%\Lang\*.ivx" "%ENGADDON%\" >nul

echo [*] Staging clean local engine dir %ENG%
if not exist "%ENG%" mkdir "%ENG%"
copy /y "%ENGADDON%\Ivx230nt.dll" "%ENG%\" >nul
copy /y "%ENGADDON%\*.ivx" "%ENG%\" >nul
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%ENG%\Sx32w.dll" >nul

echo [*] Clearing any old HKCU Infovox config (fresh self-contained test)
reg delete "HKCU\Software\Babel-Infovox AB\Infovox 230" /f >nul 2>&1

echo [*] Running host (no --keep-registry: it writes HKCU config + 60 modes, then speaks)
echo(
%PY% "%ROOT%\host\infovox_host.py" --engine-dir "%ENG%" --modes "%MODES%" --log "%OUT%\sc.log" --debug selftest "This is the self contained Infovox two thirty add-on for N V D A." "%ENG%\sc_test.wav" --voice ""
echo     exit code: !errorlevel!
echo(
copy /y "%ENG%\sc_test.wav" "%OUT%\sc_test.wav" >nul 2>&1
copy /y "%ENG%\IVX230_*.LOG" "%OUT%\" >nul 2>&1
if exist "%OUT%\sc_test.wav" ( echo [OK] Self-contained speech produced, no admin used. ) else ( echo [!] No WAV - see %OUT%\sc.log )
echo(
pause
