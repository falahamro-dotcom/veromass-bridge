# Builds both frozen executables fresh (in the bridge repo's own
# .build-venv, created once via: py -3.12 -m venv .build-venv; then
# .build-venv\Scripts\pip install pyinstaller requests openpyxl numpy
# scipy pandas) and compiles the Inno Setup installer on top of them.
#
# Deliberately NOT using the system default Python — as of 2026-07-23
# this machine's default is 3.14, which PyInstaller 6.21 does not yet
# fully support (a real build failure, not a hypothetical: a frozen
# --onedir bridge build corrupted its own child-process bootstrap in a
# way traced back to the 3.14 environment, evidenced by "missing module
# collections.abc" — a stdlib module that always exists — showing up in
# PyInstaller's own build warnings). Always build with the pinned venv.

$ErrorActionPreference = "Stop"

$BridgeDir = Split-Path -Parent $PSScriptRoot
$AlignerDir = Join-Path (Split-Path -Parent $BridgeDir) "veromass-aligner"
$Venv = Join-Path $BridgeDir ".build-venv"

if (-not (Test-Path $Venv)) {
    throw "Build venv not found at $Venv — create it first: py -3.12 -m venv `"$Venv`"; & `"$Venv\Scripts\pip`" install pyinstaller requests openpyxl numpy scipy pandas openpyxl"
}

& "$Venv\Scripts\Activate.ps1"

Write-Host "Building VeroMass_Bridge.exe (onedir)..."
Push-Location $BridgeDir
Remove-Item build,dist,*.spec -Recurse -Force -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --onedir --windowed --name VeroMass_Bridge bridge.py
Pop-Location

Write-Host "Building VeroMass_Aligner.exe (onefile)..."
Push-Location $AlignerDir
Remove-Item build,dist,*.spec -Recurse -Force -ErrorAction SilentlyContinue
python -m PyInstaller --noconfirm --onefile --windowed --name VeroMass_Aligner --hidden-import select --hidden-import selectors VeroMass_Aligner.py
Pop-Location

Write-Host "Compiling installer..."
$Iscc = "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) {
    $Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
& $Iscc "$PSScriptRoot\VeroMassSetup.iss"

Write-Host "Done — installer in $PSScriptRoot\output\"
