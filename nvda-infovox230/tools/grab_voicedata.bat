@echo off
REM Copy the installer's known-good voice data (.ivx + lexicons) into the add-on
REM so the finished .nvda-addon is self-contained.
setlocal EnableDelayedExpansion
set HERE=%~dp0
for %%I in ("%HERE%..") do set ROOT=%%~fI
set PROG=C:\Program\Infovox 230
set ENGDST=%ROOT%\addon\synthDrivers\infovox230\engine

if not exist "%PROG%\Lang" ( echo [!] %PROG%\Lang not found - run the Infovox installer first. & pause & exit /b 1 )
if not exist "%ENGDST%" mkdir "%ENGDST%"

echo [*] Copying voice rule files from %PROG%\Lang
copy /y "%PROG%\Lang\*.*" "%ENGDST%\" >nul
if exist "%PROG%\Lex" (
  if not exist "%ENGDST%\Lex" mkdir "%ENGDST%\Lex"
  copy /y "%PROG%\Lex\*.*" "%ENGDST%\Lex\" >nul 2>&1
)
echo [*] Voice data staged into the add-on:
dir /b "%ENGDST%\*.ivx"
echo(
echo Done. Tell Claude it's copied.
pause
