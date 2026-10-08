# SkyGuard Streamer - Raspberry Pi 5 Edition

This is a standalone, lightweight, terminal-only version of the SkyGuard Streamer designed specifically for Raspberry Pi (Linux ARM64). 

It uses `websockets` for control and low-latency UDP video to the SkyGuard Operator, without the overhead of Qt/PySide6 graphical libraries. On Raspberry Pi, the default `auto` video mode prefers `rpicam-vid`/`libcamera-vid` H.264 MPEG-TS and falls back to the older OpenCV MJPEG path if camera tooling is unavailable.

## Requirements
- Raspberry Pi 4 or 5 running Raspberry Pi OS (64-bit recommended)
- A USB Camera (V4L2 compatible)

## Quick Install

Run the included install script. It will install system dependencies, set up a Python virtual environment, install the required packages, and configure a `systemd` service for automatic startup.

```bash
chmod +x install.sh
./install.sh
```

## Running the Streamer

### Manually
You can run the streamer directly in the terminal to see live logs:

```bash
source .venv/bin/activate
python run.py
```

Press `Ctrl+C` to stop.

### As a Background Service
The installation script creates a systemd service.

**Start the service:**
```bash
sudo systemctl start skyguard-streamer
```

**Stop the service:**
```bash
sudo systemctl stop skyguard-streamer
```

**Check status & logs:**
```bash
sudo systemctl status skyguard-streamer
journalctl -u skyguard-streamer -f
```

## Configuration (Optional)

You can configure the streamer by setting environment variables in your `.bashrc` or in the systemd service file:

- `SKYGUARD_PIN`: The 4-digit PIN for operator authentication (Default: `1234`)
- `SKYGUARD_CAMERA_INDEX`: The camera index to use (Default: `0`)
- `SKYGUARD_CONTROL_PORT`: Port for the WebSocket control server (Default: `8765`)
- `SKYGUARD_VIDEO_PORT`: Port for the UDP video stream (Default: `5004`)
- `SKYGUARD_VIDEO_CODEC`: `auto`, `h264`, or `mjpeg` (Default: `auto`)
- `SKYGUARD_H264_BITRATE_KBPS`: H.264 bitrate when using `rpicam-vid` (Default: `2500`)

Example (run manually with custom PIN):
```bash
SKYGUARD_PIN=9999 python run.py
```

For production Raspberry Pi streaming, keep `SKYGUARD_VIDEO_CODEC=auto` or `h264` and tune bitrate before increasing resolution or FPS. MJPEG is useful as a compatibility fallback, but it costs much more CPU and network bandwidth.
