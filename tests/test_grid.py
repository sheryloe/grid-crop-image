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


class EdgeDetectionTest(unittest.TestCase):
    """경계선 세기로 찾는 경우: 붙은 칸, 무늬 여백, 한쪽만 확인된 여백 고치기."""

    def test_touching_uneven_cells(self) -> None:
        # 여백 없이 붙은 크기가 다른 네 칸(칸마다 다른 그라데이션 + 잔잡음)
        colors = [((200, 60, 40), (90, 30, 20)), ((40, 120, 200), (20, 60, 90)),
                  ((60, 180, 80), (220, 230, 120)), ((240, 200, 210), (120, 80, 160))]
        widths, heights = [300, 420], [380, 260]
        image = Image.new("RGB", (sum(widths), sum(heights)))
        expected = []
        index = 0
        for r, h in enumerate(heights):
            for c, w in enumerate(widths):
                top, bottom = colors[index]
                strip = Image.new("RGB", (1, 2))
                strip.putpixel((0, 0), top)
                strip.putpixel((0, 1), bottom)
                cell = strip.resize((w, h), Image.Resampling.BILINEAR)
                noise = Image.effect_noise((w, h), 8).convert("RGB")
                cell = Image.blend(cell, noise, 0.1)
                x, y = sum(widths[:c]), sum(heights[:r])
                image.paste(cell, (x, y))
                expected.append((x, y, x + w, y + h))
                index += 1
        split = core.split_grid_auto(image, 2, 2)
        self.assertEqual(split.gutters_found, 2)
        self.assertEqual(split.rects, expected)

    def test_edge_band_pairs_two_edges_with_flat_inside(self) -> None:
        edges = [1.0] * 200
        edges[90], edges[104] = 60.0, 20.0
        self.assertEqual(core._edge_band(edges, 50, 150, 4.0, 40), (90, 104, core.GAP_BOTH))
        edges[94:100] = [40.0] * 6  # 사이가 고르지 않으면 여백이 아니다
        self.assertEqual(core._edge_band(edges, 50, 150, 4.0, 40)[2], core.GAP_TOUCH)

    def test_edge_profile_peaks_at_boundary_not_inside_gradient(self) -> None:
        # 왼쪽 절반은 위아래 그라데이션, 오른쪽 절반은 잡음: 가운데가 가장 센 경계, 그라데이션 안은 0에 가깝다
        left = Image.linear_gradient("L").resize((100, 256))
        right = Image.effect_noise((100, 256), 20)
        image = Image.new("L", (200, 256))
        image.paste(left, (0, 0))
        image.paste(right, (100, 0))
        edges = core.line_edge_profile(image, "x")
        self.assertEqual(max(range(200), key=edges.__getitem__), 100)
        self.assertLess(max(edges[1:99]), core.EDGE_MIN_STRENGTH)

    def test_reconcile_fixes_one_sided_gap(self) -> None:
        edges = [0.0] * 300
        x = core.AxisResult(300, 0, 300, [(140, 152, core.GAP_BOTH)], edges)
        y = core.AxisResult(300, 0, 300, [(150, 190, core.GAP_START)], list(edges))
        core.reconcile_axes([x, y])
        self.assertEqual(y.gaps[0], (150, 162, core.GAP_BOTH))

    def test_reconcile_touch_reference_shrinks_run(self) -> None:
        edges = [0.0] * 300
        x = core.AxisResult(300, 0, 300, [(140, 140, core.GAP_TOUCH)], edges)
        y = core.AxisResult(300, 0, 300, [(150, 170, core.GAP_START)], list(edges))
        core.reconcile_axes([x, y])
        self.assertEqual(y.gaps[0], (150, 150, core.GAP_BOTH))


class SampleSetTest(unittest.TestCase):
    """scripts/make_grid_samples.py의 시험 그림 전부를 나눠 정답과 비교한다(회귀 방지)."""

    def test_samples_within_3px(self) -> None:
        import sys

        from helpers import ROOT

        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import make_grid_samples as samples
        finally:
            sys.path.remove(str(ROOT / "scripts"))
        failures = []
        items = samples.sample_list()
        for sample in items:
            image, truth = samples.finish(sample, *samples.render(sample))
            if sample.jpeg:
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=sample.jpeg)
                image = Image.open(io.BytesIO(buffer.getvalue()))
            split = core.split_grid_auto(image, len(sample.rows), len(sample.cols))
            rects = core.clamp_rects(split.rects, image.width, image.height)
            error = max(abs(a - b) for g, e in zip(rects, truth) for a, b in zip(g, e))
            if len(rects) != len(truth) or error > 3:
                failures.append((sample.name, error))
        self.assertGreaterEqual(len(items), 20)
        self.assertLessEqual(len(failures), 2, failures)


class SharedEdgeTest(unittest.TestCase):
    RECTS = [(0, 0, 100, 80), (110, 0, 200, 80), (0, 90, 100, 160), (110, 90, 200, 160)]

    def test_find_in_gutter_and_on_line(self) -> None:
        self.assertEqual(core.find_shared_edge(self.RECTS, 105, 40, 4), core.SharedEdge("x", 0, 1))
        self.assertEqual(core.find_shared_edge(self.RECTS, 98, 40, 4), core.SharedEdge("x", 0, 1))
        self.assertEqual(core.find_shared_edge(self.RECTS, 150, 85, 4), core.SharedEdge("y", 1, 3))

    def test_not_found_inside_cell(self) -> None:
        self.assertIsNone(core.find_shared_edge(self.RECTS, 50, 40, 4))
        self.assertIsNone(core.find_shared_edge([(0, 0, 50, 50)], 50, 25, 4))

    def test_not_neighbors_when_barely_overlapping(self) -> None:
        rects = [(0, 0, 100, 100), (100, 90, 200, 190)]  # 마주 보는 길이 10 — 이웃이 아니다
        self.assertIsNone(core.find_shared_edge(rects, 100, 95, 4))

    def test_move_keeps_gutter_and_both_cells_change(self) -> None:
        moved = core.move_shared_edge(self.RECTS, core.SharedEdge("x", 0, 1), 15, 200, 160)
        self.assertEqual(moved[0], (0, 0, 115, 80))
        self.assertEqual(moved[1], (125, 0, 200, 80))
        self.assertEqual(moved[2:], self.RECTS[2:])

    def test_move_is_clamped_to_min_size(self) -> None:
        moved = core.move_shared_edge(self.RECTS, core.SharedEdge("y", 0, 2), 500, 200, 160)
        self.assertEqual(moved[2], (0, 156, 100, 160))
        self.assertEqual(moved[0], (0, 0, 100, 146))
        moved = core.move_shared_edge(self.RECTS, core.SharedEdge("y", 0, 2), -500, 200, 160)
        self.assertEqual(moved[0], (0, 0, 100, 4))


class VersionTest(unittest.TestCase):
    def test_version_format(self) -> None:
        self.assertRegex(core.__version__, r"^\d+\.\d+\.\d+$")


class RectHelpersTest(unittest.TestCase):
    def test_clamp_and_dedupe(self) -> None:
        rects = [(-10, -10, 50, 50), (50, 50, -10, -10), (0, 0, 2, 2), (90, 90, 200, 200)]
        self.assertEqual(core.clamp_rects(rects, 100, 100), [(0, 0, 50, 50), (90, 90, 100, 100)])

    def test_scale(self) -> None:
        self.assertEqual(core.scale_rects([(10, 10, 20, 20)], (100, 100), (200, 50)), [(20, 5, 40, 10)])
        self.assertEqual(core.scale_rects([(1, 2, 3, 4)], (0, 0), (10, 10)), [(1, 2, 3, 4)])


if __name__ == "__main__":
    unittest.main()
