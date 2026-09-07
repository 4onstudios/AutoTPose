#!/usr/bin/env python3
"""Local bridge for Chrome extension use with Mesh2Motion.

This tiny HTTP server accepts a GLB/GLTF upload, runs the existing Blender-based
AutoTPose pipeline, and returns the generated T-pose output as a downloadable
GLB file.
"""

from __future__ import annotations

import cgi
import io
import json
import os
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLENDER_PATH = os.environ.get("BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
HOST = "127.0.0.1"
PORT = 8765


def run_autotpose(input_path: Path) -> Path:
    output_path = input_path.with_name(f"{input_path.stem}_tpose.glb")
    report_path = input_path.with_name(f"{input_path.stem}_tpose-report.json")

    command = [
        BLENDER_PATH,
        "--background",
        "--python",
        str(REPO_ROOT / "auto_t_pose.py"),
        "--",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
        "--report",
        str(report_path),
        "--auto-rig",
        "--bind-method",
        "DISTANCE",
        "--apply-rest-pose",
    ]

    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(
            "AutoTPose Blender pipeline failed. "
            f"stdout={completed.stdout[-2000:]} stderr={completed.stderr[-2000:]}"
        )

    if not output_path.exists():
        raise RuntimeError(f"Expected output file was not created: {output_path}")

    return output_path


class AutoTPoseBridgeHandler(BaseHTTPRequestHandler):
    server_version = "AutoTPoseBridge/1.0"

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
            return

        self.send_response(404)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_POST(self):
        if not self.path.startswith("/auto-t-pose"):
            self.send_response(404)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return

        try:
            content_type = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in content_type:
                raise ValueError("Expected multipart/form-data upload.")

            length = int(self.headers.get("Content-Length", "0"))
            data = self.rfile.read(length)
            environ = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": str(len(data)),
            }
            form = cgi.FieldStorage(fp=io.BytesIO(data), headers=self.headers, environ=environ)
            file_item = form.getfirst("file")
            file_name = form["file"].filename if "file" in form else "model.glb"

            if file_item is None:
                raise ValueError("No uploaded file was received.")

            with tempfile.TemporaryDirectory(prefix="autotpose-") as temp_dir:
                temp_dir_path = Path(temp_dir)
                input_path = temp_dir_path / Path(file_name).name
                input_path.write_bytes(file_item)

                output_path = run_autotpose(input_path)
                payload = output_path.read_bytes()

                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Disposition", f'attachment; filename="{output_path.name}"')
                self.end_headers()
                self.wfile.write(payload)
        except Exception as exc:
            error_text = str(exc)
            payload = json.dumps({"status": "error", "error": error_text}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(payload)

    def log_message(self, format, *args):
        print(f"[AutoTPose Bridge] {format % args}")


if __name__ == "__main__":
    if not Path(BLENDER_PATH).exists():
        print(f"[AutoTPose Bridge] Blender not found at {BLENDER_PATH}")
        print("Set BLENDER=/path/to/blender before running this script.")
        sys.exit(1)

    print(f"[AutoTPose Bridge] Starting on http://{HOST}:{PORT}")
    print(f"[AutoTPose Bridge] Blender: {BLENDER_PATH}")
    print(f"[AutoTPose Bridge] Repo: {REPO_ROOT}")
    server = ThreadingHTTPServer((HOST, PORT), AutoTPoseBridgeHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AutoTPose Bridge] Stopped.")
    finally:
        server.server_close()
