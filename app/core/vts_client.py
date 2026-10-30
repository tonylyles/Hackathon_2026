"""Minimal synchronous client for the VTube Studio public WebSocket API."""
import json
import os
import threading
import uuid
from pathlib import Path


class VTSAPIError(RuntimeError):
    """An error response returned by VTube Studio."""

    def __init__(self, error_id, message):
        self.error_id = error_id
        self.message = message
        super().__init__(f"VTube Studio API error {error_id}: {message}")


class VTSClient:
    API_NAME = "VTubeStudioPublicAPI"
    API_VERSION = "1.0"

    def __init__(self, url="ws://localhost:8001", plugin_name="Naiwa Booth",
                 plugin_developer="Naiwa - PhotoBooth", token_path=None,
                 timeout=8, socket_factory=None, connector=None):
        self.url = url
        self.plugin_name = plugin_name
        self.plugin_developer = plugin_developer
        self.token_path = Path(token_path or self.default_token_path())
        self.timeout = timeout
        self.socket_factory = socket_factory
        self.connector = connector
        self.socket = None
        self._lock = threading.RLock()

    @staticmethod
    def default_token_path():
        base = Path(os.environ.get("APPDATA", Path.home()))
        return base / "AIPhotoBooth" / "vts_token.txt"

    def connect(self):
        with self._lock:
            if self.socket is not None:
                return
            self.socket = self._connect_socket()
            if hasattr(self.socket, "settimeout"):
                self.socket.settimeout(self.timeout)
            try:
                self.authenticate()
            except Exception:
                self.close()
                raise

    def _connect_socket(self):
        if self.socket_factory:
            return self.socket_factory(self.url, timeout=self.timeout)
        if self.connector:
            return self.connector(self.url, self.timeout)
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("缺少 websocket-client，请安装项目依赖") from exc
        return websocket.create_connection(self.url, timeout=self.timeout)


    def _send(self, message_type, data=None):
        if self.socket is None:
            raise RuntimeError("VTube Studio API 尚未连接")
        request_id = uuid.uuid4().hex
        request = {
            "apiName": self.API_NAME,
            "apiVersion": self.API_VERSION,
            "requestID": request_id,
            "messageType": message_type,
        }
        if data is not None:
            request["data"] = data
        try:
            self.socket.send(json.dumps(request, ensure_ascii=False))
            while True:
                response = json.loads(self.socket.recv())
                if response.get("requestID") != request_id:
                    continue
                if response.get("messageType") == "APIError":
                    error = response.get("data", {})
                    raise VTSAPIError(error.get("errorID", "unknown"),
                                      error.get("message", "Unknown error"))
                return response
        except VTSAPIError:
            raise
        except Exception:
            self.close()
            raise

    def authenticate(self):
        token = self._read_token()
        if token:
            response = self._send("AuthenticationRequest", {
                "pluginName": self.plugin_name,
                "pluginDeveloper": self.plugin_developer,
                "authenticationToken": token,
            })
            if response.get("data", {}).get("authenticated"):
                return
            self._forget_token()

        response = self._send("AuthenticationTokenRequest", {
            "pluginName": self.plugin_name,
            "pluginDeveloper": self.plugin_developer,
        })
        token = response.get("data", {}).get("authenticationToken")
        if not token:
            raise RuntimeError("VTube Studio 未返回插件授权令牌")
        self._save_token(token)
        response = self._send("AuthenticationRequest", {
            "pluginName": self.plugin_name,
            "pluginDeveloper": self.plugin_developer,
            "authenticationToken": token,
        })
        if not response.get("data", {}).get("authenticated"):
            self._forget_token()
            raise RuntimeError("VTube Studio 插件授权未完成")

    def _read_token(self):
        try:
            return self.token_path.read_text(encoding="utf-8").strip() or None
        except FileNotFoundError:
            return None

    def _save_token(self, token):
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(token, encoding="utf-8")
        if os.name != "nt":
            self.token_path.chmod(0o600)

    def _forget_token(self):
        try:
            self.token_path.unlink()
        except FileNotFoundError:
            pass

    def request(self, message_type, data=None):
        with self._lock:
            self.connect()
            try:
                return self._send(message_type, data).get("data", {})
            except VTSAPIError:
                raise
            except Exception:
                self.close()
                self.connect()
                return self._send(message_type, data).get("data", {})

    def get_api_state(self):
        return self.request("APIStateRequest")

    def get_current_model(self):
        return self.request("CurrentModelRequest")

    def get_available_models(self):
        return self.request("AvailableModelsRequest")

    def load_model(self, model_id):
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("模型 ID 不能为空")
        return self.request("ModelLoadRequest", {"modelID": model_id})

    def get_hotkeys(self):
        model = self.get_current_model()
        model_id = model.get("modelID", "")
        return self.request("HotkeysInCurrentModelRequest", {"modelID": model_id})

    def trigger_hotkey(self, hotkey_id):
        return self.request("HotkeyTriggerRequest", {"hotkeyID": hotkey_id})

    def close(self):
        with self._lock:
            if self.socket is not None:
                try:
                    self.socket.close()
                finally:
                    self.socket = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_exc):
        self.close()
