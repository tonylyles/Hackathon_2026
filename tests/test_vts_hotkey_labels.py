"""Persistence and isolation of VTS hotkey display names."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.vts_hotkey_labels import VTSHotkeyLabels


class VTSHotkeyLabelsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "labels.json"

    def test_default_path_and_missing_file(self):
        with patch.dict("os.environ", {"APPDATA": self.directory.name}):
            labels = VTSHotkeyLabels()
        self.assertEqual(labels.path, Path(self.directory.name) / "AIPhotoBooth" / "vts_hotkey_labels.json")
        self.assertEqual(labels.label_for("frog", "wave", "挥手"), "挥手")
        self.assertEqual(labels.label_for("frog", "wave", ""), "动作")

    def test_chinese_names_persist_per_model_and_hotkey(self):
        labels = VTSHotkeyLabels(self.path)
        labels.set_label("frog", "wave", "  奶蛙挥手  ")
        labels.set_label("cow", "wave", "牛来挥手")
        self.assertIn("奶蛙挥手", self.path.read_text(encoding="utf-8"))
        loaded = VTSHotkeyLabels(self.path)
        self.assertEqual(loaded.label_for("frog", "wave", "旧名"), "奶蛙挥手")
        self.assertEqual(loaded.label_for("cow", "wave", "旧名"), "牛来挥手")
        self.assertEqual(loaded.label_for("frog", "other", "原名"), "原名")
        loaded.set_label("frog", "wave", "  ")
        self.assertEqual(VTSHotkeyLabels(self.path).label_for("frog", "wave", "原名"), "原名")
        self.assertEqual(VTSHotkeyLabels(self.path).label_for("cow", "wave", "旧名"), "牛来挥手")

    def test_invalid_config_is_ignored(self):
        for data in ("{broken", "[]", '{"version": 2, "models": {}}',
                     '{"version": 1, "models": {"frog": {"wave": 9}}}'):
            with self.subTest(data=data):
                self.path.write_text(data, encoding="utf-8")
                self.assertEqual(VTSHotkeyLabels(self.path).label_for("frog", "wave", "原名"), "原名")

    def test_invalid_input_and_write_failure_do_not_modify_cache(self):
        labels = VTSHotkeyLabels(self.path)
        labels.set_label("frog", "wave", "原覆盖")
        with self.assertRaises(ValueError):
            labels.set_label("frog", "wave", "太" * 25)
        with patch("app.core.vts_hotkey_labels.os.replace", side_effect=OSError("readonly")):
            with self.assertRaises(OSError):
                labels.set_label("frog", "wave", "新覆盖")
        self.assertEqual(labels.label_for("frog", "wave", "原名"), "原覆盖")
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["models"]["frog"]["wave"], "原覆盖")
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
