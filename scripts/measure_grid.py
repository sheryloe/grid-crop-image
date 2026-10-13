"""폴더의 그림마다 4칸·9칸 자동 나누기를 돌려 정답과 비교한다.

    py scripts/measure_grid.py .scratch/grid_samples
    py scripts/measure_grid.py D:/내AI그림 --grid 3x3

- 그림 옆에 같은 이름의 정답 JSON(make_grid_samples.py가 만든 형식)이 있으면
  칸마다 네 변의 차이(px)를 재서 가장 큰 값이 허용 오차(기본 3px) 이내면 '맞음'.
- 정답 JSON이 없으면(실제 AI 그림 폴더) --grid로 준 칸 수로 나눠 보고,
  찾은 여백 수와 같은 간격으로 넘어간 경계 수만 보고한다.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import gridcrop_core as core  # noqa: E402


def parse_grid(text: str) -> tuple[int, int]:
    try:
        rows, cols = (int(v) for v in text.lower().replace("×", "x").split("x"))
    except ValueError:
        raise argparse.ArgumentTypeError("칸 수는 2x2, 3x3처럼 적어 주세요.") from None
    if rows < 1 or cols < 1:
        raise argparse.ArgumentTypeError("행과 열은 1 이상이어야 합니다.")
    return rows, cols


def load_truth(image_path: Path) -> dict | None:
    json_path = image_path.with_suffix(".json")
    if not json_path.exists():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("rects"), list):
        return None
    return data


def max_error(got: list[core.Rect], expected: list[list[int]]) -> int | None:
    if len(got) != len(expected):
        return None
    return max(abs(a - b) for g, e in zip(got, expected) for a, b in zip(g, e))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="4칸·9칸 자동 나누기 측정")
    parser.add_argument("folder", type=Path)
    parser.add_argument("--grid", type=parse_grid, default=(2, 2), help="정답 JSON이 없을 때 쓸 칸 수(기본 2x2)")
    parser.add_argument("--tolerance", type=int, default=3, help="'맞음'으로 볼 최대 경계 오차(px, 기본 3)")
    parser.add_argument("--detail", metavar="이름", help="이 글자가 이름에 든 그림은 축마다 경계선 세기 상위 값을 함께 보인다")
    args = parser.parse_args(argv)

    folder: Path = args.folder
    if not folder.is_dir():
        print(f"폴더가 없습니다: {folder}")
        return 2
    images = [p for p in sorted(folder.iterdir()) if p.is_file() and p.suffix.lower() in core.SUPPORTED_IMAGE_SUFFIXES]
    if not images:
        print(f"그림이 없습니다: {folder}")
        return 2

    rows_out: list[tuple[str, ...]] = []
    judged = passed = 0
    total_found = total_expected = 0
    errors: list[int] = []
    started = time.perf_counter()
    for path in images:
        truth = load_truth(path)
        rows, cols = (int(truth["rows"]), int(truth["cols"])) if truth else args.grid
        try:
            image, _fmt = core.open_image_file(path)
        except Exception as exc:  # 측정 도구: 한 장이 깨져도 나머지는 잰다
            rows_out.append((path.name, f"{rows}×{cols}", "-", "-", "-", core.describe_error(exc)))
            continue
        t0 = time.perf_counter()
        split = core.split_grid_auto(image, rows, cols)
        elapsed = time.perf_counter() - t0
        rects = core.clamp_rects(split.rects, image.width, image.height)
        total_found += split.gutters_found
        total_expected += split.gutters_expected
        found = f"{split.gutters_found}/{split.gutters_expected}"
        fallback = str(split.gutters_expected - split.gutters_found)
        if truth:
            err = max_error(rects, truth["rects"])
            judged += 1
            if err is None:
                verdict = "틀림(칸 수 다름)"
                err_text = "-"
            else:
                errors.append(err)
                ok = err <= args.tolerance
                passed += ok
                verdict = "맞음" if ok else "틀림"
                err_text = str(err)
        else:
            err_text = "-"
            verdict = "정답 없음"
        rows_out.append((path.name, f"{rows}×{cols}", found, fallback, err_text, f"{verdict} ({elapsed:.2f}초)"))
        if args.detail and args.detail in path.name:
            print_detail(path.name, image, rects, truth)

    headers = ("그림", "칸", "찾은 여백", "같은 간격", "최대 오차(px)", "결과")
    widths = [max(_width(h), *(_width(r[i]) for r in rows_out)) for i, h in enumerate(headers)]
    print(_line(headers, widths))
    print(_line(tuple("-" * w for w in widths), widths))
    for row in rows_out:
        print(_line(row, widths))
    print()
    print(f"그림 {len(images)}장, 걸린 시간 {time.perf_counter() - started:.1f}초")
    print(f"찾은 여백 {total_found}곳 / 있어야 할 경계 {total_expected}곳(같은 간격으로 넘어간 경계 {total_expected - total_found}곳)")
    if judged:
        mean = sum(errors) / len(errors) if errors else 0
        print(f"정답 있는 그림 {judged}장 중 {passed}장 맞음(오차 {args.tolerance}px 이내), 평균 최대 오차 {mean:.1f}px")
    return 0


def print_detail(name: str, image, rects: list[core.Rect], truth: dict | None) -> None:
    """알고리즘을 고칠 때 보는 자료: 축마다 경계선 세기 상위 12곳, 찾은 경계와 정답 경계."""
    gray = image.convert("L")
    print(f"[자세히] {name}")
    for axis, index in (("x", (0, 2)), ("y", (1, 3))):
        edges = core.line_edge_profile(gray, axis)
        top = sorted(range(len(edges)), key=edges.__getitem__, reverse=True)[:12]
        print(f"  {axis}축 경계선 세기 상위: " + ", ".join(f"{i}:{edges[i]:.0f}" for i in sorted(top)))
        got = sorted({r[i] for r in rects for i in index})
        print(f"  {axis}축 찾은 경계: {got}")
        if truth:
            want = sorted({r[i] for r in truth["rects"] for i in index})
            print(f"  {axis}축 정답 경계: {want}")


def _width(text: str) -> int:
    """한글 등 넓은 글자는 두 칸으로 센다(표 줄 맞춤용)."""
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(ch) in {"W", "F"} else 1 for ch in text)


def _line(cells: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(c + " " * (w - _width(c)) for c, w in zip(cells, widths)).rstrip()


if __name__ == "__main__":
    raise SystemExit(main())
