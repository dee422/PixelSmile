from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests


class ComfyClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188", timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def upload_image(self, image_path: Path, overwrite: bool = True) -> str:
        url = f"{self.base_url}/upload/image"
        with image_path.open("rb") as f:
            files = {"image": (image_path.name, f, "application/octet-stream")}
            data = {"type": "input", "overwrite": "true" if overwrite else "false"}
            resp = requests.post(url, files=files, data=data, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        name = payload.get("name") or payload.get("filename")
        if not name:
            raise RuntimeError(f"Unexpected upload response: {payload}")
        return str(name)

    def queue_prompt(self, prompt: Dict[str, Any], client_id: str = "pixelsmile-ui") -> str:
        url = f"{self.base_url}/prompt"
        body = {"prompt": prompt, "client_id": client_id}
        resp = requests.post(url, json=body, timeout=self.timeout)
        resp.raise_for_status()
        payload = resp.json()
        prompt_id = payload.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"Unexpected prompt response: {payload}")
        return str(prompt_id)

    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/history/{prompt_id}"
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def wait_until_done(
        self, prompt_id: str, max_wait_sec: int = 600, poll_sec: float = 1.2
    ) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < max_wait_sec:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                return history[prompt_id]
            time.sleep(poll_sec)
        raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")

    def fetch_image_bytes(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        url = f"{self.base_url}/view"
        params = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        resp = requests.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def get_first_output_image(meta: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    outputs = meta.get("outputs", {})
    for node_out in outputs.values():
        images = node_out.get("images", [])
        if images:
            item = images[0]
            return (
                str(item.get("filename", "")),
                str(item.get("subfolder", "")),
                str(item.get("type", "output")),
            )
    return None
