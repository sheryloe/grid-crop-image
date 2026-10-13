"""Tk 없이 시험할 수 있는 핵심 처리 모음.

- 칸 나누기: 균등 분할, AI 그림의 칸 사이 여백(거터) 자동 찾기
- 배치 설정(JSON) 해석과 좌표 맞추기
- 작업 기록(.crop_history.jsonl): 깨진 줄 건너뛰기, 크기 기준 롤링, 최근 N건 읽기
- 글자 읽기: 내 PC의 Ollama 그림 읽기 모델로 요청 조립·응답 해석
"""

from __future__ import annotations

import base64
import io
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

try:
    from PIL import Image, ImageOps, ImageStat
except ImportError:  # pragma: no cover - app.py가 실행 시 안내한다
    Image = None
    ImageOps = None
    ImageStat = None


__version__ = "1.1.0"  # 프로그램 판 번호(창 제목·배포 압축 파일 이름이 여기서 가져간다)

Rect = tuple[int, int, int, int]

SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
MIN_RECT_SIZE = 4

# ---------------------------------------------------------------------------
# 앱 폴더
# ---------------------------------------------------------------------------


def app_base_dir() -> Path:
    """실행 파일(또는 app.py)이 있는 폴더. 작업 폴더(cwd)와 무관하게 같은 곳을 가리킨다."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _is_writable_dir(path: Path) -> bool:
    probe = path / ".gcs_write_probe"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def app_data_dir() -> Path:
    """기록·설정을 둘 폴더. 실행 파일 폴더에 쓸 수 없으면 사용자 폴더 아래로 옮긴다."""
    base = app_base_dir()
    if _is_writable_dir(base):
        return base
    fallback = Path.home() / ".grid_crop_studio"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


# ---------------------------------------------------------------------------
# 사각형 다루기
# ---------------------------------------------------------------------------


def normalize_rect(rect: Rect) -> Rect:
    left, top, right, bottom = rect
    left, right = sorted((left, right))
    top, bottom = sorted((top, bottom))
    return left, top, right, bottom


def clamp_rects(rects: list[Rect], width: int, height: int, min_size: int = MIN_RECT_SIZE) -> list[Rect]:
    """그림 안으로 자르고, 너무 작거나 겹치는(같은 좌표) 영역은 뺀다."""
    result: list[Rect] = []
    seen: set[Rect] = set()
    for rect in rects:
        left, top, right, bottom = normalize_rect(rect)
        left = min(max(left, 0), width)
        right = min(max(right, 0), width)
        top = min(max(top, 0), height)
        bottom = min(max(bottom, 0), height)
        if right - left < min_size or bottom - top < min_size:
            continue
        key = (left, top, right, bottom)
        if key in seen:
            continue
        seen.add(key)
        result.append(key)
    return result


def scale_rects(rects: list[Rect], from_size: tuple[int, int], to_size: tuple[int, int]) -> list[Rect]:
    from_w, from_h = from_size
    to_w, to_h = to_size
    if from_w <= 0 or from_h <= 0:
        return list(rects)
    rx = to_w / from_w
    ry = to_h / from_h
    return [(round(l * rx), round(t * ry), round(r * rx), round(b * ry)) for l, t, r, b in rects]


@dataclass(frozen=True)
class SharedEdge:
    """이웃한 두 칸이 맞닿은(또는 여백을 사이에 둔) 경계.

    axis='x'는 세로 경계(좌우로 끈다): first의 오른쪽 변과 second의 왼쪽 변.
    axis='y'는 가로 경계(위아래로 끈다): first의 아래 변과 second의 위 변.
    """

    axis: str
    first: int
    second: int


SHARED_EDGE_MIN_OVERLAP = 0.5  # 두 칸이 겹쳐 마주 보는 길이가 짧은 쪽 변의 이 비율 이상이어야 이웃
SHARED_EDGE_MAX_GAP_RATIO = 0.25  # 사이 여백이 작은 칸 크기의 이 비율 이하여야 이웃


def find_shared_edge(rects: list[Rect], x: float, y: float, tolerance: float) -> SharedEdge | None:
    """(x, y) 가까이에 있는 이웃 두 칸의 공유 경계. 경계선 ±tolerance와 사이 여백 안을 잡는다."""
    best: SharedEdge | None = None
    best_dist = float("inf")
    boxes = [normalize_rect(r) for r in rects]
    # 마우스 가까운 칸만 짝지어 본다(50×50칸이어도 마우스를 움직일 때 느려지지 않게)
    near = []
    for i, (l, t, r, b) in enumerate(boxes):
        pad = tolerance + SHARED_EDGE_MAX_GAP_RATIO * max(r - l, b - t)
        if l - pad <= x <= r + pad and t - pad <= y <= b + pad:
            near.append(i)
    for i in near:
        a = boxes[i]
        for j in near:
            b = boxes[j]
            if i == j:
                continue
            for axis in ("x", "y"):
                if axis == "x":
                    a_end, b_start = a[2], b[0]
                    a_len, b_len = a[2] - a[0], b[2] - b[0]
                    cross_lo, cross_hi = max(a[1], b[1]), min(a[3], b[3])
                    shorter = min(a[3] - a[1], b[3] - b[1])
                    along, across = x, y
                else:
                    a_end, b_start = a[3], b[1]
                    a_len, b_len = a[3] - a[1], b[3] - b[1]
                    cross_lo, cross_hi = max(a[0], b[0]), min(a[2], b[2])
                    shorter = min(a[2] - a[0], b[2] - b[0])
                    along, across = y, x
                gap = b_start - a_end
                if gap < -tolerance or gap > max(tolerance, min(a_len, b_len) * SHARED_EDGE_MAX_GAP_RATIO):
                    continue
                if shorter <= 0 or cross_hi - cross_lo < shorter * SHARED_EDGE_MIN_OVERLAP:
                    continue
                if not cross_lo <= across <= cross_hi:
                    continue
                lo, hi = min(a_end, b_start) - tolerance, max(a_end, b_start) + tolerance
                if not lo <= along <= hi:
                    continue
                dist = abs(along - (a_end + b_start) / 2)
                if dist < best_dist:
                    best, best_dist = SharedEdge(axis, i, j), dist
    return best


def move_shared_edge(
    rects: list[Rect], edge: SharedEdge, delta: int, width: int, height: int, min_size: int = MIN_RECT_SIZE
) -> list[Rect]:
    """공유 경계를 delta만큼 옮긴다. 두 칸이 함께 바뀌고 사이 여백 폭은 그대로다.
    어느 칸도 min_size보다 작아지거나 그림 밖으로 나가지 않게 delta를 줄인다."""
    result = [normalize_rect(r) for r in rects]
    a = list(result[edge.first])
    b = list(result[edge.second])
    if edge.axis == "x":
        end_i, start_i, limit = 2, 0, width
        a_lo, b_hi = a[0], b[2]
    else:
        end_i, start_i, limit = 3, 1, height
        a_lo, b_hi = a[1], b[3]
    lowest = (a_lo + min_size) - a[end_i]  # first가 너무 작아지지 않게
    highest = (b_hi - min_size) - b[start_i]  # second가 너무 작아지지 않게
    lowest = max(lowest, -b[start_i])
    highest = min(highest, limit - a[end_i])
    delta = max(lowest, min(highest, delta)) if lowest <= highest else 0
    a[end_i] += delta
    b[start_i] += delta
    result[edge.first] = (a[0], a[1], a[2], a[3])
    result[edge.second] = (b[0], b[1], b[2], b[3])
    return result


def uniform_grid(width: int, height: int, rows: int, cols: int, padding: int = 0) -> list[Rect]:
    """행·열 수대로 균등하게 나눈 영역. padding은 칸 사이와 바깥 여백(픽셀)."""
    if rows < 1 or cols < 1:
        raise ValueError("행과 열은 1 이상이어야 합니다.")
    if padding < 0:
        raise ValueError("여백은 0 이상이어야 합니다.")
    total_x = padding * (cols + 1)
    total_y = padding * (rows + 1)
    if total_x >= width or total_y >= height:
        raise ValueError("여백을 모두 더한 값이 그림 크기보다 큽니다. 여백을 줄여 주세요.")
    cell_w = (width - total_x) / cols
    cell_h = (height - total_y) / rows
    if cell_w < 1 or cell_h < 1:
        raise ValueError("한 칸이 1픽셀보다 작아집니다. 행·열·여백을 줄여 주세요.")
    rects: list[Rect] = []
    for r in range(rows):
        for c in range(cols):
            left = round(padding + c * (cell_w + padding))
            top = round(padding + r * (cell_h + padding))
            right = min(width, round(padding + c * (cell_w + padding) + cell_w))
            bottom = min(height, round(padding + r * (cell_h + padding) + cell_h))
            rects.append((left, top, right, bottom))
    return rects


# ---------------------------------------------------------------------------
# 거터(칸 사이 여백) 찾기
# ---------------------------------------------------------------------------

GUTTER_STD_THRESHOLD = 10.0  # 한 줄의 밝기 표준편차가 이 값 이하면 '고른 띠'로 본다(0~255)
GUTTER_SEARCH_RATIO = 0.25  # 기대 경계에서 칸 크기의 이 비율 안쪽만 찾는다
GUTTER_MAX_WIDTH_RATIO = 0.2  # 칸 크기의 이 비율보다 넓은 띠는 거터가 아니라 배경으로 본다
MARGIN_MAX_RATIO = 0.2  # 바깥 테두리는 그림 변의 이 비율까지만 인정
GUTTER_ANALYSIS_MAX_SIDE = 3000  # 이보다 큰 그림은 줄여서 분석

# 경계선 세기: 줄을 길이 방향으로 토막 내 평균한 뒤, 옆 줄과 토막별 차이의 중앙값.
# 칸 경계는 그림 끝에서 끝까지 곧게 이어지므로 거의 모든 토막에서 차이가 나고,
# 칸 안의 물체 윤곽은 일부 토막에서만 차이가 나서 중앙값이 작다.
# 토막 평균은 잡음·잔무늬를 지우고, 길이 방향 그라데이션은 옆 줄과 같아서 차이가 0이다.
EDGE_SEGMENTS = 32
EDGE_MIN_STRENGTH = 4.0  # 경계로 볼 최소 차이(0~255)
EDGE_REL_STRENGTH = 3.0  # 찾는 범위 안 보통 값(중앙값)의 이 배수 이상이어야 경계
EDGE_PARTNER_RATIO = 0.5  # 여백 안(경계 사이)의 값은 경계 세기의 이 비율 미만이어야 고른 여백
EDGE_PARTNER_MIN_RATIO = 0.1  # 여백의 반대쪽 경계는 센 쪽의 이 비율 이상(칸마다 여백과의 대비가 크게 다르다)
EDGE_BORDER_MIN = 8.0  # 고른 띠 없이 경계선만으로 바깥 테두리를 인정할 최소 세기
EDGE_SNAP = 3  # 고른 띠의 끝을 이 거리(px) 안의 경계선에 맞춘다


@dataclass
class GridSplit:
    rects: list[Rect]
    rows: int
    cols: int
    gutters_found: int
    gutters_expected: int

    @property
    def used_gutters(self) -> bool:
        return self.gutters_found > 0


def line_std_profile(gray: "Image.Image", axis: str) -> list[float]:
    """axis='x'면 세로줄(열)마다, 'y'면 가로줄(행)마다 밝기 표준편차."""
    width, height = gray.size
    if axis == "x":
        return [ImageStat.Stat(gray.crop((x, 0, x + 1, height))).stddev[0] for x in range(width)]
    return [ImageStat.Stat(gray.crop((0, y, width, y + 1))).stddev[0] for y in range(height)]


def line_edge_profile(gray: "Image.Image", axis: str) -> list[float]:
    """axis='x'면 x-1열과 x열 사이, 'y'면 y-1행과 y행 사이의 경계선 세기(0번은 0)."""
    if axis == "y":
        gray = gray.transpose(Image.Transpose.TRANSPOSE)
    width, height = gray.size
    segments = max(1, min(EDGE_SEGMENTS, height // 4))
    data = gray.resize((width, segments), Image.Resampling.BOX).tobytes()
    middle = segments // 2
    profile = [0.0] * width
    for x in range(1, width):
        diffs = sorted(abs(data[r * width + x] - data[r * width + x - 1]) for r in range(segments))
        profile[x] = float(diffs[middle])
    return profile


def _edge_threshold(edges: list[float], lo: int, hi: int) -> float:
    window = sorted(edges[max(lo, 1):hi])
    if not window:
        return EDGE_MIN_STRENGTH
    return max(EDGE_MIN_STRENGTH, window[len(window) // 2] * EDGE_REL_STRENGTH)


def _edge_peaks(edges: list[float], lo: int, hi: int, threshold: float) -> list[int]:
    """lo~hi 안에서 threshold 이상인 봉우리(양옆보다 센 자리)."""
    n = len(edges)
    peaks = []
    for i in range(max(lo, 1), min(hi, n)):
        value = edges[i]
        if value >= threshold and value >= edges[i - 1] and (i + 1 >= n or value > edges[i + 1]):
            peaks.append(i)
    return peaks


# 찾은 여백의 확실한 정도
GAP_BOTH = "both"  # 양쪽 끝 모두 경계선으로 확인
GAP_TOUCH = "touch"  # 여백 없이 붙은 칸(경계선 하나)
GAP_START = "start"  # 앞쪽 끝만 경계선으로 확인(뒤쪽은 고른 띠가 끝나는 자리)
GAP_END = "end"  # 뒤쪽 끝만 확인
GAP_RUN = "run"  # 경계선 없이 고른 띠만
GAP_NONE = "none"  # 못 찾아 같은 간격으로 자름

Gap = tuple[int, int, str]


def _snap_band(edges: list[float], run_s: int, run_e: int, threshold: float) -> Gap:
    """고른 띠 [run_s, run_e)의 양 끝을 가까운 경계선에 맞춘다.

    띠 안팎 EDGE_SNAP 안의 경계선이 둘 이상이면 처음~끝을 여백으로 본다(흰 바탕 칸이
    흰 여백과 붙어 띠가 넓어진 경우 띠 안의 진짜 여백 경계를 고른다).
    """
    peaks = _edge_peaks(edges, run_s - EDGE_SNAP, run_e + EDGE_SNAP + 1, threshold)
    if len(peaks) >= 2:
        return peaks[0], peaks[-1], GAP_BOTH
    if len(peaks) == 1:
        p = peaks[0]
        if abs(p - run_s) <= EDGE_SNAP:
            return p, max(p, run_e), GAP_START
        if abs(p - run_e) <= EDGE_SNAP:
            return min(run_s, p), p, GAP_END
    return run_s, run_e, GAP_RUN


def _edge_band(edges: list[float], lo: int, hi: int, threshold: float, max_width: float) -> Gap | None:
    """고른 띠가 없을 때(무늬·그라데이션 여백, 붙은 칸) 경계선만으로 여백을 찾는다."""
    peaks = _edge_peaks(edges, lo, hi, threshold)
    if not peaks:
        return None
    first = max(peaks, key=edges.__getitem__)
    best: int | None = None
    for other in peaks:
        if not 2 <= abs(other - first) <= max_width:
            continue
        if edges[other] < EDGE_PARTNER_MIN_RATIO * edges[first]:
            continue
        a, b = sorted((first, other))
        inner = edges[a + 2 : b - 1]
        if inner and max(inner) >= EDGE_PARTNER_RATIO * min(edges[first], edges[other]):
            continue  # 사이가 고르지 않으면 여백이 아니다
        if best is None or edges[other] > edges[best]:
            best = other
    if best is None:
        return first, first, GAP_TOUCH
    return min(first, best), max(first, best), GAP_BOTH


def _trim_start(low: list[bool], edges: list[float] | None, limit: int) -> int:
    """앞쪽 바깥 테두리가 끝나는 자리(없으면 0)."""
    n = len(low)
    run = 0
    while run < n and run < limit and low[run]:
        run += 1
    if run >= limit:
        run = 0
    if edges is None:
        return run
    threshold = _edge_threshold(edges, 1, limit)
    if run > 0:
        # 고른 띠 안이나 끝의 가장 센 경계선. 경계선이 없으면 칸 안의 흰 바탕이 띠로 보인 것이다.
        peaks = _edge_peaks(edges, 1, min(run + EDGE_SNAP + 1, limit), threshold)
        return max(peaks, key=edges.__getitem__) if peaks else 0
    # 무늬·그라데이션 테두리: 앞쪽이 고르고(안쪽 값이 경계의 절반 미만) 뚜렷한 경계선 중 가장 센 자리
    best, best_value = 0, 0.0
    for p in _edge_peaks(edges, 1, limit, max(threshold, EDGE_BORDER_MIN)):
        inner = edges[1 : max(1, p - 1)]
        if inner and max(inner) >= EDGE_PARTNER_RATIO * edges[p]:
            continue
        if edges[p] > best_value:
            best, best_value = p, edges[p]
    return best


def _low_run_around(low: list[bool], index: int, start: int, end: int) -> tuple[int, int]:
    """index를 포함하는 '고른 띠' 구간 [s, e)를 start~end 안에서 넓힌다."""
    s = index
    while s > start and low[s - 1]:
        s -= 1
    e = index + 1
    while e < end and low[e]:
        e += 1
    return s, e


@dataclass
class AxisResult:
    """한 축의 분석 결과(분석용으로 줄인 그림 좌표)."""

    n: int
    start: int
    end: int
    gaps: list[Gap]
    edges: list[float] | None = None

    @property
    def found(self) -> int:
        return sum(1 for _s, _e, kind in self.gaps if kind != GAP_NONE)

    def spans(self) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        cursor = self.start
        for gap_s, gap_e, _kind in self.gaps:
            spans.append((cursor, max(cursor, gap_s)))
            cursor = max(cursor, gap_e)
        spans.append((cursor, max(cursor, self.end)))
        return spans


def find_axis_spans(
    stds: list[float],
    parts: int,
    threshold: float = GUTTER_STD_THRESHOLD,
    edges: list[float] | None = None,
) -> tuple[list[tuple[int, int]], int]:
    """한 축을 parts칸으로 나눈 [시작, 끝) 구간들과 찾은 거터 수.

    양 끝의 고른 띠는 바깥 테두리로 보고 잘라 낸다. 칸 경계는 기대 위치 근처의
    고른 띠를 쓰고, 못 찾으면 그 경계만 균등 위치로 나눈다.
    edges(line_edge_profile)를 주면 띠의 끝을 경계선에 맞추고, 고른 띠가 없는
    무늬·그라데이션 여백과 여백 없이 붙은 칸도 경계선으로 찾는다.
    """
    result = analyze_axis(stds, parts, threshold, edges)
    return result.spans(), result.found


def analyze_axis(
    stds: list[float],
    parts: int,
    threshold: float = GUTTER_STD_THRESHOLD,
    edges: list[float] | None = None,
) -> AxisResult:
    n = len(stds)
    if parts < 1:
        raise ValueError("칸 수는 1 이상이어야 합니다.")
    if n == 0:
        return AxisResult(0, 0, 0, [], edges)
    if edges is not None and len(edges) != n:
        raise ValueError("경계선 세기와 표준편차의 길이가 다릅니다.")
    low = [s <= threshold for s in stds]

    limit = max(1, int(n * MARGIN_MAX_RATIO))
    start = _trim_start(low, edges, limit)
    end = n - _trim_start(low[::-1], _reverse_edges(edges), limit)
    if end - start < parts * 2:
        start, end = 0, n

    span = end - start
    cell = span / parts
    window = cell * GUTTER_SEARCH_RATIO
    max_width = cell * GUTTER_MAX_WIDTH_RATIO

    gaps: list[Gap] = []
    for k in range(1, parts):
        expected = start + cell * k
        lo = max(start + 1, int(expected - window))
        hi = min(end - 1, int(expected + window) + 1)
        edge_threshold = _edge_threshold(edges, lo, hi) if edges is not None else 0.0
        best: Gap | None = None
        best_dist = float("inf")
        i = lo
        while i < hi:
            if not low[i]:
                i += 1
                continue
            run_s, run_e = _low_run_around(low, i, start, end)
            i = run_e
            band: Gap = (run_s, run_e, GAP_RUN)
            if edges is not None:
                band = _snap_band(edges, run_s, run_e, edge_threshold)
            if band[1] - band[0] > max_width:
                continue
            dist = abs((band[0] + band[1]) / 2 - expected)
            if dist < best_dist:
                best, best_dist = band, dist
        if best is None and edges is not None:
            best = _edge_band(edges, lo, hi, edge_threshold, max_width)
        if best is None:
            cut = round(expected)
            best = (cut, cut, GAP_NONE)
        gaps.append(best)
    return AxisResult(n, start, end, gaps, edges)


def _reverse_edges(edges: list[float] | None) -> list[float] | None:
    """축을 뒤집었을 때의 경계선 세기(뒤집힌 i번 자리 = 원래 n-i번 자리)."""
    if edges is None:
        return None
    n = len(edges)
    return [0.0] + [edges[n - i] for i in range(1, n)]


def _peak_near(edges: list[float], position: int, minimum: float) -> int | None:
    """position ± EDGE_SNAP 안에서 minimum 이상인 가장 센 경계선 자리."""
    lo = max(1, position - EDGE_SNAP)
    hi = min(len(edges), position + EDGE_SNAP + 1)
    candidates = [i for i in range(lo, hi) if edges[i] >= minimum]
    return max(candidates, key=edges.__getitem__) if candidates else None


def reconcile_axes(results: list[AxisResult]) -> None:
    """AI 격자 그림은 칸 사이 여백 폭과 바깥 테두리 폭이 어디서나 같다는 점으로
    한쪽만 확인된 여백·테두리를 고친다(두 축 결과를 함께 본다)."""
    widths = sorted(e - s for r in results for s, e, kind in r.gaps if kind == GAP_BOTH)
    if not widths:
        widths = [0 for r in results for _s, _e, kind in r.gaps if kind == GAP_TOUCH]
    if widths:
        ref = widths[len(widths) // 2]
        for r in results:
            if r.edges is None:
                continue
            for index, (s, e, kind) in enumerate(r.gaps):
                if kind == GAP_START:
                    peak = _peak_near(r.edges, s + ref, EDGE_MIN_STRENGTH / 2) if ref else None
                    r.gaps[index] = (s, peak if peak is not None else s + ref, GAP_BOTH)
                elif kind == GAP_END:
                    peak = _peak_near(r.edges, e - ref, EDGE_MIN_STRENGTH / 2) if ref else None
                    r.gaps[index] = (peak if peak is not None else e - ref, e, GAP_BOTH)
                elif kind == GAP_TOUCH and ref > 0:
                    # 여백 반대쪽 경계가 약해 붙은 칸으로 보였을 수 있다
                    after = _peak_near(r.edges, s + ref, EDGE_MIN_STRENGTH)
                    before = _peak_near(r.edges, s - ref, EDGE_MIN_STRENGTH)
                    if after is not None and (before is None or r.edges[after] >= r.edges[before]):
                        r.gaps[index] = (s, after, GAP_BOTH)
                    elif before is not None:
                        r.gaps[index] = (before, s, GAP_BOTH)

    borders = [b for r in results for b in (r.start, r.n - r.end) if b > 0]
    if borders:
        ref_border = sorted(borders)[len(borders) // 2]
        for r in results:
            if r.edges is None or r.n < ref_border * 4:
                continue
            if r.start == 0:
                peak = _peak_near(r.edges, ref_border, EDGE_MIN_STRENGTH)
                if peak is not None:
                    r.start = peak
            if r.end == r.n:
                peak = _peak_near(r.edges, r.n - ref_border, EDGE_MIN_STRENGTH)
                if peak is not None:
                    r.end = peak


def split_grid_auto(image: "Image.Image", rows: int, cols: int, detect_gutters: bool = True) -> GridSplit:
    """AI가 한 장에 그린 rows×cols 칸 그림을 나눈다. 거터를 못 찾으면 균등 분할."""
    if rows < 1 or cols < 1:
        raise ValueError("행과 열은 1 이상이어야 합니다.")
    width, height = image.size
    expected = (rows - 1) + (cols - 1)
    if not detect_gutters or width < cols * 2 or height < rows * 2:
        return GridSplit(uniform_grid(width, height, rows, cols), rows, cols, 0, expected)

    gray = image.convert("L")
    scale = 1.0
    longest = max(width, height)
    if longest > GUTTER_ANALYSIS_MAX_SIDE:
        scale = GUTTER_ANALYSIS_MAX_SIDE / longest
        gray = gray.resize((max(1, round(width * scale)), max(1, round(height * scale))), Image.Resampling.BOX)

    x_result = analyze_axis(line_std_profile(gray, "x"), cols, edges=line_edge_profile(gray, "x"))
    y_result = analyze_axis(line_std_profile(gray, "y"), rows, edges=line_edge_profile(gray, "y"))
    reconcile_axes([x_result, y_result])
    x_spans, found_x = x_result.spans(), x_result.found
    y_spans, found_y = y_result.spans(), y_result.found

    def back(value: int, limit: int) -> int:
        return min(limit, max(0, round(value / scale)))

    rects: list[Rect] = []
    for ys, ye in y_spans:
        for xs, xe in x_spans:
            rects.append((back(xs, width), back(ys, height), back(xe, width), back(ye, height)))
    if any(r - l < 1 or b - t < 1 for l, t, r, b in rects):
        return GridSplit(uniform_grid(width, height, rows, cols), rows, cols, 0, expected)
    return GridSplit(rects, rows, cols, found_x + found_y, expected)


def describe_grid_split(split: GridSplit) -> str:
    label = f"{split.rows}×{split.cols} {len(split.rects)}칸"
    if split.gutters_expected == 0:
        return f"{label}으로 나눴습니다."
    if split.gutters_found == split.gutters_expected:
        return f"{label}으로 나눴습니다. 칸 사이 여백을 모두 찾아 그 선을 기준으로 잘랐습니다."
    if split.gutters_found:
        return (
            f"{label}으로 나눴습니다. 칸 사이 여백 {split.gutters_expected}곳 중 "
            f"{split.gutters_found}곳을 찾았고 나머지는 같은 간격으로 잘랐습니다."
        )
    return f"{label}으로 나눴습니다. 칸 사이 여백을 찾지 못해 같은 간격으로 잘랐습니다."


# ---------------------------------------------------------------------------
# 그림 열기·저장
# ---------------------------------------------------------------------------


def open_image_file(path: Path) -> tuple["Image.Image", str | None]:
    """그림을 읽어 메모리로 복사한다. 휴대폰 사진의 회전 정보(EXIF)를 반영한다."""
    with Image.open(path) as source:
        format_name = source.format
        source.load()
        image = ImageOps.exif_transpose(source) or source.copy()
        if image is source:
            image = source.copy()
    return image, format_name


def save_image(image: "Image.Image", target_path: Path, icc_profile: bytes | None = None) -> None:
    suffix = target_path.suffix.lower()
    params: dict[str, object] = {}
    if suffix in {".jpg", ".jpeg"}:
        if image.mode not in {"RGB", "L", "CMYK"}:
            image = image.convert("RGB")
        params.update(quality=95, subsampling=0)
    elif suffix == ".webp":
        params.update(quality=95)
    elif suffix == ".bmp" and image.mode not in {"1", "L", "P", "RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.mode else "RGB")
    elif suffix == ".gif" and image.mode not in {"1", "L", "P", "RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.mode else "RGB")
    if icc_profile and suffix in {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}:
        params["icc_profile"] = icc_profile
    image.save(target_path, **params)


def describe_error(exc: BaseException) -> str:
    """파일·그림 처리 예외를 사용자가 알아듣는 한글로."""
    if Image is not None:
        if isinstance(exc, getattr(Image, "DecompressionBombError", ())):
            return "그림이 너무 커서 열지 않았습니다(픽셀 수 제한)."
        if isinstance(exc, getattr(Image, "UnidentifiedImageError", ())):
            return "그림 파일로 읽을 수 없습니다(손상됐거나 지원하지 않는 형식)."
    if isinstance(exc, FileNotFoundError):
        return "파일이나 폴더를 찾을 수 없습니다."
    if isinstance(exc, PermissionError):
        return "파일에 접근할 권한이 없습니다(다른 프로그램이 쓰는 중이거나 읽기 전용)."
    if isinstance(exc, OSError):
        return f"파일 처리 중 문제가 생겼습니다: {exc}"
    if isinstance(exc, (ValueError, OcrError)):
        return str(exc)
    return f"예상하지 못한 문제가 생겼습니다: {exc}"


def suffix_from_format(format_name: str | None) -> str:
    mapping = {
        "PNG": ".png",
        "JPEG": ".jpg",
        "JPG": ".jpg",
        "MPO": ".jpg",
        "BMP": ".bmp",
        "GIF": ".gif",
        "WEBP": ".webp",
        "TIFF": ".tiff",
        "TIF": ".tif",
    }
    return mapping.get((format_name or "").strip().upper(), ".png")


def build_output_path(output_dir: Path, base_name: str, suffix: str) -> Path:
    target = output_dir / f"{base_name}{suffix}"
    attempt = 1
    while target.exists():
        target = output_dir / f"{base_name}_{attempt}{suffix}"
        attempt += 1
    return target


GENERATED_CROP_PATTERN = re.compile(r"_rect_\d{2,}(_\d+)?$")


def is_generated_crop(path: Path) -> bool:
    """이 프로그램이 저장한 조각(이름_rect_01.png 등)인지."""
    return bool(GENERATED_CROP_PATTERN.search(path.stem))


def collect_images_in_folder(folder: Path) -> list[Path]:
    """폴더(하위 포함)의 그림. 앞서 잘라 저장한 조각은 다시 자르지 않도록 뺀다."""
    found: list[Path] = []
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES and not is_generated_crop(path):
            found.append(path)
    return sorted(found)


# ---------------------------------------------------------------------------
# 배치 설정(JSON)
# ---------------------------------------------------------------------------


class LayoutError(ValueError):
    pass


@dataclass
class Layout:
    rects: list[Rect]
    image_size: tuple[int, int] | None = None
    image_path: str | None = None
    source_kind: str = "file"
    output_dir: str | None = None
    zoom: float = 1.0
    configured: bool = False


def _to_number(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise LayoutError(f"{label} 값이 숫자가 아닙니다.")
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise LayoutError(f"{label} 값이 숫자가 아닙니다: {value!r}") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise LayoutError(f"{label} 값이 올바르지 않습니다.")
    return number


def parse_layout(data: object, require_size: bool = False) -> Layout:
    if not isinstance(data, dict):
        raise LayoutError("배치 파일 형식이 아닙니다(최상위가 객체가 아님).")
    raw_rects = data.get("rectangles")
    if not isinstance(raw_rects, list) or not raw_rects:
        raise LayoutError("배치 파일에 자를 영역이 없습니다.")
    rects: list[Rect] = []
    for index, item in enumerate(raw_rects, start=1):
        if not isinstance(item, dict):
            raise LayoutError(f"{index}번 영역의 형식이 올바르지 않습니다.")
        values = [round(_to_number(item.get(key, 0), f"{index}번 영역의 {key}")) for key in ("left", "top", "right", "bottom")]
        rects.append((values[0], values[1], values[2], values[3]))

    image_size: tuple[int, int] | None = None
    size_info = data.get("image_size")
    if isinstance(size_info, dict) and size_info.get("width") is not None and size_info.get("height") is not None:
        width = round(_to_number(size_info.get("width"), "그림 너비"))
        height = round(_to_number(size_info.get("height"), "그림 높이"))
        if width <= 0 or height <= 0:
            raise LayoutError("배치 파일의 그림 크기가 0 이하입니다.")
        image_size = (width, height)
    elif require_size:
        raise LayoutError("배치 파일에 원본 그림 크기 정보가 없습니다.")

    zoom_raw = data.get("zoom")
    try:
        zoom = float(zoom_raw) if zoom_raw is not None else 1.0
    except (TypeError, ValueError):
        zoom = 1.0
    if not zoom > 0:
        zoom = 1.0

    image_path = data.get("image_path")
    output_dir = data.get("output_dir")
    return Layout(
        rects=rects,
        image_size=image_size,
        image_path=str(image_path) if isinstance(image_path, str) and image_path else None,
        source_kind=str(data.get("image_source_kind") or "file"),
        output_dir=str(output_dir) if isinstance(output_dir, str) and output_dir else None,
        zoom=zoom,
        configured=bool(data.get("configured")),
    )


def load_layout_file(path: Path, require_size: bool = False) -> Layout:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise LayoutError(f"배치 파일을 읽지 못했습니다: {exc}") from None
    except UnicodeDecodeError:
        raise LayoutError("배치 파일이 UTF-8 글자가 아닙니다.") from None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LayoutError(f"배치 파일의 JSON이 깨졌습니다({exc.lineno}번째 줄).") from None
    return parse_layout(data, require_size=require_size)


def write_text_atomic(path: Path, text: str) -> None:
    """같은 폴더의 임시 파일에 다 쓴 뒤 바꿔치기한다(쓰다 끊겨도 원본이 남는다)."""
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fp:
        fp.write(text)
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# 작업 기록
# ---------------------------------------------------------------------------

HISTORY_FILENAME = ".crop_history.jsonl"
HISTORY_MAX_BYTES = 5 * 1024 * 1024
HISTORY_KEEP_ARCHIVES = 3
HISTORY_MAX_SAVED_PATHS = 200
_history_lock = threading.Lock()

JOB_TYPE_LABELS = {"single": "한 장", "batch": "여러 장", "ocr": "글자 읽기"}


def history_archive_path(path: Path, number: int) -> Path:
    return path.with_name(f"{path.stem}.{number}{path.suffix}")


def history_files(path: Path, keep: int = HISTORY_KEEP_ARCHIVES) -> list[Path]:
    """최신 파일부터: 본 파일, .1, .2, ..."""
    return [path] + [history_archive_path(path, i) for i in range(1, keep + 1)]


def rotate_history(path: Path, max_bytes: int = HISTORY_MAX_BYTES, keep: int = HISTORY_KEEP_ARCHIVES) -> bool:
    try:
        if path.stat().st_size < max_bytes:
            return False
    except FileNotFoundError:
        return False
    keep = max(1, keep)
    oldest = history_archive_path(path, keep)
    if oldest.exists():
        oldest.unlink()
    for number in range(keep - 1, 0, -1):
        src = history_archive_path(path, number)
        if src.exists():
            os.replace(src, history_archive_path(path, number + 1))
    os.replace(path, history_archive_path(path, 1))
    return True


def make_history_entry(
    job_type: str,
    source_images: list[str],
    output_dir: Path | str | None,
    saved_paths: list[Path],
    rectangles_count: int,
    details: dict[str, object] | None = None,
    timestamp: str | None = None,
) -> dict[str, object]:
    from datetime import datetime

    entry: dict[str, object] = {
        "timestamp": timestamp or datetime.now().isoformat(timespec="seconds"),
        "job_type": job_type,
        "source_images": source_images[:HISTORY_MAX_SAVED_PATHS],
        "source_count": len(source_images),
        "output_dir": str(output_dir) if output_dir is not None else None,
        "saved_paths": [str(p) for p in saved_paths[:HISTORY_MAX_SAVED_PATHS]],
        "saved_count": len(saved_paths),
        "rectangles_count": rectangles_count,
    }
    if len(saved_paths) > HISTORY_MAX_SAVED_PATHS:
        entry["saved_paths_truncated"] = True
    if details is not None:
        entry["details"] = details
    return entry


def append_history(
    path: Path,
    entry: dict[str, object],
    max_bytes: int = HISTORY_MAX_BYTES,
    keep: int = HISTORY_KEEP_ARCHIVES,
) -> None:
    """한 줄을 한 번에 덧붙인다. 크기가 넘으면 먼저 롤링하고, 앞 줄이 끊겨 있으면 줄을 바꿔 붙인다."""
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    with _history_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        rotate_history(path, max_bytes, keep)
        prefix = b""
        try:
            with open(path, "rb") as fp:
                fp.seek(0, os.SEEK_END)
                if fp.tell() > 0:
                    fp.seek(-1, os.SEEK_END)
                    if fp.read(1) != b"\n":
                        prefix = b"\n"
        except FileNotFoundError:
            pass
        with open(path, "ab") as fp:
            fp.write(prefix + line)
            fp.flush()
            os.fsync(fp.fileno())


def iter_lines_reverse(path: Path, chunk_size: int = 64 * 1024) -> Iterator[bytes]:
    """파일 끝에서부터 한 줄씩(바이트). 큰 파일도 끝부분만 읽는다."""
    with open(path, "rb") as fp:
        fp.seek(0, os.SEEK_END)
        position = fp.tell()
        buffer = b""
        while position > 0:
            size = min(chunk_size, position)
            position -= size
            fp.seek(position)
            buffer = fp.read(size) + buffer
            parts = buffer.split(b"\n")
            buffer = parts[0]
            for part in reversed(parts[1:]):
                yield part
        yield buffer


def parse_history_line(raw: bytes | str) -> dict[str, object] | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def read_recent_history(
    path: Path,
    limit: int = 200,
    skip: int = 0,
    keep: int = HISTORY_KEEP_ARCHIVES,
) -> tuple[list[dict[str, object]], bool]:
    """최신순으로 skip건을 건너뛰고 limit건. 두 번째 값은 더 남았는지."""
    results: list[dict[str, object]] = []
    seen = 0
    for file_path in history_files(path, keep):
        if not file_path.exists():
            continue
        try:
            for raw in iter_lines_reverse(file_path):
                entry = parse_history_line(raw)
                if entry is None:
                    continue
                if seen < skip:
                    seen += 1
                    continue
                if len(results) >= limit:
                    return results, True
                results.append(entry)
        except OSError:
            continue
    return results, False


def safe_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        try:
            return int(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default


# ---------------------------------------------------------------------------
# 글자 읽기(Ollama)
# ---------------------------------------------------------------------------

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
SUGGESTED_VISION_MODEL = "qwen2.5vl:7b"
OCR_TIMEOUT_SEC = 300
OCR_IMAGE_MAX_SIDE = 2048
OCR_IMAGE_MIN_SIDE = 512
OCR_PROMPT = (
    "이 그림에 보이는 글자를 그대로 옮겨 적어 주세요. "
    "줄바꿈은 그림에 보이는 대로 유지하고, 설명·요약·번역은 덧붙이지 마세요. "
    "글자가 없으면 (글자 없음)이라고만 쓰세요."
)
OCR_SETTINGS_FILENAME = ".grid_crop_ocr.json"


class OcrError(Exception):
    """사용자에게 그대로 보여 줄 한글 안내를 담는다."""


def no_vision_model_message(models: list[str]) -> str:
    have = ", ".join(models) if models else "(없음)"
    return (
        "이 PC의 Ollama에 그림을 읽을 수 있는 모델이 없습니다.\n\n"
        f"지금 있는 모델: {have}\n\n"
        "명령창에서 아래처럼 그림 읽기 모델을 받은 뒤 다시 눌러 주세요(약 6GB).\n"
        f"    ollama pull {SUGGESTED_VISION_MODEL}\n\n"
        "받은 뒤 '읽기 설정'에서 모델을 고를 수 있습니다."
    )


def normalize_local_host(host: str) -> str:
    """Ollama 주소를 다듬고, 내 PC·사내망 주소만 허용한다(외부 인터넷으로 보내지 않음)."""
    text = (host or "").strip() or DEFAULT_OLLAMA_HOST
    if "://" not in text:
        text = "http://" + text
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OcrError(f"Ollama 주소 형식이 올바르지 않습니다: {host}\n예: {DEFAULT_OLLAMA_HOST}")
    hostname = parsed.hostname
    if hostname.lower() != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            raise OcrError(
                "Ollama 주소는 내 PC(127.0.0.1, localhost)나 사내망 IP 숫자 주소만 쓸 수 있습니다.\n"
                f"입력한 주소: {host}"
            ) from None
        if not (address.is_loopback or address.is_private):
            raise OcrError(
                "그림을 외부 인터넷으로 보내지 않도록 내 PC나 사내망 주소만 허용합니다.\n"
                f"입력한 주소: {host}"
            )
    try:
        port = parsed.port
    except ValueError:
        raise OcrError(f"Ollama 주소의 포트 번호가 올바르지 않습니다: {host}") from None
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port:
        netloc += f":{port}"
    return f"{parsed.scheme}://{netloc}"


def prepare_ocr_image(image: "Image.Image", max_side: int = OCR_IMAGE_MAX_SIDE, min_side: int = OCR_IMAGE_MIN_SIDE) -> "Image.Image":
    """모델에 보낼 그림: RGB로 바꾸고, 너무 크면 줄이고 너무 작으면 키운다."""
    if image.mode not in {"RGB", "L"}:
        if "A" in image.mode or image.mode == "P":
            rgba = image.convert("RGBA")
            background = Image.new("RGB", rgba.size, (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
    longest = max(image.size)
    if longest > max_side:
        ratio = max_side / longest
    elif longest < min_side:
        ratio = min(4.0, min_side / max(1, longest))
    else:
        return image
    size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
    return image.resize(size, Image.Resampling.LANCZOS)


def image_to_png_base64(image: "Image.Image") -> str:
    buffer = io.BytesIO()
    prepare_ocr_image(image).save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def build_ollama_chat_payload(model: str, image_b64: str, prompt: str = OCR_PROMPT) -> dict[str, object]:
    return {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "stream": False,
        "options": {"temperature": 0},
    }


def parse_ollama_chat_response(data: object) -> str:
    if not isinstance(data, dict):
        raise OcrError("Ollama 응답 형식을 알아보지 못했습니다.")
    if data.get("error"):
        raise OcrError(translate_ollama_error(0, str(data["error"])))
    message = data.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
        raise OcrError("Ollama 응답에 읽은 글자가 없습니다.")
    return message["content"].strip()


def translate_ollama_error(status: int, message: str, model: str = "") -> str:
    lowered = message.lower()
    subject = f"모델 '{model}'" if model else "모델"
    if "not found" in lowered and "model" in lowered:
        return (
            f"{subject}이(가) 이 PC의 Ollama에 없습니다.\n"
            f"명령창에서 ollama pull {model or SUGGESTED_VISION_MODEL} 로 받은 뒤 다시 시도하세요."
        )
    if "unable to load model" in lowered:
        return (
            f"Ollama가 {subject}을(를) 불러오지 못했습니다.\n"
            "이 PC의 Ollama 판이 이 모델을 지원하지 않거나 메모리가 모자랄 수 있습니다.\n"
            f"Ollama를 새 판으로 올리거나 다른 그림 읽기 모델(예: {SUGGESTED_VISION_MODEL})을 고르세요."
        )
    if ("does not support" in lowered and "image" in lowered) or "vision" in lowered:
        return f"{subject}은(는) 그림을 읽지 못합니다. 그림 읽기 모델(예: {SUGGESTED_VISION_MODEL})을 고르세요."
    prefix = f"Ollama가 오류를 돌려주었습니다(상태 {status})." if status else "Ollama가 오류를 돌려주었습니다."
    return f"{prefix}\n서버 메시지: {message}"


def _model_matches(name: str, wanted: str) -> bool:
    if name == wanted:
        return True
    if ":" not in wanted and name == f"{wanted}:latest":
        return True
    return False


class OllamaClient:
    def __init__(self, host: str = DEFAULT_OLLAMA_HOST, timeout: float = OCR_TIMEOUT_SEC, opener: object | None = None) -> None:
        self.base_url = normalize_local_host(host)
        self.timeout = timeout
        # 시스템 프록시를 거치지 않도록 프록시 처리기를 비운다(내 PC로만 보낸다).
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path: str, payload: dict[str, object] | None = None, timeout: float | None = None, model: str = "") -> object:
        url = self.base_url + path
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST" if data is not None else "GET",
        )
        wait = timeout if timeout is not None else self.timeout
        try:
            with self.opener.open(request, timeout=wait) as response:  # type: ignore[attr-defined]
                body = response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read().decode("utf-8", "replace")).get("error", "")
            except Exception:
                detail = str(exc.reason)
            finally:
                exc.close()
            raise OcrError(translate_ollama_error(exc.code, str(detail), model)) from None
        except (socket.timeout, TimeoutError):
            raise OcrError(
                f"Ollama가 {int(wait)}초 안에 답하지 않았습니다.\n"
                "처음 쓰는 모델은 불러오는 데 오래 걸릴 수 있으니 잠시 뒤 다시 눌러 주세요."
            ) from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise OcrError(f"Ollama가 {int(wait)}초 안에 답하지 않았습니다.") from None
            raise OcrError(
                f"Ollama에 연결하지 못했습니다(주소 {self.base_url}).\n"
                "Ollama가 켜져 있는지 확인해 주세요. 시작 메뉴에서 Ollama를 실행하거나 명령창에서 ollama serve 를 실행하면 됩니다."
            ) from None
        except OSError as exc:
            raise OcrError(f"Ollama와 주고받는 중 문제가 생겼습니다: {exc}") from None
        try:
            return json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OcrError("Ollama 응답을 해석하지 못했습니다.") from None

    def list_models(self) -> list[str]:
        data = self._request("/api/tags", timeout=10)
        models = data.get("models", []) if isinstance(data, dict) else []
        return [str(m.get("name") or m.get("model")) for m in models if isinstance(m, dict) and (m.get("name") or m.get("model"))]

    def model_capabilities(self, model: str) -> list[str] | None:
        """모델 능력 목록. 옛 Ollama라 알려 주지 않으면 None."""
        data = self._request("/api/show", {"model": model}, timeout=30, model=model)
        if isinstance(data, dict) and isinstance(data.get("capabilities"), list):
            return [str(c) for c in data["capabilities"]]
        return None

    def vision_models(self) -> list[str]:
        result = []
        for name in self.list_models():
            try:
                caps = self.model_capabilities(name)
            except OcrError:
                continue
            if caps is not None and "vision" in caps:
                result.append(name)
        return result

    def pick_vision_model(self, preferred: str = "") -> str:
        models = self.list_models()
        wanted = (preferred or "").strip()
        if wanted:
            match = next((m for m in models if _model_matches(m, wanted)), None)
            if match is None:
                raise OcrError(
                    f"설정한 모델 '{wanted}'이(가) 이 PC의 Ollama에 없습니다.\n"
                    f"명령창에서 ollama pull {wanted} 로 받거나 '읽기 설정'에서 다른 모델을 고르세요."
                )
            caps = self.model_capabilities(match)
            if caps is not None and "vision" not in caps:
                raise OcrError(
                    f"'{match}'은(는) 그림을 읽지 못하는 모델입니다.\n\n" + no_vision_model_message(models)
                )
            return match
        for name in models:
            try:
                caps = self.model_capabilities(name)
            except OcrError:
                continue
            if caps is not None and "vision" in caps:
                return name
        raise OcrError(no_vision_model_message(models))

    def read_text(self, model: str, image: "Image.Image", prompt: str = OCR_PROMPT) -> str:
        payload = build_ollama_chat_payload(model, image_to_png_base64(image), prompt)
        return parse_ollama_chat_response(self._request("/api/chat", payload, model=model))


@dataclass
class OcrSettings:
    engine: str = "ollama"  # "ollama"(기본) 또는 "cpp"(고급)
    ollama_host: str = DEFAULT_OLLAMA_HOST
    ollama_model: str = ""  # 비우면 그림 읽기 모델을 자동으로 고른다
    timeout_sec: int = OCR_TIMEOUT_SEC
    extra: dict[str, object] = field(default_factory=dict)


def load_ocr_settings(path: Path) -> OcrSettings:
    settings = OcrSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return settings
    if not isinstance(data, dict):
        return settings
    if data.get("engine") in {"ollama", "cpp"}:
        settings.engine = str(data["engine"])
    if isinstance(data.get("ollama_host"), str) and data["ollama_host"].strip():
        settings.ollama_host = data["ollama_host"].strip()
    if isinstance(data.get("ollama_model"), str):
        settings.ollama_model = data["ollama_model"].strip()
    timeout = safe_int(data.get("timeout_sec"), OCR_TIMEOUT_SEC)
    settings.timeout_sec = min(3600, max(10, timeout))
    return settings


def save_ocr_settings(path: Path, settings: OcrSettings) -> None:
    data = asdict(settings)
    data.pop("extra", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, json.dumps(data, ensure_ascii=False, indent=2))


def format_ocr_results(results: list[tuple[str, str]]) -> str:
    """[(영역 이름, 읽은 글자)] → 결과창·텍스트 파일에 쓸 글."""
    blocks = []
    for label, text in results:
        blocks.append(f"[{label}]\n{text.strip() or '(글자 없음)'}")
    return "\n\n".join(blocks) + ("\n" if blocks else "")
