param(
    [switch]$RecreateVenv
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"

Write-Host "SkyGuard setup" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path $RequirementsPath)) {
    throw "requirements.txt was not found at $RequirementsPath"
}

if ($RecreateVenv -and (Test-Path $VenvPath)) {
    Write-Host "Removing existing .venv..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    py -3 -m venv $VenvPath
}

Write-Host "Upgrading pip..." -ForegroundColor Cyan
& $PythonExe -m pip install --upgrade pip

Write-Host "Installing project requirements..." -ForegroundColor Cyan
& $PythonExe -m pip install -r $RequirementsPath

Write-Host "Verifying imports..." -ForegroundColor Cyan
$VerifyScript = @"
import cv2
import numpy
import PySide6
import qfluentwidgets
import websockets

print("Python environment OK")
print(f"OpenCV: {cv2.__version__}")
print(f"NumPy: {numpy.__version__}")
"@
$VerifyScript | & $PythonExe -

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Run streamer:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe run_streamer.py"
Write-Host "Run operator:" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe run_operator.py"
