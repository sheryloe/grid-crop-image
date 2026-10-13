from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

from helpers import scratch_tempdir

import gridcrop_core as core
from PIL import Image


class ParseLayoutTest(unittest.TestCase):
    def test_valid(self) -> None:
        layout = core.parse_layout(
            {
                "rectangles": [{"left": 1, "top": 2, "right": "30.6", "bottom": 40}],
                "image_size": {"width": 100, "height": 80},
                "zoom": "0.5",
                "configured": True,
                "output_dir": "D:/out",
            }
        )
        self.assertEqual(layout.rects, [(1, 2, 31, 40)])
        self.assertEqual(layout.image_size, (100, 80))
        self.assertEqual(layout.zoom, 0.5)
        self.assertTrue(layout.configured)

    def test_errors(self) -> None:
        cases = [
            ([1, 2], "객체"),
            ({}, "영역이 없"),
            ({"rectangles": ["x"]}, "1번 영역"),
            ({"rectangles": [{"left": "a"}]}, "숫자가 아닙"),
            ({"rectangles": [{"left": True}]}, "숫자가 아닙"),
            ({"rectangles": [{"left": 1}], "image_size": {"width": 0, "height": 5}}, "0 이하"),
        ]
        for data, pattern in cases:
            with self.subTest(data=data):
                with self.assertRaisesRegex(core.LayoutError, pattern):
                    core.parse_layout(data)

    def test_require_size(self) -> None:
        with self.assertRaisesRegex(core.LayoutError, "크기 정보"):
            core.parse_layout({"rectangles": [{"left": 1}]}, require_size=True)

    def test_bad_zoom_defaults(self) -> None:
        for zoom in ["abc", -1, 0, None]:
            self.assertEqual(core.parse_layout({"rectangles": [{}], "zoom": zoom}).zoom, 1.0)

    def test_load_file_with_bom_and_broken_json(self) -> None:
        with scratch_tempdir() as tmp:
            good = Path(tmp) / "good.json"
            good.write_bytes("\ufeff".encode("utf-8") + json.dumps({"rectangles": [{"right": 5, "bottom": 5}]}).encode("utf-8"))
            self.assertEqual(core.load_layout_file(good).rects, [(0, 0, 5, 5)])
            broken = Path(tmp) / "broken.json"
            broken.write_text("{ not json", encoding="utf-8")
            with self.assertRaisesRegex(core.LayoutError, "깨졌습니다"):
                core.load_layout_file(broken)
            with self.assertRaisesRegex(core.LayoutError, "읽지 못했"):
                core.load_layout_file(Path(tmp) / "none.json")

    def test_write_text_atomic(self) -> None:
        with scratch_tempdir() as tmp:
            target = Path(tmp) / "a.json"
            core.write_text_atomic(target, "하나")
            core.write_text_atomic(target, "둘")
            self.assertEqual(target.read_text(encoding="utf-8"), "둘")
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["a.json"])


class ImageIoTest(unittest.TestCase):
    def test_exif_orientation_applied(self) -> None:
        with scratch_tempdir() as tmp:
            path = Path(tmp) / "phone.jpg"
            exif = Image.Exif()
            exif[0x0112] = 6  # 시계 방향 90도 회전 필요
            Image.new("RGB", (40, 20), "red").save(path, exif=exif.tobytes())
            image, fmt = core.open_image_file(path)
            self.assertEqual(fmt, "JPEG")
            self.assertEqual(image.size, (20, 40))

    def test_save_variants(self) -> None:
        with scratch_tempdir() as tmp:
            rgba = Image.new("RGBA", (10, 10), (255, 0, 0, 128))
            for suffix in [".jpg", ".png", ".bmp", ".gif", ".webp", ".tif"]:
                target = Path(tmp) / f"x{suffix}"
                core.save_image(rgba, target)
                with Image.open(target) as reopened:
                    self.assertEqual(reopened.size, (10, 10))
            core.save_image(Image.new("I;16", (8, 8)), Path(tmp) / "deep.jpg")

    def test_output_path_unique(self) -> None:
        with scratch_tempdir() as tmp:
            out = Path(tmp)
            first = core.build_output_path(out, "a_rect_01", ".png")
            first.write_bytes(b"")
            second = core.build_output_path(out, "a_rect_01", ".png")
            self.assertEqual(second.name, "a_rect_01_1.png")

    def test_collect_images_skips_generated_crops(self) -> None:
        with scratch_tempdir() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            for name in ["a.PNG", "b.jpg", "a_rect_01.png", "sub/c.webp", "sub/c_rect_02_1.webp", "note.txt"]:
                (root / name).write_bytes(b"")
            names = [p.relative_to(root).as_posix() for p in core.collect_images_in_folder(root)]
            self.assertEqual(names, ["a.PNG", "b.jpg", "sub/c.webp"])

    def test_describe_error(self) -> None:
        self.assertIn("찾을 수 없", core.describe_error(FileNotFoundError("x")))
        self.assertIn("권한", core.describe_error(PermissionError("x")))
        try:
            Image.open(io.BytesIO(b"not an image"))
        except Exception as exc:
            self.assertIn("그림 파일로 읽을 수 없", core.describe_error(exc))
        self.assertEqual(core.describe_error(ValueError("한글")), "한글")

    def test_suffix_from_format(self) -> None:
        self.assertEqual(core.suffix_from_format("JPEG"), ".jpg")
        self.assertEqual(core.suffix_from_format("DIB"), ".png")
        self.assertEqual(core.suffix_from_format(None), ".png")


if __name__ == "__main__":
    unittest.main()
