"""Small booth-facing facade over the VTube Studio API client."""


class VTSController:
    def __init__(self, client):
        self.client = client

    def connect(self):
        self.client.connect()
        return self.status()

    def status(self):
        state = self.client.get_api_state()
        model = self.client.get_current_model()
        return {
            "connected": bool(state.get("active", True)),
            "model_loaded": bool(model.get("modelLoaded", False)),
            "model_name": model.get("modelName", ""),
            "model_id": model.get("modelID", ""),
        }

    def hotkeys(self):
        return self.client.get_hotkeys().get("availableHotkeys", [])

    def trigger(self, hotkey_id):
        if not hotkey_id:
            raise ValueError("热键 ID 不能为空")
        return self.client.trigger_hotkey(hotkey_id)

    def close(self):
        self.client.close()
