from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from urllib import request


class N8nSender:
    def send(self, webhook_url: str, payload: dict, image_paths: list[Path]) -> None:
        if not webhook_url:
            raise ValueError("n8n webhook URL is empty.")

        body_payload = dict(payload)
        body_payload["images"] = [
            self._image_payload(index, image_path)
            for index, image_path in enumerate(image_paths, start=1)
            if image_path.exists()
        ]
        body_payload["image_count"] = len(body_payload["images"])
        body = json.dumps(body_payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            webhook_url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "SkyGuard-SmartAlerts/1.0",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=30) as response:
            if response.status >= 400:
                raise RuntimeError(f"n8n webhook returned HTTP {response.status}.")

    @staticmethod
    def _image_payload(index: int, path: Path) -> dict:
        mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "id": f"image_{index}",
            "filename": path.name,
            "path": str(path),
            "mime_type": mime_type,
            "data_base64": encoded,
            "data_url": f"data:{mime_type};base64,{encoded}",
        }
