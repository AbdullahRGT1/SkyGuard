param(
    [switch]$RecreateVenv
)

$ErrorActionPreference = "Stop"
trap {
    Write-Host ""
    Write-Host "CUDA AI setup failed." -ForegroundColor Red
    Write-Host $_ -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close this installer"
    exit 1
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseSetup = Join-Path $ProjectRoot "setup_project.ps1"
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$CommonRequirementsPath = Join-Path $ProjectRoot "requirements-ai-common.txt"
$BackendRequirementsPath = Join-Path $ProjectRoot "requirements-ai-cuda.txt"
$SitePackagesPath = Join-Path $VenvPath "Lib\site-packages"
$TorchCudaIndexUrl = "https://download.pytorch.org/whl/cu128"

function Wait-ForVenvPythonToClose {
    while ($true) {
        $runningPython = @(Get-Process python -ErrorAction SilentlyContinue | Where-Object {
            $_.Path -and (([System.IO.Path]::GetFullPath($_.Path)) -eq ([System.IO.Path]::GetFullPath($PythonExe)))
        })

        if ($runningPython.Count -eq 0) {
            return
        }

        Write-Host ""
        Write-Host "Python is still running from this virtual environment:" -ForegroundColor Yellow
        $runningPython | ForEach-Object {
            Write-Host "  PID $($_.Id): $($_.Path)" -ForegroundColor Yellow
        }
        Write-Host "Close the operator app and any Python terminals using this project, then press Enter." -ForegroundColor Yellow
        Read-Host "Press Enter to check again"
    }
}

function Remove-PipLeftovers {
    if (-not (Test-Path $SitePackagesPath)) {
        return
    }

    Get-ChildItem -LiteralPath $SitePackagesPath -Directory -Force |
        Where-Object { $_.Name -like "~orch*" } |
        ForEach-Object {
            Write-Host "Removing leftover directory: $($_.Name)" -ForegroundColor Cyan
            Remove-Item -LiteralPath $_.FullName -Recurse -Force -ErrorAction SilentlyContinue
        }
}

Write-Host "SkyGuard AI setup - CUDA" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path $BaseSetup)) {
    throw "setup_project.ps1 was not found at $BaseSetup"
}

if (-not (Test-Path $PythonExe) -or $RecreateVenv) {
    Write-Host "Preparing base environment first..." -ForegroundColor Cyan
    & $BaseSetup -RecreateVenv:$RecreateVenv
}

if (-not (Test-Path $CommonRequirementsPath)) {
    throw "requirements-ai-common.txt was not found at $CommonRequirementsPath"
}
if (-not (Test-Path $BackendRequirementsPath)) {
    throw "requirements-ai-cuda.txt was not found at $BackendRequirementsPath"
}

Write-Host "Installing CUDA AI requirements..." -ForegroundColor Cyan
Wait-ForVenvPythonToClose
Write-Host "Removing any existing PyTorch build first..." -ForegroundColor Cyan
& $PythonExe -m pip uninstall torch torchvision torchaudio -y
Write-Host "Removing any existing ONNX Runtime build first..." -ForegroundColor Cyan
& $PythonExe -m pip uninstall onnxruntime onnxruntime-gpu -y
Remove-PipLeftovers
Write-Host "Installing CUDA PyTorch from $TorchCudaIndexUrl..." -ForegroundColor Cyan
& $PythonExe -m pip install torch torchvision torchaudio --index-url $TorchCudaIndexUrl
Write-Host "Installing CUDA ONNX Runtime packages..." -ForegroundColor Cyan
& $PythonExe -m pip install -r $BackendRequirementsPath
Write-Host "Installing shared AI packages..." -ForegroundColor Cyan
& $PythonExe -m pip install -r $CommonRequirementsPath

Write-Host "Verifying CUDA AI imports..." -ForegroundColor Cyan
$VerifyScript = @"
from pathlib import Path
import torch
from ultralytics import YOLO
import cvzone
import insightface
import onnxruntime as ort

root = Path(r"$ProjectRoot")
model_path = root / "AI_layer" / "yolo" / "light_2.6k.pt"

print("AI CUDA environment installed")
print(f"Torch: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"InsightFace: {insightface.__version__}")
providers = ort.get_available_providers()
print(f"ONNX Runtime providers: {providers}")
if torch.cuda.is_available():
    print(f"CUDA device: {torch.cuda.get_device_name(0)}")
else:
    raise SystemExit(
        "CUDA setup installed a non-working PyTorch build. "
        "Check the NVIDIA driver and PyTorch CUDA wheel support for this Python version."
    )

if "+cpu" in torch.__version__.lower():
    raise SystemExit("CUDA setup installed a CPU-only PyTorch wheel.")

if "CUDAExecutionProvider" not in providers:
    print(
        "Warning: onnxruntime-gpu did not expose CUDAExecutionProvider. "
        "YOLO can still use CUDA, but InsightFace Smart Alerts will fall back to CPU."
    )

if model_path.exists():
    model = YOLO(str(model_path))
    print(f"Loaded model: {model_path.name}")
    print(f"Classes: {model.names}")
else:
    print(f"Model not found yet: {model_path}")
"@
$VerifyScript | & $PythonExe -

Write-Host ""
Write-Host "CUDA AI setup complete." -ForegroundColor Green
Read-Host "Press Enter to close this installer"
