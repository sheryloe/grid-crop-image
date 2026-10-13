"""시험 공용 도구. 임시 파일은 저장소 안 .scratch/tmp 아래에만 만든다."""

from __future__ import annotations

import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRATCH = ROOT / ".scratch" / "tmp"


def scratch_tempdir() -> tempfile.TemporaryDirectory:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(dir=SCRATCH)


def make_grid_image(
    cell_sizes_x: list[int],
    cell_sizes_y: list[int],
    gutter: int,
    border: int,
    gutter_color: int = 255,
    seed: int = 1,
):
    """칸마다 무늬(잡음)가 있고 칸 사이·바깥이 단색인 시험용 그림과 기대 영역."""
    from PIL import Image

    rng = random.Random(seed)
    width = border * 2 + sum(cell_sizes_x) + gutter * (len(cell_sizes_x) - 1)
    height = border * 2 + sum(cell_sizes_y) + gutter * (len(cell_sizes_y) - 1)
    image = Image.new("RGB", (width, height), (gutter_color,) * 3)
    expected = []
    y = border
    for ch in cell_sizes_y:
        x = border
        for cw in cell_sizes_x:
            noise = Image.effect_noise((cw, ch), 60).convert("RGB")
            tint = Image.new("RGB", (cw, ch), (rng.randrange(40, 200), rng.randrange(40, 200), rng.randrange(40, 200)))
            image.paste(Image.blend(noise, tint, 0.5), (x, y))
            expected.append((x, y, x + cw, y + ch))
            x += cw + gutter
        y += ch + gutter
    return image, expected
