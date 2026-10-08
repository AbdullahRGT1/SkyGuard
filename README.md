# SkyGuard

Modern operator/streamer desktop system for low-latency LAN video control.

The streamer app always starts in `READY_WAITING`. It does not open the camera, encode frames, or transmit video until an authenticated operator sends `START_STREAM`.

## Quick Start

Automatic setup on Windows:

```powershell
cd path\to\skyguard
.\setup_project.ps1
```

If PowerShell blocks the script on a new machine:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Manual setup:

```powershell
cd path\to\skyguard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run the apps:

```powershell
.\.venv\Scripts\python.exe run_streamer.py
.\.venv\Scripts\python.exe run_operator.py
```

## Optional AI and Smart Alerts Setup

The base streamer does not install heavy AI libraries by default. Install the AI layer only on machines that need operator-side YOLO violation detection or Smart Alerts face grouping.

AI runs only on the operator PC. The streamer always sends raw camera frames; it does not load YOLO, Torch, InsightFace, ONNX Runtime, or CUDA libraries.

The operator Settings page includes an `AI Environment` panel that checks the current Python environment without importing Torch in the GUI process. It shows:

- Python executable in use.
- PyTorch version.
- Current backend: CPU, CUDA, or not installed.
- CUDA availability and GPU name when available.
- Whether `ultralytics`, `cvzone`, `insightface`, and `onnxruntime` are installed.
- ONNX Runtime providers, such as `CPUExecutionProvider` or `CUDAExecutionProvider`.

Operator settings are stored in:

```text
%APPDATA%\SkyGuard\operator_settings.json
```

If an older `%APPDATA%\SIMPLE_STREAM\operator_settings.json` file exists, SkyGuard can read it as a migration fallback and will save future changes under the new SkyGuard folder.

For machines without an NVIDIA GPU, install the CPU AI environment:

```powershell
cd path\to\skyguard
.\setup_ai_cpu.ps1
```

For machines with an NVIDIA GPU/CUDA, install the CUDA AI environment:

```powershell
cd path\to\skyguard
.\setup_ai_cuda.ps1
```

You can also launch the same installers from the operator app:

1. Open `Settings`.
2. Find `AI Environment`.
3. Click `Install CPU AI` or `Install CUDA AI`.
4. Confirm the warning.
5. A separate PowerShell installer window opens.
6. Close the operator app and any Python terminals if the installer asks.
7. Restart the operator app after installation completes.

CPU and CUDA PyTorch builds cannot both be installed in the same `.venv`. The setup scripts uninstall `torch`, `torchvision`, and `torchaudio` before installing the requested backend.

The current CUDA installer installs PyTorch from:

```text
https://download.pytorch.org/whl/cu128
```

The CPU installer installs PyTorch from:

```text
https://download.pytorch.org/whl/cpu
```

Shared AI packages are installed from `requirements-ai-common.txt`.
Backend-specific ONNX Runtime packages are installed from:

- `requirements-ai-cpu.txt`: installs `onnxruntime`.
- `requirements-ai-cuda.txt`: installs `onnxruntime-gpu`.

The setup scripts uninstall any existing `onnxruntime`/`onnxruntime-gpu` package before installing the selected backend to avoid mixed CPU/GPU runtimes.

AI files live in:

```text
AI_layer/
  improved.py
  yolo/
    light_2.6k.pt
    medium_2.6k.pt
face_recognizer/
  embeddings.py
  clustering.py
  store.py
  n8n_sender.py
  smart_alert_service.py
```

Model files under `AI_layer/yolo/` are local runtime artifacts and are ignored by Git.
Copy or download the required `.pt` files into that folder before enabling AI.

`AI_layer/improved.py` is the reusable version of the earlier live-camera YOLO demo. It no longer opens a local camera at import time. The old local-camera demo entry point is kept in `backup/improved_demo.py`.

### Smart Alerts

Smart Alerts is an operator-side batch alert layer. It does not capture images by itself. It reads violation RAW images after the existing violation capture system saves them under:

```text
Images/
```

For each saved violation image, Smart Alerts:

1. Uses InsightFace (`buffalo_l` by default) to detect real faces and create normalized face embeddings.
2. Stores image metadata, violations, face boxes, confidence, quality, and embeddings in:

   ```text
   face_recognizer/smart_alerts.sqlite3
   ```

3. Clusters pending observations by cosine similarity and violation type.
4. Selects the best 2-5 representative images for the current batch.
5. Sends one JSON payload to the configured n8n webhook.

The n8n payload remains JSON-only. Images are embedded as base64 in the `images` array with `filename`, `path`, `mime_type`, `data_base64`, and `data_url` fields. No multipart upload is used.

InsightFace model selection can be overridden before launching the operator:

```powershell
$env:SKYGUARD_INSIGHTFACE_MODEL="buffalo_s"  # or buffalo_l
```

Use `buffalo_s` on low-end CPUs. Use `buffalo_l` for better accuracy when performance is acceptable.

### AI Verification

After installing CUDA AI, the installer verifies the environment. A successful CUDA setup must show:

```text
Torch: ...+cu128
CUDA available: True
CUDA device: <your NVIDIA GPU>
InsightFace: ...
ONNX Runtime providers: [..., CUDAExecutionProvider, ...]
CUDA AI setup complete.
```

If it shows `Torch: ...+cpu` or `CUDA available: False`, the CUDA setup is not usable. Common causes:

- The operator app or another Python process kept files locked during installation.
- The NVIDIA driver is too old for the selected CUDA wheel.
- The current Python version does not have a compatible CUDA wheel for the selected PyTorch channel.
- `pip` installed a CPU wheel instead of a CUDA wheel.
- `onnxruntime-gpu` is installed but cannot expose `CUDAExecutionProvider`; in that case YOLO may still use CUDA, while InsightFace falls back to CPU.

The CUDA script now fails loudly if `torch.cuda.is_available()` is false or if the installed Torch version contains `+cpu`.

If the installer reports Python is still running from this virtual environment, close the operator app and any terminals using `.venv\Scripts\python.exe`, then press Enter in the installer window.

### AI Installer Troubleshooting

Administrator PowerShell is normally not required because packages are installed into the project `.venv`, not into system Python. Use administrator mode only if Windows security policy blocks script execution or file writes in the project folder.

If pip prints warnings such as:

```text
Failed to remove contents in a temporary directory ...\~orch
```

it usually means a Python process was still using PyTorch files. Close the operator app and any project Python terminals, then run the installer again. The setup scripts now detect running project Python processes and remove leftover `~orch*` directories before installing the selected backend.

If the CUDA installer downloads a wheel with `+cu128`, that is the expected CUDA build. If it downloads or verifies `+cpu`, CUDA was not installed correctly and the script will fail instead of reporting success.

### AI Performance Notes

- Use `light_2.6k.pt` for CPU or low-end GPUs.
- Use `medium_2.6k.pt` only when GPU performance is acceptable.
- Keep `imgsz=320` for low latency.
- Use `Device=auto` unless you specifically need to force CPU or CUDA.
- While the AI model is loading, the operator preview continues showing RAW video instead of blocking the stream.
- Smart Alerts runs in a background worker and uses InsightFace only after a violation image is saved. If YOLO and InsightFace both compete for a low-end GPU, prefer `buffalo_s` or CPU ONNX Runtime for Smart Alerts.

Development default PIN:

```powershell
$env:SKYGUARD_PIN="1234"
```

Optional camera settings on the streamer PC:

```powershell
$env:SKYGUARD_CAMERA_INDEX="0"
$env:SKYGUARD_FRAME_WIDTH="640"
$env:SKYGUARD_FRAME_HEIGHT="360"
$env:SKYGUARD_FPS="60"
$env:SKYGUARD_VIDEO_CODEC="auto"        # auto, mjpeg, or h264
$env:SKYGUARD_H264_BITRATE_KBPS="2500"  # used by Raspberry Pi H.264 streaming
```

Legacy `SIMPLE_STREAM_*` environment variables are still accepted as fallback values so existing local setups do not break immediately, but new configuration should use `SKYGUARD_*`.

On Windows, `auto` resolves to the existing MJPEG/JPEG-over-UDP path. On Raspberry Pi, `auto` uses `rpicam-vid`/`libcamera-vid` H.264 MPEG-TS when available and falls back to MJPEG if the camera tooling is missing or fails to start.

Use a stronger pairing flow before production deployment. The current starter uses challenge-response auth so the PIN is not sent over the control channel as plain text.

## Connecting From Another PC

The streamer listens on `0.0.0.0:8765`, which means "accept connections on all network interfaces." Do not type `0.0.0.0` in the operator app. On the operator PC, use the Streamer PC LAN address shown in the streamer window, for example:

```text
192.168.1.20
192.168.1.20:8765
ws://192.168.1.20:8765
10.0.0.15
```

If another PC cannot connect, allow Python or the packaged streamer app through Windows Defender Firewall for private networks.

## Apps

- `streamer/`: streamer PC application. Starts a WebSocket control server and waits in ready mode.
- `operator/`: operator PC application. Connects by IP and PIN, then sends `START_STREAM` / `STOP_STREAM`.
- `shared/`: shared state, protocol messages, config, and security helpers.

## Current Project Files

```text
SkyGuard/
  run_streamer.py
  run_operator.py
  setup_project.ps1
  setup_ai_cpu.ps1
  setup_ai_cuda.ps1
  requirements.txt
  requirements-ai-common.txt
  requirements-ai-cpu.txt
  requirements-ai-cuda.txt
  AI_layer/
    improved.py
    yolo/
  shared/
    config.py
    constants.py
    messages.py
    network.py
    security.py
    settings.py
    state.py
    ui_theme.py
    ui_tokens.py
    ui_widgets.py
    video_packets.py
  streamer/
    app.py
    main_window.py
    control_server.py
    state_machine.py
    services/
      stream_service.py
  operator/
    ai_environment.py
    ai_processor.py
    app.py
    main_window.py
    control_client.py
    settings_panel.py
    settings_store.py
    video_receiver.py
    violation_capture.py
  face_recognizer/
    embeddings.py
    clustering.py
    store.py
    n8n_sender.py
    smart_alert_service.py
    smart_alerts.sqlite3
  Images/
```

## Current Implementation Stage

This is a project starter:

- PySide6 + QFluentWidgets UI shell
- Central design-token theme system with custom light/dark palettes
- Opaque themed panels with restrained hover overlays and accent borders
- Control channel scaffolding over WebSocket
- Authenticated start/stop command flow
- Streamer state machine
- OpenCV camera capture with a separate UDP JPEG video channel for the current MVP
- Operator Settings page for AI environment, AI detection, and video settings
- Optional operator-side YOLO processing with RAW fallback when AI dependencies are missing
- Optional violation RAW image capture into `Images/`
- Optional Smart Alerts batching with InsightFace face embeddings, SQLite metadata, cosine clustering, and JSON/base64 n8n webhook delivery
- Scrollable operator pages so Settings controls do not collapse on smaller windows
- Fullscreen operator preview that mirrors the latest frame, stream settings, RAW/AI status, AI state, and alert count
- AI setup scripts that switch between CPU and CUDA PyTorch builds safely
- Operator Settings page is lazy-loaded and the AI environment check runs only on demand, improving startup and navigation smoothness without changing the visual design

Next implementation step: replace the MVP JPEG-over-UDP video path with GStreamer RTP/H.264 or WebRTC.

For video preview between two PCs, Windows Defender Firewall must allow inbound UDP `5004` on the operator PC and inbound TCP `8765` on the streamer PC.

## UI Theme System

The desktop UI uses QFluentWidgets plus a small local design-token layer:

- `shared/ui_tokens.py`: light/dark color palettes, semantic badge colors, borders, surfaces, preview colors, scrollbar colors, and hover colors.
- `shared/ui_theme.py`: central `ThemeManager`; applies `Theme.AUTO`, sets the QFluentWidgets theme color, builds shared QSS, and refreshes registered widgets.
- `shared/ui_widgets.py`: reusable themed widgets such as `AcrylicGlowFrame` and `ThemedStatusBadge`.

Current light palette:

- Main background: `#F0F8FF`
- Primary action: `#2196F3`
- Borders/dividers: `#D3D3D3`
- Secondary text: `#757575`

Current dark palette:

- Main background: `#0B1220`
- Card/surface: `#122033`
- Borders/dividers: `rgba(144, 202, 249, 0.14)`
- Primary highlight: `#90CAF9`
- Primary text: `#D6E2F0`
- Secondary text: `#93A4B7`

Panels in the operator and streamer apps use custom-painted opaque card surfaces instead of hard-coded per-window `QFrame` styles. The window and page backgrounds stay solid for stability and readability. Hovering a panel applies a quiet transparent accent overlay and a slightly stronger blue border.

The operator Preview page includes a stream-info badge and a `Full Screen` action. The fullscreen preview is a frameless top-level window using the same aspect-ratio renderer as the embedded preview, and it can be closed with `Esc`, `F11`, or the `Exit` button.

