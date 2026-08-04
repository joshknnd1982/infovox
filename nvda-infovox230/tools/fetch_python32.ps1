# Fetch a private 32-bit CPython into the add-on so the host needs no
# system Python. Produces: addon\synthDrivers\infovox230\python32\python.exe
# with pip + comtypes installed. Requires internet. Windows PowerShell 5+.
param(
  [string]$Version = "3.11.9"   # any 32-bit 3.x works; independent of NVDA's Python
)
$ErrorActionPreference = "Stop"
# Windows PowerShell 5.x often negotiates TLS 1.0 by default, which python.org
# and bootstrap.pypa.io reject. Force TLS 1.2.
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$dest = Join-Path $here "..\addon\synthDrivers\infovox230\python32"
$dest = [System.IO.Path]::GetFullPath($dest)
$tmp  = Join-Path $env:TEMP "ivx_py32"
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
New-Item -ItemType Directory -Force -Path $dest | Out-Null

$zipUrl = "https://www.python.org/ftp/python/$Version/python-$Version-embed-win32.zip"
$zip = Join-Path $tmp "embed.zip"
Write-Host "[*] Downloading $zipUrl"
Invoke-WebRequest -Uri $zipUrl -OutFile $zip
Write-Host "[*] Extracting to $dest"
Expand-Archive -Path $zip -DestinationPath $dest -Force

# Enable site-packages in the embeddable distribution (._pth file).
$pth = Get-ChildItem -Path $dest -Filter "python*._pth" | Select-Object -First 1
if ($pth) {
  (Get-Content $pth.FullName) `
    -replace '^#\s*import site', 'import site' | Set-Content $pth.FullName
  Add-Content $pth.FullName "Lib\site-packages"
}

# Bootstrap pip, then install comtypes.
$getpip = Join-Path $tmp "get-pip.py"
Write-Host "[*] Bootstrapping pip"
Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip
& (Join-Path $dest "python.exe") $getpip --no-warn-script-location
Write-Host "[*] Installing comtypes"
& (Join-Path $dest "python.exe") -m pip install --no-warn-script-location comtypes

Write-Host "[OK] 32-bit Python ready at $dest"
