"""Small embedded HTTP server for booth QR-code downloads."""
import socket
import threading
import time

import uvicorn


class ShareServer:
    def __init__(self, port=8000):
        self.port = port
        self.server = None
        self.thread = None
        self.ready = threading.Event()

    def __enter__(self):
        from app.server.api import app

        config = uvicorn.Config(app, host="0.0.0.0", port=self.port, log_level="error")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.server.started:
                self.ready.set()
                return self
            if not self.thread.is_alive():
                break
            time.sleep(0.05)
        raise RuntimeError(f"分享服务无法在端口 {self.port} 启动")

    def __exit__(self, exc_type, exc, tb):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=3)

    @property
    def is_lan_available(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0] != "127.0.0.1"
            finally:
                sock.close()
        except OSError:
            return False
