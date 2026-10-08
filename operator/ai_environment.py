from __future__ import annotations

import sys
from pathlib import Path

VALID_AI_BACKENDS = {"cpu", "cuda"}


def project_python(project_root: Path) -> Path:
    venv_python = project_root / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def setup_script(project_root: Path, backend: str) -> Path:
    normalized = backend.lower()
    if normalized not in VALID_AI_BACKENDS:
        raise ValueError(f"Unknown AI backend: {backend}")
    return project_root / f"setup_ai_{normalized}.ps1"


def environment_probe_code() -> str:
    return r'''
import importlib.util
import json
import sys

status = {
    "python": sys.executable,
    "torch_installed": False,
    "torch_version": "",
    "cuda_available": False,
    "cuda_device": "",
    "backend": "Not installed",
    "ultralytics_installed": importlib.util.find_spec("ultralytics") is not None,
    "cvzone_installed": importlib.util.find_spec("cvzone") is not None,
    "insightface_installed": importlib.util.find_spec("insightface") is not None,
    "onnxruntime_installed": importlib.util.find_spec("onnxruntime") is not None,
    "onnx_providers": [],
    "error": "",
}

if status["onnxruntime_installed"]:
    try:
        import onnxruntime as ort
        status["onnx_providers"] = list(ort.get_available_providers())
    except Exception as exc:
        status["onnx_providers"] = [f"error: {exc}"]

try:
    import torch

    status["torch_installed"] = True
    status["torch_version"] = str(torch.__version__)
    status["cuda_available"] = bool(torch.cuda.is_available())
    if status["cuda_available"]:
        status["cuda_device"] = str(torch.cuda.get_device_name(0))
        status["backend"] = "CUDA"
    elif "+cpu" in status["torch_version"].lower():
        status["backend"] = "CPU"
    else:
        status["backend"] = "CPU / CUDA unavailable"
except Exception as exc:
    status["error"] = str(exc)

print(json.dumps(status))
'''


def installer_command(project_root: Path, backend: str) -> tuple[str, list[str]]:
    script = setup_script(project_root, backend)
    return (
        "cmd.exe",
        [
            "/c",
            "start",
            "SkyGuard AI Installer",
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-NoExit",
            "-File",
            str(script),
        ],
    )
