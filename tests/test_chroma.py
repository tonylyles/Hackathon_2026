"""Synthetic chroma and background checks; no VTS/camera access."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.core.backgrounds import background_label, cover_image
from app.core.chroma import BackgroundCatalog, ChromaRejected, ChromaSettings, blend_scene, compose_avatar


class ChromaTests(unittest.TestCase):
    def setUp(self):
        self.bg = np.full((10, 10, 3), (200, 60, 40), np.uint8)
        self.vts = np.full((10, 10, 3), (0, 255, 0), np.uint8)
        self.vts[2:7, 3:8] = (80, 90, 210)

    def test_composition_preserves_foreground_and_background_and_inputs(self):
        orig_vts, orig_bg = self.vts.copy(), self.bg.copy()
        result, info = compose_avatar(self.vts, self.bg)
        np.testing.assert_array_equal(result[0, 0], self.bg[0, 0])
        np.testing.assert_array_equal(result[3, 4], self.vts[3, 4])
        np.testing.assert_array_equal(self.vts, orig_vts)
        np.testing.assert_array_equal(self.bg, orig_bg)
        self.assertEqual(result.dtype, np.uint8)
        self.assertAlmostEqual(info.foreground_ratio, .25)
        self.assertAlmostEqual(info.keyed_ratio, .75)
        self.assertEqual(info.edge_ratio, 0)

    def test_soft_edge_and_hard_threshold(self):
        self.vts[0, 0] = (70, 120, 70)  # green excess 50: halfway through 40..60
        result, info = compose_avatar(self.vts, self.bg)
        self.assertEqual(info.edge_ratio, .01)
        np.testing.assert_array_equal(result[0, 0], np.rint((self.vts[0, 0].astype(float) + self.bg[0, 0].astype(float)) / 2).astype(np.uint8))
        result, info = compose_avatar(self.vts, self.bg, ChromaSettings(edge=0))
        np.testing.assert_array_equal(result[0, 0], self.bg[0, 0])
        self.assertEqual(info.edge_ratio, 0)

    def test_rejects_empty_green_and_solid_foreground_with_diagnostics(self):
        for frame, expected in ((np.full_like(self.vts, (0, 255, 0)), 0),
                                (np.full_like(self.vts, (50, 50, 220)), 1)):
            with self.assertRaises(ChromaRejected) as caught:
                compose_avatar(frame, self.bg)
            self.assertEqual(caught.exception.diagnostics.foreground_ratio, expected)

    def test_invalid_frames_and_settings(self):
        for bad in (None, np.zeros((0, 1, 3), np.uint8), np.zeros((10, 10), np.uint8),
                    np.zeros((10, 10, 4), np.uint8), np.zeros((10, 10, 3), np.float32)):
            with self.subTest(bad=str(getattr(bad, "shape", None))), self.assertRaises(ValueError):
                compose_avatar(bad, self.bg)
        with self.assertRaises(ValueError):
            compose_avatar(self.vts, np.zeros((20, 20, 3), np.uint8))
        with self.assertRaises(ValueError):
            compose_avatar(self.vts, self.bg, settings=None)
        for kwargs in ({"threshold": float("nan")}, {"edge": -1}, {"min_green": 256},
                       {"min_foreground_ratio": .9, "max_foreground_ratio": .1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                ChromaSettings(**kwargs)

    def test_cover_image_crops_from_center_without_squeezing(self):
        wide = np.zeros((2, 6, 3), np.uint8)
        for x in range(6):
            wide[:, x] = x * 20
        original = wide.copy()
        cropped = cover_image(wide, (2, 2))
        self.assertEqual(cropped.shape, (2, 2, 3))
        np.testing.assert_array_equal(cropped[0, :, 0], [40, 60])
        np.testing.assert_array_equal(wide, original)
        tall = np.transpose(wide, (1, 0, 2))
        cropped_tall = cover_image(tall, (2, 2))
        np.testing.assert_array_equal(cropped_tall[:, 0, 0], [40, 60])

    def test_scene_blending_precedes_chroma_key(self):
        base = np.full((10, 10, 3), (20, 40, 60), np.uint8)
        original_base, original_bg = base.copy(), self.bg.copy()
        for opacity, expected in ((0, base[0, 0]), (1, self.bg[0, 0]),
                                  (.5, np.array([110, 50, 50]))):
            scene = blend_scene(base, self.bg, opacity)
            final, _ = compose_avatar(self.vts, scene)
            np.testing.assert_array_equal(final[0, 0], expected)
            np.testing.assert_array_equal(final[3, 4], self.vts[3, 4])
        np.testing.assert_array_equal(base, original_base)
        np.testing.assert_array_equal(self.bg, original_bg)
        with self.assertRaises(ValueError):
            blend_scene(base, self.bg, 1.1)

    def test_background_labels_and_character_directories(self):
        self.assertEqual(background_label("builtin:aurora"), "极光")
        self.assertEqual(background_label("builtin:sunset"), "落日")
        self.assertEqual(background_label("user:最后的晚餐.jpg"), "最后的晚餐")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frog = root / "奶蛙"
            cow = root / "牛来"
            frog.mkdir()
            cow.mkdir()
            image = np.full((4, 6, 3), (20, 50, 180), np.uint8)
            cv2.imencode(".jpg", image)[1].tofile(frog / "最后的晚餐.jpg")
            cv2.imencode(".jpg", image)[1].tofile(cow / "另一角色.jpg")
            self.assertEqual(BackgroundCatalog(root).items,
                             ("builtin:aurora", "builtin:sunset"))
            catalog = BackgroundCatalog(frog)
            self.assertIn("user:最后的晚餐.jpg", catalog.items)
            self.assertNotIn("user:另一角色.jpg", catalog.items)
            self.assertEqual(catalog.get("user:最后的晚餐.jpg", (12, 8)).shape, (8, 12, 3))

    def test_builtin_backgrounds_and_no_directory(self):
        catalog = BackgroundCatalog()
        self.assertEqual(catalog.items, ("builtin:aurora", "builtin:sunset"))
        for name in catalog.items:
            image = catalog.get(name, (32, 24))
            self.assertEqual(image.shape, (24, 32, 3))
            self.assertEqual(image.dtype, np.uint8)
            self.assertGreater(np.unique(image.reshape(-1, 3), axis=0).shape[0], 2)
            np.testing.assert_array_equal(image, catalog.get(name, (32, 24)))
        self.assertEqual(BackgroundCatalog("missing/not/a/directory").items, catalog.items)
        with self.assertRaises(ValueError):
            catalog.get("builtin:other", (8, 8))
        with self.assertRaises(ValueError):
            catalog.get("builtin:aurora", (0, 8))

    def test_user_directory_unicode_image_and_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            original = np.full((4, 6, 3), (20, 50, 180), np.uint8)
            png = directory / "自有背景.png"
            cv2.imencode(".png", original)[1].tofile(png)
            (directory / "not-an-image.txt").write_text("x", encoding="utf-8")
            (directory / "broken.jpg").write_bytes(b"invalid")
            (directory / "nested").mkdir()
            cv2.imencode(".png", original)[1].tofile(directory / "nested" / "hidden.png")
            catalog = BackgroundCatalog(directory)
            self.assertIn("user:自有背景.png", catalog.items)
            self.assertNotIn("user:hidden.png", catalog.items)
            np.testing.assert_array_equal(catalog.get("user:自有背景.png", (12, 8)),
                                          np.tile(original[0, 0], (8, 12, 1)))
            with self.assertRaises(ValueError):
                catalog.get("user:broken.jpg", (8, 8))
            for name in ("user:../hidden.png", "user:nested/hidden.png", "user:..\\hidden.png", "user:not-an-image.txt"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    catalog.get(name, (8, 8))

    def test_background_cache_size_copy_eviction_and_clear(self):
        catalog = BackgroundCatalog()
        with patch("app.core.backgrounds.load_background", wraps=__import__(
                "app.core.backgrounds", fromlist=["load_background"]).load_background) as load:
            first = catalog.get("builtin:aurora", [12, 8])
            first[:] = 0
            second = catalog.get("builtin:aurora", (12, 8))
            self.assertEqual(load.call_count, 1)
            self.assertTrue(np.any(second))
            catalog.get("builtin:aurora", (8, 12))
            self.assertEqual(load.call_count, 2)
            catalog.clear_cache()
            catalog.get("builtin:aurora", (12, 8))
            self.assertEqual(load.call_count, 3)
            catalog.MAX_CACHE_ITEMS = 1
            catalog.get("builtin:sunset", (12, 8))
            catalog.get("builtin:aurora", (12, 8))
            self.assertEqual(load.call_count, 5)
        self.assertIsNot(catalog.get("builtin:aurora", (12, 8)),
                         BackgroundCatalog().get("builtin:aurora", (12, 8)))

    def test_background_cache_file_change_and_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "scene.png"
            def save(color):
                cv2.imencode(".png", np.full((6, 6, 3), color, np.uint8))[1].tofile(path)
            save((10, 20, 30))
            catalog = BackgroundCatalog(temp)
            original = catalog.get("user:scene.png", (8, 8))
            save((200, 130, 80))
            updated = catalog.get("user:scene.png", (8, 8))
            self.assertFalse(np.array_equal(original, updated))
            path.unlink()
            with self.assertRaises(ValueError):
                catalog.get("user:scene.png", (8, 8))


if __name__ == "__main__":
    unittest.main()
