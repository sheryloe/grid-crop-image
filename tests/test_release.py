"""다른 PC 배포 관련: 쓰기 금지 폴더에서의 기록·설정 위치, 배포 zip 구성, 판 번호."""

from __future__ import annotations

import sys
import tkinter as tk
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from helpers import ROOT, scratch_tempdir

import gridcrop_core as core

sys.path.insert(0, str(ROOT / "scripts"))
import make_release  # noqa: E402

sys.path.remove(str(ROOT / "scripts"))

try:
    _probe = tk.Tk()
    _probe.destroy()
    TK_OK = True
except tk.TclError:
    TK_OK = False


class ReadOnlyFolderTest(unittest.TestCase):
    """exe 폴더에 쓸 수 없을 때(예: C:\\Program Files 아래) 기록·설정이 사용자 폴더로 가는지.

    실제 권한(ACL)을 바꾸지 않고, exe 폴더에 파일을 쓰면 '권한 없음'이 나도록 흉내 낸다.
    사용자 폴더(Path.home)도 시험용 폴더로 바꿔 실제 사용자 폴더에는 아무것도 쓰지 않는다.
    """

    def setUp(self) -> None:
        self._tmp = scratch_tempdir()
        root = Path(self._tmp.name)
        self.exe_dir = root / "Program Files" / "AutoCropSplitter"
        self.exe_dir.mkdir(parents=True)
        self.home = root / "home"
        self.home.mkdir()
        self.expected = self.home / ".grid_crop_studio"
        original_write_bytes = Path.write_bytes
        original_open = open
        exe_dir = self.exe_dir

        def deny_write_bytes(path: Path, data: bytes) -> int:
            if path.parent == exe_dir:
                raise PermissionError(13, "액세스가 거부되었습니다", str(path))
            return original_write_bytes(path, data)

        def deny_open(file, mode="r", *args, **kwargs):
            if isinstance(file, (str, Path)) and any(flag in mode for flag in "wax+") and Path(file).parent == exe_dir:
                raise PermissionError(13, "액세스가 거부되었습니다", str(file))
            return original_open(file, mode, *args, **kwargs)

        self.patches = [
            mock.patch.object(core, "app_base_dir", return_value=self.exe_dir),
            mock.patch.object(Path, "home", return_value=self.home),
            mock.patch.object(Path, "write_bytes", deny_write_bytes),
            mock.patch("builtins.open", deny_open),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self) -> None:
        for patch in reversed(self.patches):
            patch.stop()
        self._tmp.cleanup()

    def test_data_dir_moves_to_user_folder(self) -> None:
        data_dir = core.app_data_dir()
        self.assertEqual(data_dir, self.expected)
        self.assertTrue(data_dir.is_dir())

    def test_history_and_settings_written_to_user_folder(self) -> None:
        data_dir = core.app_data_dir()
        history = data_dir / core.HISTORY_FILENAME
        core.append_history(history, core.make_history_entry("single", ["a.png"], data_dir, [], 4))
        core.save_ocr_settings(data_dir / core.OCR_SETTINGS_FILENAME, core.OcrSettings())
        entries, _ = core.read_recent_history(history)
        self.assertEqual(entries[0]["job_type"], "single")
        self.assertTrue((self.expected / core.OCR_SETTINGS_FILENAME).is_file())
        self.assertEqual(list(self.exe_dir.iterdir()), [])  # exe 폴더에는 아무것도 남지 않는다

    def test_writable_exe_folder_is_used_as_is(self) -> None:
        mock.patch.stopall()
        self.patches = []
        with mock.patch.object(core, "app_base_dir", return_value=self.exe_dir):
            self.assertEqual(core.app_data_dir(), self.exe_dir)
        self.assertEqual(list(self.exe_dir.iterdir()), [])  # 쓰기 확인용 파일은 지운다

    @unittest.skipUnless(TK_OK, "Tk를 쓸 수 없는 환경")
    def test_app_uses_user_folder(self) -> None:
        import app

        root = tk.Tk()
        root.withdraw()
        try:
            window = app.AutoCropApp(root)
            self.assertEqual(window.history_path.parent, self.expected)
            self.assertEqual(window.ocr_settings_path.parent, self.expected)
            window._append_history_entry("single", ["a.png"], self.home, [self.home / "a_rect_01.png"], 1)
            self.assertTrue((self.expected / core.HISTORY_FILENAME).is_file())
        finally:
            root.destroy()


class ReleaseZipTest(unittest.TestCase):
    def test_zip_has_exe_internal_and_guide(self) -> None:
        with scratch_tempdir() as tmp:
            base = Path(tmp)
            dist = base / "dist" / make_release.APP_NAME
            (dist / "_internal").mkdir(parents=True)
            (dist / f"{make_release.APP_NAME}.exe").write_bytes(b"MZ")
            (dist / "_internal" / "python314.dll").write_bytes(b"dll")
            (dist / core.HISTORY_FILENAME).write_text("{}\n", encoding="utf-8")  # 시험 실행 흔적은 빠져야 한다
            target = make_release.make_zip("9.9.9", dist_dir=dist, release_dir=base / "release")
            self.assertEqual(target.name, "AutoCropSplitter-9.9.9.zip")
            with zipfile.ZipFile(target) as archive:
                names = set(archive.namelist())
                guide = archive.read("AutoCropSplitter/사용안내.txt").decode("utf-8-sig")
        self.assertEqual(
            names,
            {
                "AutoCropSplitter/AutoCropSplitter.exe",
                "AutoCropSplitter/_internal/python314.dll",
                "AutoCropSplitter/사용안내.txt",
            },
        )
        self.assertIn("9.9.9", guide)
        self.assertNotIn("{version}", guide)
        self.assertIn("\r\n", guide)
        for word in ("압축", "실행", "4칸", "저장 폴더", "여러 장", "기록", "막혔을 때", "그래픽카드"):
            self.assertIn(word, guide)

    def test_missing_exe_is_reported_in_korean(self) -> None:
        with scratch_tempdir() as tmp:
            with self.assertRaises(SystemExit) as caught:
                make_release.make_zip("1.0.0", dist_dir=Path(tmp) / "none", release_dir=Path(tmp) / "release")
        self.assertIn("실행 파일이 없습니다", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
