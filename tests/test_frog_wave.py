import json
import math
import unittest
from pathlib import Path


MODEL_DIR = Path(__file__).resolve().parents[1] / "refs" / "vts-model-reference" / "奶蛙"
WAVE_PATH = MODEL_DIR / "wave.motion3.json"
ARM_IDS = {"Paramyt5", "Paramyt6", "Paramyt7", "Paramyt8"}


class FrogWaveMotionTests(unittest.TestCase):
    def test_motion3_metadata_and_model_parameters_are_consistent(self):
        motion = json.loads(WAVE_PATH.read_text(encoding="utf-8"))
        model = json.loads((MODEL_DIR / "奶蛙.model3.json").read_text(encoding="utf-8"))
        display = json.loads((MODEL_DIR / "奶蛙.cdi3.json").read_text(encoding="utf-8"))
        known_ids = {item["Id"] for item in display["Parameters"]}

        self.assertEqual(motion["Version"], 3)
        self.assertFalse(motion["Meta"]["Loop"])
        self.assertTrue(WAVE_PATH.is_file())
        # The reference copy is intentionally not registered as a hotkey or motion.
        # Registration is deferred until visual testing and rights confirmation.
        self.assertNotIn(WAVE_PATH.name, [ref["File"] for refs in model["FileReferences"]["Motions"].values() for ref in refs])

        curves = motion["Curves"]
        self.assertEqual({curve["Id"] for curve in curves}, ARM_IDS)
        self.assertTrue(all(curve["Target"] == "Parameter" for curve in curves))
        self.assertTrue(all(curve["Id"] in known_ids for curve in curves))
        self.assertEqual(motion["Meta"]["CurveCount"], len(curves))

        total_segments = 0
        total_points = 0
        duration = motion["Meta"]["Duration"]
        for curve in curves:
            data = curve["Segments"]
            # Initial (time, value), followed by (linear marker, time, value).
            self.assertEqual(data[:2], [0, 0])
            self.assertEqual((len(data) - 2) % 3, 0)
            self.assertTrue(all(marker == 0 for marker in data[2::3]))
            segments = (len(data) - 2) // 3
            total_segments += segments
            total_points += segments + 1
            times = [data[0], *data[3::3]]
            values = [data[1], *data[4::3]]
            self.assertTrue(all(math.isfinite(v) for v in data))
            self.assertTrue(all(0 <= t <= duration for t in times))
            self.assertTrue(all(abs(value) <= 10 for value in values))
            self.assertEqual(times, sorted(times))
            self.assertEqual(data[-3:], [0, duration, 0])

        self.assertEqual(motion["Meta"]["TotalSegmentCount"], total_segments)
        self.assertEqual(motion["Meta"]["TotalPointCount"], total_points)

    def test_motion_does_not_modify_reference_model_files(self):
        motion = json.loads(WAVE_PATH.read_text(encoding="utf-8"))
        model = json.loads((MODEL_DIR / "奶蛙.model3.json").read_text(encoding="utf-8"))
        motion_refs = model["FileReferences"]["Motions"]
        self.assertEqual(set(motion_refs), {""})
        self.assertEqual([entry["File"] for entry in motion_refs[""]], ["hahaha.motion3.json"])
        self.assertEqual(motion["Meta"]["CurveCount"], 4)


if __name__ == "__main__":
    unittest.main()
