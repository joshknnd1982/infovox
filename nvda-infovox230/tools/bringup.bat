@echo off
REM ==========================================================================
REM  Infovox 230 -> NVDA  bring-up / first-audio test.
REM  Stages an engine folder (engine DLL + .IVX rules + dongle emulator) and
REM  runs the 32-bit host self-test, which writes first_speech.wav.
REM  Run from anywhere; paths are resolved relative to this script.
REM ==========================================================================
setlocal EnableDelayedExpansion
set HERE=%~dp0
set ROOT=%HERE%..
set PROJ=%ROOT%\..
set RUN=%ROOT%\_run
set ENG=%RUN%\engine

echo(
echo === Infovox 230 bring-up ===
echo(

REM --- 1. locate a 32-bit Python -------------------------------------------
set PY=
if exist "%ROOT%\addon\synthDrivers\infovox230\python32\python.exe" (
  set "PY=%ROOT%\addon\synthDrivers\infovox230\python32\python.exe"
)
if not defined PY (
  py -3-32 -c "import struct,sys;sys.exit(0 if struct.calcsize('P')==4 else 1)" 2>nul
  if !errorlevel! == 0 set "PY=py -3-32"
)
if not defined PY (
  echo [!] No 32-bit Python found.
  echo     Either install the 32-bit Python 3 from python.org, or run:
  echo         powershell -ExecutionPolicy Bypass -File "%HERE%fetch_python32.ps1"
  echo     to fetch a private 32-bit interpreter into the add-on, then re-run this.
  exit /b 3
)
echo [*] 32-bit Python: %PY%

REM --- 2. ensure comtypes is available -------------------------------------
%PY% -c "import comtypes" 2>nul
if !errorlevel! neq 0 (
  echo [*] Installing comtypes into the 32-bit Python...
  %PY% -m pip install --quiet comtypes
  if !errorlevel! neq 0 (
    echo [!] Could not install comtypes. Install it manually: %PY% -m pip install comtypes
    exit /b 4
  )
)

REM --- 3. stage the engine folder ------------------------------------------
if not exist "%ENG%" mkdir "%ENG%"
echo [*] Staging engine files into %ENG%
copy /y "%PROJ%\Ivx230nt.dll"  "%ENG%\" >nul 2>nul
if not exist "%ENG%\Ivx230nt.dll" copy /y "%PROJ%\data1\Infovox_230_TTS_Engine_Files_NT\Ivx230nt.dll" "%ENG%\" >nul 2>nul
copy /y "%PROJ%\*.IVX"  "%ENG%\" >nul 2>nul
copy /y "%PROJ%\*.ivx"  "%ENG%\" >nul 2>nul
copy /y "%PROJ%\darules.dll" "%ENG%\" >nul 2>nul
REM the dongle emulator (built and validated by Claude):
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%ENG%\Sx32w.dll" >nul 2>nul
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%ENG%\SX32W.dll" >nul 2>nul

REM --- 4. run the self-test ------------------------------------------------
echo [*] Running self-test (writing first_speech.wav)...
echo(
%PY% "%ROOT%\host\infovox_host.py" --engine-dir "%ENG%" --log "%RUN%\selftest.log" --debug selftest "Hello. This is Infovox two thirty, speaking through N V D A." "%RUN%\first_speech.wav" --voice ""
set RC=!errorlevel!
echo(
echo === result: exit code !RC! ===
echo Log : %RUN%\selftest.log
if exist "%RUN%\first_speech.wav" (
  echo WAV : %RUN%\first_speech.wav
  echo(
  echo [OK] Open first_speech.wav to hear it. If it played, the engine speaks!
) else (
  echo [!] No WAV produced. Open the log above; the last lines say which gate blocked.
)
endlocal
exit /b %RC%
