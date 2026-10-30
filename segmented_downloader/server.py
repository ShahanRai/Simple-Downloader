"""
Background Local HTTP API Server for Browser Extension Integration.
Provides a REST API on 127.0.0.1:9653 with CORS support so Chrome, Edge,
Brave, and Firefox extensions can detect IDM and route downloads instantly.
"""

import http.server
import json
import threading
import urllib.parse
from typing import Optional, Callable

from .queue_manager import QueueManager


DEFAULT_SERVER_PORT = 9653


class IDMExtensionHandler(http.server.BaseHTTPRequestHandler):
    """
    HTTP Request Handler serving browser extensions and native bridges.
    """
    def log_message(self, format, *args):
        # Silence default console logging
        pass

    def _send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Content-Type", "application/json; charset=utf-8")

    def do_OPTIONS(self):
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path in ("", "/ping", "/status"):
            qm = QueueManager.get_instance()
            resp = {
                "app": "IDM Modern Downloader",
                "version": "2.0.0",
                "status": "online",
                "active_tasks": len(qm.downloaders),
                "total_tasks": len(qm.tasks),
                "speed_bps": qm.get_active_speed()
            }
            self.send_response(200)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path == "/tasks":
            qm = QueueManager.get_instance()
            tasks_data = [t.to_dict() for t in qm.get_all_tasks()]
            self.send_response(200)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"tasks": tasks_data}).encode("utf-8"))

        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not Found"}).encode("utf-8"))

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"

        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/download":
            url = payload.get("url")
            if not url:
                self.send_response(400)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Missing URL"}).encode("utf-8"))
                return

            filename = payload.get("filename")
            auto_start = payload.get("auto_start", True)
            connections = int(payload.get("connections", 8))
            speed_limit = float(payload.get("speed_limit", 0))

            # Notify GUI listener if registered, otherwise direct queue
            qm = QueueManager.get_instance()
            if hasattr(self.server, "on_new_download_callback") and self.server.on_new_download_callback:
                # Callback might prompt user in GUI or add task
                self.server.on_new_download_callback(payload)
                self.send_response(200)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "prompted",
                    "url": url,
                    "filename": filename
                }).encode("utf-8"))
            else:
                task = qm.add_task(
                    url=url,
                    custom_filename=filename,
                    connections=connections,
                    speed_limit_kb=speed_limit,
                    auto_start=auto_start
                )
                self.send_response(200)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "success",
                    "task_id": task.id,
                    "filename": task.filename,
                    "file_size": task.file_size
                }).encode("utf-8"))

        elif path.startswith("/task/"):
            # /task/<id>/pause or /task/<id>/resume or /task/<id>/cancel
            parts = path.split("/")
            if len(parts) >= 4:
                task_id = parts[2]
                action = parts[3]
                qm = QueueManager.get_instance()
                if action == "pause":
                    qm.pause_task(task_id)
                elif action == "resume":
                    qm.resume_task(task_id)
                elif action == "cancel":
                    qm.cancel_task(task_id)

                self.send_response(200)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
                return

            self.send_response(400)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Bad task path"}).encode("utf-8"))
        else:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not Found"}).encode("utf-8"))


class IDMAPIServer:
    """
    Manages lifecycle of local background HTTP server.
    """
    def __init__(self, port: int = DEFAULT_SERVER_PORT, on_new_download: Optional[Callable[[dict], None]] = None):
        self.port = port
        self.on_new_download = on_new_download
        self._server: Optional[http.server.ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        try:
            self._server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), IDMExtensionHandler)
            self._server.on_new_download_callback = self.on_new_download
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            print(f"[IDM Server] Running on http://127.0.0.1:{self.port} (Extension API active)")
        except Exception as e:
            print(f"[IDM Server] Could not bind to port {self.port}: {e}")

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

