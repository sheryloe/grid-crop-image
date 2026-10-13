"""화면을 띄우지 않고(창 숨김) 앱의 연결부를 확인한다. Tk를 쓸 수 없는 환경에서는 건너뛴다."""

from __future__ import annotations

import tkinter as tk
import unittest
from pathlib import Path

from helpers import make_grid_image, scratch_tempdir

import gridcrop_core as core

try:
    _probe = tk.Tk()
    _probe.destroy()
    TK_OK = True
except tk.TclError:
    TK_OK = False


@unittest.skipUnless(TK_OK, "Tk를 쓸 수 없는 환경")
class AppWiringTest(unittest.TestCase):
    def setUp(self) -> None:
        import app

        self.app_module = app
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = app.AutoCropApp(self.root)
        self._tmp = scratch_tempdir()
        self.dir = Path(self._tmp.name)
        self.app.history_path = self.dir / core.HISTORY_FILENAME

    def tearDown(self) -> None:
        self.root.destroy()
        self._tmp.cleanup()

    def load(self, image, name="grid.png") -> None:
        self.app._load_image(
            image=image,
            display_name=name,
            save_stem=Path(name).stem,
            format_name="PNG",
            source_kind="clipboard",
            source_path=None,
        )

    def test_auto_grid_confirms_and_saves(self) -> None:
        image, expected = make_grid_image([300, 320], [200, 220], gutter=20, border=10)
        self.load(image)
        self.assertTrue(self.app._apply_auto_grid(2, 2, detect_gutters=True, confirm=True))
        self.assertEqual([r.as_tuple() for r in self.app.rectangles], expected)
        self.assertTrue(self.app.is_configured)
        self.app._set_output_dir(self.dir, user_selected=True)
        self.assertEqual(str(self.app.split_button.cget("state")), "normal")

    def test_batch_job_with_auto_grid(self) -> None:
        files = []
        for i in range(3):
            image, _ = make_grid_image([150, 160, 170], [150, 150, 150], gutter=8, border=4, seed=i)
            path = self.dir / f"ai_{i}.png"
            image.save(path)
            files.append(path)
        broken = self.dir / "broken.png"
        broken.write_bytes(b"not an image")
        files.append(broken)
        out = self.dir / "out"
        out.mkdir()
        job = self.app_module.BatchJob(files=files, output_dir=out, create_subfolders=True, grid=(3, 3))
        progress = []
        result = self.app._perform_batch_job(job, lambda d, t: progress.append((d, t)))
        self.assertEqual(len(result["saved_paths"]), 27)
        self.assertEqual(result["failed_paths"], [broken])
        self.assertIn("그림 파일로 읽을 수 없", result["errors"][0])
        self.assertEqual(progress[-1], (4, 4))
        self.assertEqual(result["gutter_misses"], 0)
        first = sorted((out / "ai_0").iterdir())[0]
        self.assertEqual(first.name, "ai_0_rect_01.png")

    def test_batch_scales_current_layout_to_other_sizes(self) -> None:
        from PIL import Image

        small = self.dir / "small.png"
        Image.new("RGB", (50, 50), "blue").save(small)
        out = self.dir / "out2"
        out.mkdir()
        job = self.app_module.BatchJob(
            files=[small], output_dir=out, create_subfolders=False, rects=[(0, 0, 100, 100)], source_size=(200, 200)
        )
        result = self.app._perform_batch_job(job)
        with Image.open(result["saved_paths"][0]) as saved:
            self.assertEqual(saved.size, (25, 25))

    def test_history_written_and_ocr_targets(self) -> None:
        self.load(Image_new())
        targets = self.app._ocr_targets()
        self.assertEqual([t[0] for t in targets], ["사진 전체"])
        self.app._apply_auto_grid(2, 2, detect_gutters=False, confirm=True)
        self.assertEqual(len(self.app._ocr_targets()), 4)
        self.app._append_history_entry("single", ["a.png"], self.dir, [self.dir / "a_rect_01.png"], 1)
        entries, _ = self.app._read_history_entries()
        self.assertEqual(entries[0]["job_type"], "single")

    def test_layout_fits_laptop_window(self) -> None:
        """노트북 크기 창에서 버튼이 잘리지 않고 '잘라서 저장'이 창 안에 보이는지."""
        self.root.geometry("1080x640+0+0")  # 앱이 허용하는 가장 작은 창
        self.root.deiconify()
        self.root.update()
        try:
            buttons = [
                self.app.open_button, self.app.paste_button, self.app.save_config_button, self.app.load_config_button,
                self.app.batch_button, self.app.retry_batch_button, self.app.history_button, self.app.ocr_button,
                self.app.ocr_settings_button, self.app.zoom_out_button, self.app.zoom_in_button, self.app.zoom_reset_button,
                self.app.zoom_fit_button, self.app.delete_button, self.app.clear_button, self.app.grid_button,
                self.app.configure_button,
            ]
            for button in buttons:
                parent = button.master
                with self.subTest(button=button.cget("text")):
                    self.assertLessEqual(button.winfo_x() + button.winfo_width(), parent.winfo_width() + 1)
                    self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth() - 1)
            bottom = self.app.split_button.winfo_rooty() + self.app.split_button.winfo_height()
            self.assertLessEqual(bottom, self.root.winfo_rooty() + self.root.winfo_height())
            for button in self.app.quick_grid_buttons:
                self.assertLessEqual(
                    button.winfo_rooty() + button.winfo_height(), self.root.winfo_rooty() + self.root.winfo_height()
                )
        finally:
            self.root.withdraw()

    def test_zoom_is_capped_for_huge_images(self) -> None:
        from PIL import Image

        self.load(Image.new("RGB", (8000, 6000)))
        self.assertLess(self.app._clamp_zoom(8.0), 1.0)


def Image_new():
    from PIL import Image

    return Image.new("RGB", (200, 100), "white")


if __name__ == "__main__":
    unittest.main()
