@echo off
setlocal
set HERE=%~dp0
for %%I in ("%HERE%..") do set ROOT=%%~fI
set PY=%ROOT%\addon\synthDrivers\infovox230\python32\python.exe
set ENGSRC=%ROOT%\addon\synthDrivers\infovox230\engine
set ENG=C:\infovox230sc
echo [*] Staging full engine (DLL + all .ivx + darules.dll + emulator) to %ENG%
if not exist "%ENG%" mkdir "%ENG%"
copy /y "%ENGSRC%\*.*" "%ENG%\" >nul
copy /y "%ROOT%\sx32w_stub\sx32w.dll" "%ENG%\Sx32w.dll" >nul
echo [*] Testing the NVDA serve protocol...
echo(
"%PY%" "%HERE%serve_client_test.py" "%ENG%"
echo(
pause
