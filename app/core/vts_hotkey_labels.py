"""Local display-name overrides for VTube Studio hotkeys; IDs never change."""
import json
import os
import tempfile
import threading
from pathlib import Path


class VTSHotkeyLabels:
    MAX_LENGTH = 24

    def __init__(self, path=None):
        base = Path(os.environ.get("APPDATA", Path.home())) / "AIPhotoBooth"
        self.path = Path(path) if path is not None else base / "vts_hotkey_labels.json"
        self._lock = threading.RLock()
        self._models = self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return {}
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("models"), dict):
            return {}
        models = {}
        for model_id, labels in data["models"].items():
            if not isinstance(model_id, str) or not model_id or not isinstance(labels, dict):
                continue
            valid = {hotkey_id: label for hotkey_id, label in labels.items()
                     if isinstance(hotkey_id, str) and hotkey_id
                     and isinstance(label, str) and label.strip() == label
                     and 0 < len(label) <= self.MAX_LENGTH}
            if valid:
                models[model_id] = valid
        return models

    def label_for(self, model_id, hotkey_id, fallback):
        with self._lock:
            return self._models.get(model_id, {}).get(hotkey_id) or fallback or "动作"

    def set_label(self, model_id, hotkey_id, label):
        """Persist first; only publish the new in-memory mapping on success."""
        if not isinstance(model_id, str) or not model_id or not isinstance(hotkey_id, str) or not hotkey_id:
            raise ValueError("model_id and hotkey_id are required")
        if not isinstance(label, str):
            raise ValueError("display name must be text")
        label = label.strip()
        if len(label) > self.MAX_LENGTH:
            raise ValueError(f"动作名称最多 {self.MAX_LENGTH} 个字符")
        with self._lock:
            models = {key: dict(value) for key, value in self._models.items()}
            if label:
                models.setdefault(model_id, {})[hotkey_id] = label
            elif model_id in models:
                models[model_id].pop(hotkey_id, None)
                if not models[model_id]:
                    del models[model_id]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                                 prefix=".vts_hotkey_labels_", suffix=".tmp",
                                                 delete=False) as temporary:
                    temp_path = Path(temporary.name)
                    json.dump({"version": 1, "models": models}, temporary, ensure_ascii=False, indent=2)
                    temporary.write("\n")
                os.replace(temp_path, self.path)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
            self._models = models
