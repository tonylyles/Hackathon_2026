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

    def models(self):
        response = self.client.get_available_models()
        return [{"model_id": item["modelID"],
                 "model_name": item.get("modelName") or item.get("vtsModelName") or "未命名模型",
                 "model_loaded": bool(item.get("modelLoaded"))}
                for item in response.get("availableModels", []) if item.get("modelID")]

    def load_model(self, model_id):
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("模型 ID 不能为空")
        return self.client.load_model(model_id)

    def hotkeys(self):
        return self.client.get_hotkeys().get("availableHotkeys", [])

    def trigger(self, hotkey_id):
        if not hotkey_id:
            raise ValueError("热键 ID 不能为空")
        return self.client.trigger_hotkey(hotkey_id)

    def close(self):
        self.client.close()
