"""AI 그림 4칸·9칸과 비슷한 시험 그림을 만들고 정답 경계를 JSON으로 함께 저장한다.

실제 AI 그림이 없는 PC에서 칸 사이 여백 찾기를 재기 위한 것이다. Pillow만 쓴다.

    py scripts/make_grid_samples.py            # 결과: .scratch/grid_samples/
    py scripts/make_grid_samples.py 다른폴더

그림마다 <이름>.png(또는 .jpg)와 <이름>.json이 생긴다. JSON에는 행·열 수, 칸마다
[왼쪽, 위, 오른쪽, 아래](오른쪽·아래는 포함하지 않는 끝) 정답과 설명이 들어 있다.
같은 번호로 다시 만들면 늘 같은 그림이 나온다(난수 씨앗 고정).
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / ".scratch" / "grid_samples"


@dataclass
class Sample:
    name: str
    desc: str
    cols: list[int]  # 칸 너비들
    rows: list[int]  # 칸 높이들
    gutter: int
    border: int
    background: str = "flat"  # flat, vgrad, dgrad, noise, stripes, hstripes
    colors: tuple = ((255, 255, 255),)
    content: str = "photo"  # photo, whitebg
    jpeg: int = 0  # 0이면 PNG, 아니면 JPEG 품질
    seed: int = 1
    extra: dict = field(default_factory=dict)


def _rand_color(rng: random.Random, lo: int = 20, hi: int = 235) -> tuple[int, int, int]:
    return (rng.randrange(lo, hi), rng.randrange(lo, hi), rng.randrange(lo, hi))


def _vertical_gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    w, h = size
    strip = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        strip.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return strip.resize((w, h))


def _diagonal_gradient(size: tuple[int, int], a: tuple, b: tuple) -> Image.Image:
    w, h = size
    small = Image.new("RGB", (64, 64))
    for y in range(64):
        for x in range(64):
            t = (x + y) / 126
            small.putpixel((x, y), tuple(round(p + (q - p) * t) for p, q in zip(a, b)))
    return small.resize((w, h), Image.Resampling.BILINEAR)


def _add_noise(image: Image.Image, sigma: float) -> Image.Image:
    """그림에 평균 0의 잡음을 더한다(그림 + 잡음 - 128)."""
    noise = Image.effect_noise(image.size, sigma)  # 128 중심의 회색 잡음
    return ImageChops.add(image, Image.merge("RGB", (noise, noise, noise)), scale=1.0, offset=-128)


def _noise_layer(size: tuple[int, int], sigma: float, base: tuple) -> Image.Image:
    return _add_noise(Image.new("RGB", size, base), sigma)


def make_background(sample: Sample, size: tuple[int, int], rng: random.Random) -> Image.Image:
    kind = sample.background
    c = sample.colors
    if kind == "flat":
        return Image.new("RGB", size, c[0])
    if kind == "vgrad":
        return _vertical_gradient(size, c[0], c[1])
    if kind == "dgrad":
        return _diagonal_gradient(size, c[0], c[1])
    if kind == "noise":
        return _noise_layer(size, sample.extra.get("sigma", 16), c[0])
    if kind in {"stripes", "hstripes"}:
        w, h = size
        image = Image.new("RGB", size, c[0])
        draw = ImageDraw.Draw(image)
        period = sample.extra.get("period", 8)
        if kind == "hstripes":
            for y in range(0, h, period):
                draw.rectangle((0, y, w, y + period // 2 - 1), fill=c[1])
        else:  # 대각선 줄무늬
            for k in range(-h, w + h, period):
                draw.line((k, 0, k + h, h), fill=c[1], width=max(1, period // 2))
        return image
    raise ValueError(kind)


def make_cell(size: tuple[int, int], rng: random.Random, style: str) -> Image.Image:
    """AI 그림 한 칸처럼 보이는 내용: 그라데이션 바탕 + 도형 + 잔잡음 + 살짝 흐림."""
    w, h = size
    if style == "whitebg":
        # 흰 바탕 제품 사진: 바탕은 거의 흰색(여백 255보다 살짝 어둡게), 가운데 물체
        tone = rng.randrange(238, 249)
        cell = _vertical_gradient(size, (tone + 4,) * 3, (tone - 4,) * 3)
        draw = ImageDraw.Draw(cell)
        mx, my = w * rng.uniform(0.2, 0.28), h * rng.uniform(0.18, 0.26)
        body = _rand_color(rng, 30, 200)
        draw.ellipse((mx, my, w - mx, h - my), fill=body)
        draw.rectangle((w * 0.4, h * 0.35, w * 0.6, h * 0.8), fill=_rand_color(rng, 20, 180))
        draw.ellipse((w * 0.45, h * 0.6, w * 0.55, h * 0.85), fill=(tone - 30,) * 3)  # 그림자
        cell = _add_noise(cell, 3)
        return cell.filter(ImageFilter.GaussianBlur(0.8))

    cell = _vertical_gradient(size, _rand_color(rng), _rand_color(rng))
    draw = ImageDraw.Draw(cell)
    for _ in range(rng.randrange(5, 10)):
        x0, y0 = rng.uniform(-0.2, 0.9) * w, rng.uniform(-0.2, 0.9) * h
        x1, y1 = x0 + rng.uniform(0.15, 0.6) * w, y0 + rng.uniform(0.15, 0.6) * h
        color = _rand_color(rng, 0, 255)
        shape = rng.randrange(3)
        if shape == 0:
            draw.ellipse((x0, y0, x1, y1), fill=color)
        elif shape == 1:
            draw.rectangle((x0, y0, x1, y1), fill=color)
        else:
            draw.polygon([(x0, y1), ((x0 + x1) / 2, y0), (x1, y1)], fill=color)
    cell = _add_noise(cell, 10)
    return cell.filter(ImageFilter.GaussianBlur(1.0))


def render(sample: Sample) -> tuple[Image.Image, list[list[int]]]:
    rng = random.Random(sample.seed)
    width = sample.border * 2 + sum(sample.cols) + sample.gutter * (len(sample.cols) - 1)
    height = sample.border * 2 + sum(sample.rows) + sample.gutter * (len(sample.rows) - 1)
    image = make_background(sample, (width, height), rng)
    rects: list[list[int]] = []
    y = sample.border
    for ch in sample.rows:
        x = sample.border
        for cw in sample.cols:
            image.paste(make_cell((cw, ch), rng, sample.content), (x, y))
            rects.append([x, y, x + cw, y + ch])
            x += cw + sample.gutter
        y += ch + sample.gutter
    return image, rects


def _even(total: int, parts: int, gutter: int, border: int) -> list[int]:
    inner = total - 2 * border - gutter * (parts - 1)
    base = inner // parts
    sizes = [base] * parts
    sizes[-1] += inner - base * parts
    return sizes


WHITE, BLACK, GRAY = (255, 255, 255), (0, 0, 0), (128, 128, 128)


def sample_list() -> list[Sample]:
    s: list[Sample] = []

    def add(name, desc, size, grid, gutter, border, **kw):
        w, h = size
        r, c = grid
        cols = kw.pop("cols", None) or _even(w, c, gutter, border)
        rows = kw.pop("rows", None) or _even(h, r, gutter, border)
        s.append(Sample(name, desc, cols, rows, gutter, border, seed=len(s) + 1, **kw))

    add("01_white_2x2", "흰 여백 16px, 바깥 테두리 있음", (1024, 1024), (2, 2), 16, 16)
    add("02_black_2x2", "검정 여백 12px, 테두리 없음", (1024, 1024), (2, 2), 12, 0, colors=(BLACK,))
    add("03_gray_3x3", "회색 여백 10px, 테두리 10px", (1200, 1200), (3, 3), 10, 10, colors=(GRAY,))
    add("04_vgrad_2x2", "위아래 그라데이션 여백 20px, 테두리 20px", (1024, 1024), (2, 2), 20, 20,
        background="vgrad", colors=((170, 200, 240), (240, 170, 200)))
    add("05_dgrad_3x3", "대각선 그라데이션 여백 14px, 테두리 없음", (1200, 1200), (3, 3), 14, 0,
        background="dgrad", colors=((30, 30, 60), (230, 220, 180)))
    add("06_noise_2x2", "잡음 무늬 여백 18px(종이 질감), 테두리 18px", (1024, 1024), (2, 2), 18, 18,
        background="noise", colors=((225, 215, 200),), extra={"sigma": 18})
    add("07_stripes_3x3", "대각선 줄무늬 여백 16px, 테두리 16px", (1200, 1200), (3, 3), 16, 16,
        background="stripes", colors=((240, 240, 240), (200, 200, 220)), extra={"period": 8})
    add("08_hstripes_3x3", "가로 줄무늬 여백 12px, 테두리 없음", (1200, 1200), (3, 3), 12, 0,
        background="hstripes", colors=((250, 250, 250), (190, 190, 190)), extra={"period": 6})
    add("09_thin2_2x2", "아주 얇은 흰 여백 2px, 테두리 없음", (1024, 1024), (2, 2), 2, 0)
    add("10_thin3_3x3", "아주 얇은 검정 여백 3px, 테두리 3px", (1200, 1200), (3, 3), 3, 3, colors=(BLACK,))
    add("11_thin4_jpeg_2x2", "얇은 흰 여백 4px + JPEG 85", (1024, 1024), (2, 2), 4, 0, jpeg=85)
    # 붙은 칸은 크기를 조금씩 달리한다(같은 크기면 같은 간격 나누기로도 우연히 맞으므로).
    add("12_touch_2x2", "여백 없이 붙은 칸(크기 조금 다름)", (1024, 1024), (2, 2), 0, 0, cols=[470, 554], rows=[540, 484])
    add("13_touch_3x3", "여백 없이 붙은 칸 3×3(크기 조금 다름)", (1200, 1200), (3, 3), 0, 0,
        cols=[380, 420, 400], rows=[420, 370, 410])
    add("14_uneven_2x2", "칸 크기가 고르지 않음(가로 44:56, 세로 58:42), 흰 여백 12px", (1024, 1024), (2, 2), 12, 0,
        cols=[445, 567], rows=[588, 424])
    add("15_uneven_3x3", "칸 크기가 고르지 않음, 회색 여백 8px, 테두리 8px", (1200, 1200), (3, 3), 8, 8,
        colors=(GRAY,), cols=[440, 340, 388], rows=[350, 430, 388])
    add("16_jpeg70_2x2", "흰 여백 10px, 테두리 10px, JPEG 70", (1024, 1024), (2, 2), 10, 10, jpeg=70)
    add("17_jpeg75_3x3", "검정 여백 8px, JPEG 75", (1200, 1200), (3, 3), 8, 0, colors=(BLACK,), jpeg=75)
    add("18_whitebg_2x2", "흰 바탕 사진 + 흰 여백 16px, 테두리 16px", (1024, 1024), (2, 2), 16, 16, content="whitebg")
    add("19_whitebg_3x3", "흰 바탕 사진 + 흰 여백 12px, 테두리 없음", (1200, 1200), (3, 3), 12, 0, content="whitebg")
    add("20_tall_2x2", "세로로 긴 그림 832×1248, 흰 여백 10px", (832, 1248), (2, 2), 10, 0)
    add("21_tall_3x3", "세로로 긴 그림 768×1344, 짙은 여백 8px, 테두리 8px", (768, 1344), (3, 3), 8, 8,
        colors=((24, 24, 28),))
    add("22_big_jpeg_2x2", "큰 그림 2048×2048, 흰 여백 24px, JPEG 80", (2048, 2048), (2, 2), 24, 0, jpeg=80)
    add("23_touch_jpeg_3x3", "여백 없이 붙은 칸 3×3(크기 조금 다름) + JPEG 80", (1200, 1200), (3, 3), 0, 0, jpeg=80,
        cols=[410, 380, 410], rows=[390, 420, 390])
    add("24_noise_uneven_jpeg_2x2", "잡음 무늬 여백 14px + 고르지 않은 칸 + JPEG 80", (1024, 1024), (2, 2), 14, 14,
        background="noise", colors=((60, 60, 70),), extra={"sigma": 20}, jpeg=80, cols=[540, 442], rows=[430, 552])
    # 키우거나 줄인 AI 그림처럼 경계가 흐릿한 것: 그린 뒤 전체를 줄이거나 흐린다.
    add("25_resized_3x3", "흰 여백 12px 3×3을 73%로 줄임(경계가 흐릿함) + JPEG 85", (1400, 1400), (3, 3), 12, 12,
        jpeg=85, extra={"resize": 0.73})
    add("26_soft_2x2", "회색 여백 6px, 그림 전체를 살짝 흐림", (1024, 1024), (2, 2), 6, 0,
        colors=((150, 150, 150),), extra={"blur": 1.2})
    return s


def finish(sample: Sample, image: Image.Image, rects: list[list[int]]) -> tuple[Image.Image, list[list[int]]]:
    """전체 줄이기·흐리기. 줄이면 정답 경계도 같은 비율로 옮긴다."""
    ratio = sample.extra.get("resize")
    if ratio:
        size = (round(image.width * ratio), round(image.height * ratio))
        image = image.resize(size, Image.Resampling.LANCZOS)
        rects = [[round(v * ratio) for v in r] for r in rects]
    blur = sample.extra.get("blur")
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(blur))
    return image, rects


def main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="4칸·9칸 시험 그림 만들기")
    parser.add_argument("out", nargs="?", type=Path, default=DEFAULT_OUT, help="결과 폴더(기본 .scratch/grid_samples)")
    parser.add_argument("--seed", type=int, default=0, help="칸 안 그림을 바꾸는 난수 씨앗(같은 종류를 다른 그림으로 다시 재 볼 때)")
    args = parser.parse_args(argv[1:])
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    samples = sample_list()
    for sample in samples:
        sample.seed += args.seed * 1000
        image, rects = finish(sample, *render(sample))
        suffix = ".jpg" if sample.jpeg else ".png"
        path = out / f"{sample.name}{suffix}"
        if sample.jpeg:
            image.save(path, quality=sample.jpeg)
        else:
            image.save(path)
        truth = {
            "rows": len(sample.rows),
            "cols": len(sample.cols),
            "width": image.width,
            "height": image.height,
            "rects": rects,
            "desc": sample.desc,
        }
        (out / f"{sample.name}.json").write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{path.name}  {image.width}×{image.height}  {sample.desc}")
    print(f"\n시험 그림 {len(samples)}장을 만들었습니다: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
