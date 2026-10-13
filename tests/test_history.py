from __future__ import annotations

import json
import time
import unittest
from pathlib import Path

from helpers import scratch_tempdir

import gridcrop_core as core


def entry(n: int) -> dict[str, object]:
    return core.make_history_entry("single", [f"img{n}.png"], Path("out"), [Path(f"out/img{n}_rect_01.png")], 1, timestamp=f"2026-10-13T10:{n % 60:02d}:00")


class HistoryAppendReadTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = scratch_tempdir()
        self.dir = Path(self._tmp.name)
        self.path = self.dir / core.HISTORY_FILENAME

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_append_and_read_newest_first(self) -> None:
        for n in range(5):
            core.append_history(self.path, {"n": n})
        entries, more = core.read_recent_history(self.path, limit=3)
        self.assertEqual([e["n"] for e in entries], [4, 3, 2])
        self.assertTrue(more)
        entries, more = core.read_recent_history(self.path, limit=3, skip=3)
        self.assertEqual([e["n"] for e in entries], [1, 0])
        self.assertFalse(more)

    def test_missing_file(self) -> None:
        self.assertEqual(core.read_recent_history(self.path), ([], False))

    def test_broken_lines_are_skipped(self) -> None:
        self.path.write_bytes(
            b'{"n": 0}\n'
            b"not json\n"
            b"[1, 2]\n"
            b"\xff\xfe broken utf8\n"
            b"\n"
            b'{"n": 1}\n'
            b'{"n": 2, "cut'  # 쓰다 끊긴 마지막 줄
        )
        entries, _ = core.read_recent_history(self.path)
        self.assertEqual([e["n"] for e in entries], [1, 0])

    def test_append_after_cut_line_starts_new_line(self) -> None:
        self.path.write_bytes(b'{"n": 0}\n{"n": 1, "cu')
        core.append_history(self.path, {"n": 2})
        entries, _ = core.read_recent_history(self.path)
        self.assertEqual([e["n"] for e in entries], [2, 0])

    def test_korean_text_across_chunk_boundary(self) -> None:
        text = "가나다라마바사" * 50
        for n in range(30):
            core.append_history(self.path, {"n": n, "text": text})
        lines = list(core.iter_lines_reverse(self.path, chunk_size=7))
        parsed = [core.parse_history_line(line) for line in lines]
        parsed = [p for p in parsed if p]
        self.assertEqual(len(parsed), 30)
        self.assertTrue(all(p["text"] == text for p in parsed))

    def test_rotation_by_size_and_archive_limit(self) -> None:
        for n in range(200):
            core.append_history(self.path, {"n": n, "pad": "x" * 100}, max_bytes=2000, keep=2)
        self.assertTrue(self.path.exists())
        self.assertTrue(core.history_archive_path(self.path, 1).exists())
        self.assertTrue(core.history_archive_path(self.path, 2).exists())
        self.assertFalse(core.history_archive_path(self.path, 3).exists())
        for f in core.history_files(self.path, keep=2):
            self.assertLess(f.stat().st_size, 2000 + 200)
        entries, _ = core.read_recent_history(self.path, limit=1000, keep=2)
        numbers = [e["n"] for e in entries]
        self.assertEqual(numbers[0], 199)
        self.assertEqual(numbers, sorted(numbers, reverse=True))
        self.assertEqual(numbers, list(range(199, 199 - len(numbers), -1)))  # 빠진 줄 없이 이어진다

    def test_paging_crosses_archives(self) -> None:
        for n in range(60):
            core.append_history(self.path, {"n": n, "pad": "y" * 50}, max_bytes=1000, keep=5)
        first, more = core.read_recent_history(self.path, limit=10, keep=5)
        second, _ = core.read_recent_history(self.path, limit=10, skip=10, keep=5)
        self.assertTrue(more)
        self.assertEqual([e["n"] for e in first], list(range(59, 49, -1)))
        self.assertEqual([e["n"] for e in second], list(range(49, 39, -1)))

    def test_large_file_reads_only_tail_fast(self) -> None:
        line = json.dumps(entry(1), ensure_ascii=False) + "\n"
        with open(self.path, "w", encoding="utf-8") as fp:
            for _ in range(30000):
                fp.write(line)
        self.assertGreater(self.path.stat().st_size, 5 * 1024 * 1024)
        started = time.perf_counter()
        entries, more = core.read_recent_history(self.path, limit=50)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(entries), 50)
        self.assertTrue(more)
        self.assertLess(elapsed, 0.5)
        # 다음 기록을 적으면 롤링되어 새 파일이 작게 시작한다.
        core.append_history(self.path, entry(2))
        self.assertLess(self.path.stat().st_size, 2000)
        self.assertTrue(core.history_archive_path(self.path, 1).exists())

    def test_make_entry_caps_paths(self) -> None:
        paths = [Path(f"p{i}.png") for i in range(core.HISTORY_MAX_SAVED_PATHS + 5)]
        made = core.make_history_entry("batch", ["a"], None, paths, 4)
        self.assertEqual(made["saved_count"], len(paths))
        self.assertEqual(len(made["saved_paths"]), core.HISTORY_MAX_SAVED_PATHS)
        self.assertTrue(made["saved_paths_truncated"])
        self.assertIsNone(made["output_dir"])

    def test_safe_int(self) -> None:
        self.assertEqual(core.safe_int("3"), 3)
        self.assertEqual(core.safe_int("3.7"), 3)
        self.assertEqual(core.safe_int("abc", 7), 7)
        self.assertEqual(core.safe_int(None), 0)
        self.assertEqual(core.safe_int(True), 0)


if __name__ == "__main__":
    unittest.main()
