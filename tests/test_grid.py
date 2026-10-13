from __future__ import annotations

import io
import time
import unittest

from helpers import make_grid_image

import gridcrop_core as core
from PIL import Image


class UniformGridTest(unittest.TestCase):
    def test_two_by_two_covers_image(self) -> None:
        rects = core.uniform_grid(100, 60, 2, 2)
        self.assertEqual(rects, [(0, 0, 50, 30), (50, 0, 100, 30), (0, 30, 50, 60), (50, 30, 100, 60)])

    def test_padding(self) -> None:
        rects = core.uniform_grid(110, 110, 2, 2, padding=10)
        self.assertEqual(rects[0], (10, 10, 50, 50))  # (110 - 여백 30) / 2 = 40
        self.assertEqual(rects[3], (60, 60, 100, 100))

    def test_odd_sizes_stay_inside(self) -> None:
        for w, h in [(7, 7), (101, 99), (1000, 3)]:
            rects = core.uniform_grid(w, h, 3, 3)
            self.assertEqual(len(rects), 9)
            for l, t, r, b in rects:
                self.assertTrue(0 <= l < r <= w and 0 <= t < b <= h)

    def test_errors_are_korean(self) -> None:
        with self.assertRaisesRegex(ValueError, "행과 열"):
            core.uniform_grid(100, 100, 0, 2)
        with self.assertRaisesRegex(ValueError, "여백"):
            core.uniform_grid(100, 100, 2, 2, padding=40)
        with self.assertRaisesRegex(ValueError, "1픽셀"):
            core.uniform_grid(5, 5, 9, 1)


class FindAxisSpansTest(unittest.TestCase):
    def test_finds_gutter_off_center(self) -> None:
        stds = [30.0] * 100
        for i in range(55, 60):
            stds[i] = 0.0
        spans, found = core.find_axis_spans(stds, 2)
        self.assertEqual(found, 1)
        self.assertEqual(spans, [(0, 55), (60, 100)])

    def test_trims_outer_border(self) -> None:
        stds = [0.0] * 5 + [30.0] * 90 + [0.0] * 5
        spans, found = core.find_axis_spans(stds, 1)
        self.assertEqual(spans, [(5, 95)])
        self.assertEqual(found, 0)

    def test_no_gutter_falls_back_to_even_cut(self) -> None:
        spans, found = core.find_axis_spans([30.0] * 90, 3)
        self.assertEqual(found, 0)
        self.assertEqual(spans, [(0, 30), (30, 60), (60, 90)])

    def test_wide_flat_band_is_not_a_gutter(self) -> None:
        stds = [30.0] * 100
        for i in range(30, 70):  # 칸 크기의 80% — 배경으로 본다
            stds[i] = 0.0
        spans, found = core.find_axis_spans(stds, 2)
        self.assertEqual(found, 0)
        self.assertEqual(spans, [(0, 50), (50, 100)])

    def test_all_flat_image(self) -> None:
        spans, found = core.find_axis_spans([0.0] * 40, 2)
        self.assertEqual(found, 0)
        self.assertEqual(spans, [(0, 20), (20, 40)])


class SplitGridAutoTest(unittest.TestCase):
    def assertRectsClose(self, got, expected, tolerance=0) -> None:
        self.assertEqual(len(got), len(expected))
        for g, e in zip(got, expected):
            for a, b in zip(g, e):
                self.assertLessEqual(abs(a - b), tolerance, f"{got} != {expected}")

    def test_2x2_with_white_gutters_uneven_cells(self) -> None:
        image, expected = make_grid_image([480, 520], [300, 340], gutter=24, border=16)
        split = core.split_grid_auto(image, 2, 2)
        self.assertEqual(split.gutters_found, 2)
        self.assertRectsClose(split.rects, expected)

    def test_3x3_with_dark_gutters(self) -> None:
        image, expected = make_grid_image([300, 310, 290], [250, 260, 240], gutter=12, border=0, gutter_color=10)
        split = core.split_grid_auto(image, 3, 3)
        self.assertEqual(split.gutters_found, 4)
        self.assertRectsClose(split.rects, expected)

    def test_jpeg_noise_still_finds_gutters(self) -> None:
        image, expected = make_grid_image([400, 400, 400], [400, 400, 400], gutter=10, border=8)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        reloaded = Image.open(io.BytesIO(buffer.getvalue()))
        split = core.split_grid_auto(reloaded, 3, 3)
        self.assertEqual(split.gutters_found, 4)
        self.assertRectsClose(split.rects, expected, tolerance=2)

    def test_no_gutter_is_even_split(self) -> None:
        image = Image.effect_noise((600, 400), 60)
        split = core.split_grid_auto(image, 2, 2)
        self.assertEqual(split.gutters_found, 0)
        self.assertEqual(split.rects, core.uniform_grid(600, 400, 2, 2))
        self.assertIn("같은 간격", core.describe_grid_split(split))

    def test_detection_off(self) -> None:
        image, _ = make_grid_image([200, 200], [200, 200], gutter=20, border=0)
        split = core.split_grid_auto(image, 2, 2, detect_gutters=False)
        self.assertEqual(split.rects, core.uniform_grid(image.width, image.height, 2, 2))

    def test_large_image_is_downscaled_and_mapped_back(self) -> None:
        image, expected = make_grid_image([1700, 1700], [1600, 1600], gutter=40, border=0)
        started = time.perf_counter()
        split = core.split_grid_auto(image, 2, 2)
        elapsed = time.perf_counter() - started
        self.assertEqual(split.gutters_found, 2)
        self.assertRectsClose(split.rects, expected, tolerance=3)
        self.assertLess(elapsed, 10.0)

    def test_tiny_image(self) -> None:
        split = core.split_grid_auto(Image.new("L", (3, 3)), 3, 3)
        self.assertEqual(len(split.rects), 9)

    def test_describe_messages(self) -> None:
        full = core.GridSplit([], 2, 2, 2, 2)
        part = core.GridSplit([], 3, 3, 1, 4)
        self.assertIn("모두 찾아", core.describe_grid_split(full))
        self.assertIn("4곳 중 1곳", core.describe_grid_split(part))


class RectHelpersTest(unittest.TestCase):
    def test_clamp_and_dedupe(self) -> None:
        rects = [(-10, -10, 50, 50), (50, 50, -10, -10), (0, 0, 2, 2), (90, 90, 200, 200)]
        self.assertEqual(core.clamp_rects(rects, 100, 100), [(0, 0, 50, 50), (90, 90, 100, 100)])

    def test_scale(self) -> None:
        self.assertEqual(core.scale_rects([(10, 10, 20, 20)], (100, 100), (200, 50)), [(20, 5, 40, 10)])
        self.assertEqual(core.scale_rects([(1, 2, 3, 4)], (0, 0), (10, 10)), [(1, 2, 3, 4)])


if __name__ == "__main__":
    unittest.main()
