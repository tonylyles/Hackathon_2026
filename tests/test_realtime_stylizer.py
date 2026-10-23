import unittest

import numpy as np
import torch

from app.core.stylizer_anime import AnimeStylizer


class IdentityModel(torch.nn.Module):
    def forward(self, tensor):
        return tensor


class RealtimeStylizerTests(unittest.TestCase):
    def make_stylizer(self):
        stylizer = AnimeStylizer.__new__(AnimeStylizer)
        stylizer.device = torch.device("cpu")
        stylizer.half = False
        stylizer.size = 256
        stylizer._in = torch.empty((1, 3, 256, 256), dtype=torch.float32)
        stylizer.model = IdentityModel()
        return stylizer

    def test_preserves_camera_bgr_colors_and_frame_dimensions(self):
        stylizer = self.make_stylizer()
        frame = np.empty((90, 160, 3), dtype=np.uint8)
        frame[:] = (20, 70, 220)

        output = stylizer(frame)

        self.assertEqual(output.shape, frame.shape)
        means = output.mean(axis=(0, 1))
        np.testing.assert_allclose(means, (20, 70, 220), atol=2.0)

    def test_new_motion_frame_changes_stylized_output(self):
        stylizer = self.make_stylizer()
        first = np.zeros((90, 160, 3), dtype=np.uint8)
        second = first.copy()
        second[20:70, 60:110] = (30, 180, 240)

        first_output = stylizer(first)
        second_output = stylizer(second)

        self.assertEqual(first_output.shape, second_output.shape)
        self.assertGreater(np.abs(first_output.astype(np.int16) - second_output).mean(), 1.0)


if __name__ == "__main__":
    unittest.main()
