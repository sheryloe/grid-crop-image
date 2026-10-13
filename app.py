from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
import zipfile
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import Listbox
from tkinter import filedialog, messagebox, ttk
from typing import Callable

import gridcrop_core as core

PIL_IMPORT_ERROR: ImportError | None = None
IMAGEGRAB_IMPORT_ERROR: ImportError | None = None

try:
    from PIL import Image, ImageTk
except ImportError as exc:  # pragma: no cover - handled at runtime
    Image = None
    ImageTk = None
    PIL_IMPORT_ERROR = exc

try:
    from PIL import ImageGrab
except ImportError as exc:  # pragma: no cover - handled at runtime
    ImageGrab = None
    IMAGEGRAB_IMPORT_ERROR = exc


APP_TITLE = f"Grid Crop Studio {core.__version__}"
SUPPORTED_FILE_TYPES = [
    ("그림 파일", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
    ("모든 파일", "*.*"),
]
CONFIG_FILE_TYPES = [
    ("배치 파일(JSON)", "*.json"),
    ("모든 파일", "*.*"),
]
TEXT_FILE_TYPES = [
    ("텍스트 파일", "*.txt"),
    ("모든 파일", "*.*"),
]
SUPPORTED_IMAGE_SUFFIXES = core.SUPPORTED_IMAGE_SUFFIXES
MIN_RECT_SIZE = core.MIN_RECT_SIZE
HANDLE_SIZE = 8  # 화면 픽셀 기준
MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
MAX_DISPLAY_PIXELS = 40_000_000  # 확대해도 화면용 그림이 이 픽셀 수를 넘지 않게(메모리 보호)
ZOOM_STEP = 1.25
CONTROL_MASK = 0x0004
SHIFT_MASK = 0x0001
HISTORY_FILENAME = core.HISTORY_FILENAME
HISTORY_PAGE_SIZE = 200
APP_DIR = core.app_base_dir()
DEFAULT_OCR_MODEL_DIR = APP_DIR / "cpp" / "ocr_engine" / "models"
REQUIRED_OCR_MODEL_FILES = ("detector.engine", "recognizer.engine")
CPP_OCR_TIMEOUT_SEC = 600
QUICK_GRIDS = {"4칸": (2, 2), "9칸": (3, 3)}
GRID_RULE_LABELS = {"4칸 (2×2)": (2, 2), "9칸 (3×3)": (3, 3)}
JOB_FILTER_LABELS = {"전체": None, "한 장": "single", "여러 장": "batch", "글자 읽기": "ocr"}


@dataclass
class LoadedImage:
    display_name: str
    save_stem: str
    image: "Image.Image"
    format_name: str | None
    path: Path | None = None
    source_kind: str = "file"

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height


@dataclass
class CropRectangle:
    left: int
    top: int
    right: int
    bottom: int

    def normalized(self) -> "CropRectangle":
        left, right = sorted((self.left, self.right))
        top, bottom = sorted((self.top, self.bottom))
        return CropRectangle(left, top, right, bottom)

    def as_dict(self) -> dict[str, int]:
        rect = self.normalized()
        return {
            "left": rect.left,
            "top": rect.top,
            "right": rect.right,
            "bottom": rect.bottom,
        }

    def as_tuple(self) -> core.Rect:
        return (self.left, self.top, self.right, self.bottom)

    @classmethod
    def from_tuple(cls, rect: core.Rect) -> "CropRectangle":
        return cls(*rect)


@dataclass
class BatchJob:
    files: list[Path]
    output_dir: Path
    create_subfolders: bool
    rects: list[core.Rect] | None = None
    source_size: tuple[int, int] | None = None
    grid: tuple[int, int] | None = None
    detect_gutters: bool = True

    def describe_rule(self) -> str:
        if self.grid is not None:
            rows, cols = self.grid
            return f"AI 그림 {rows * cols}칸 자동 나누기"
        return f"영역 {len(self.rects or [])}개"


class AutoCropApp:
    HANDLE_CURSORS = {
        "top-left": "size_nw_se",
        "top-right": "size_ne_sw",
        "bottom-left": "size_ne_sw",
        "bottom-right": "size_nw_se",
        "top": "sb_v_double_arrow",
        "bottom": "sb_v_double_arrow",
        "left": "sb_h_double_arrow",
        "right": "sb_h_double_arrow",
    }

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        # 작은 화면(노트북 125% 배율 등)에서도 창이 화면 밖으로 넘치지 않게 맞춘다.
        screen_w = max(800, self.root.winfo_screenwidth())
        screen_h = max(600, self.root.winfo_screenheight())
        width = min(1440, screen_w - 40)
        height = min(940, screen_h - 80)
        self.root.geometry(f"{width}x{height}+{max(0, (screen_w - width) // 2)}+{max(0, (screen_h - height) // 3)}")
        self.root.minsize(min(1080, width), min(640, height))

        self.loaded_image: LoadedImage | None = None
        self.photo_image: "ImageTk.PhotoImage | None" = None
        self.canvas_image_id: int | None = None
        self.zoom = 1.0
        self.output_dir: Path | None = None
        self.output_dir_is_user_selected = False

        self.rectangles: list[CropRectangle] = []
        self.selected_rectangle_index: int | None = None
        self.drag_context: dict[str, object] | None = None
        self.is_configured = False
        self.last_batch_job: BatchJob | None = None
        self.last_batch_failures: list[Path] = []
        self.data_dir = core.app_data_dir()
        self.history_path = self.data_dir / HISTORY_FILENAME
        self.ocr_settings_path = self.data_dir / core.OCR_SETTINGS_FILENAME
        self.ocr_settings = core.load_ocr_settings(self.ocr_settings_path)
        self.ocr_running = False
        self.detect_gutters_var = tk.BooleanVar(value=True)
        self.last_grid_message = ""
        # 작업 스레드는 화면을 직접 만지지 않고 이 줄에 할 일을 넣는다(Tk는 주 스레드에서만).
        self.ui_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()

        self.zoom_var = tk.StringVar(value="100%")
        self.output_dir_var = tk.StringVar(value="아직 정하지 않음")
        self.status_var = tk.StringVar(
            value="사진을 열거나 붙여넣으면 바로 자르기 작업을 시작할 수 있습니다."
        )
        self.instruction_var = tk.StringVar(
            value=(
                "빈 화면에서 드래그하면 자를 영역이 생깁니다. 영역 안을 끌면 이동하고, 모서리를 끌면 크기가 바뀝니다. "
                "4칸·9칸으로 나눈 뒤 두 칸 사이 경계를 끌면 두 칸이 함께 맞춰집니다. "
                "Shift를 누르면 정사각형으로 고정되고, Ctrl+마우스휠로 확대/축소할 수 있습니다."
            )
        )
        self.image_summary_var = tk.StringVar(value="사진이 아직 없습니다")
        self.selection_summary_var = tk.StringVar(value="영역 0개")
        self.workspace_summary_var = tk.StringVar(value="저장 폴더를 정하면 바로 저장할 수 있습니다.")
        self.mode_summary_var = tk.StringVar(value="사진 기다리는 중")

        self._setup_styles()
        self._build_ui()
        self._bind_events()
        self._show_placeholder()
        self._update_controls()
        self.root.after(100, self._drain_ui_queue)

    # ------------------------------------------------------------------
    # 스레드 → 화면
    # ------------------------------------------------------------------

    def _post(self, callback: Callable[[], None]) -> None:
        self.ui_queue.put(callback)

    def _drain_ui_queue(self) -> None:
        try:
            while True:
                callback = self.ui_queue.get_nowait()
                try:
                    callback()
                except tk.TclError:
                    pass  # 그새 닫힌 창을 만지려던 경우
        except queue.Empty:
            pass
        self.root.after(100, self._drain_ui_queue)

    # ------------------------------------------------------------------
    # 모양
    # ------------------------------------------------------------------

    def _setup_styles(self) -> None:
        self.colors = {
            "bg": "#f3eee6",
            "hero": "#fff7ee",
            "surface": "#ffffff",
            "surface_alt": "#f7f1e8",
            "panel": "#ece4d8",
            "canvas": "#fbfaf7",
            "text": "#1e2430",
            "muted": "#697384",
            "line": "#dacfc1",
            "accent": "#dd6d1f",
            "accent_hover": "#ef8440",
            "cool": "#0e7d84",
            "cool_soft": "#dff2f1",
        }

        self.root.configure(bg=self.colors["bg"])

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure(
            ".",
            background=self.colors["bg"],
            foreground=self.colors["text"],
            fieldbackground=self.colors["surface_alt"],
            bordercolor=self.colors["line"],
            lightcolor=self.colors["line"],
            darkcolor=self.colors["line"],
            troughcolor=self.colors["panel"],
            focuscolor=self.colors["accent"],
        )
        style.configure("App.TFrame", background=self.colors["bg"])
        style.configure("Hero.TFrame", background=self.colors["hero"])
        style.configure("Surface.TFrame", background=self.colors["surface"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure("Card.TFrame", background=self.colors["surface_alt"])
        style.configure("HeroTitle.TLabel", background=self.colors["hero"], foreground=self.colors["text"], font=("Bahnschrift SemiBold", 24))
        style.configure("HeroBody.TLabel", background=self.colors["hero"], foreground=self.colors["muted"], font=("Segoe UI", 10))
        style.configure("SectionTitle.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=("Bahnschrift SemiBold", 11))
        style.configure("PanelTitle.TLabel", background=self.colors["surface"], foreground=self.colors["text"], font=("Bahnschrift SemiBold", 13))
        style.configure("CardTitle.TLabel", background=self.colors["surface_alt"], foreground=self.colors["muted"], font=("Segoe UI Semibold", 9))
        style.configure("CardValue.TLabel", background=self.colors["surface_alt"], foreground=self.colors["text"], font=("Segoe UI Semibold", 11))
        style.configure("Hint.TLabel", background=self.colors["surface"], foreground=self.colors["muted"])
        style.configure("SidebarValue.TLabel", background=self.colors["surface_alt"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("SidebarHint.TLabel", background=self.colors["surface_alt"], foreground=self.colors["muted"])
        style.configure("LogoBadge.TLabel", background=self.colors["accent"], foreground="#ffffff", padding=(14, 10), font=("Bahnschrift SemiBold", 14))
        style.configure("MiniTag.TLabel", background=self.colors["cool_soft"], foreground=self.colors["cool"], padding=(8, 3), font=("Segoe UI Semibold", 8))
        style.configure("Pill.TLabel", background=self.colors["accent"], foreground="#ffffff", padding=(10, 4), font=("Segoe UI Semibold", 9))
        style.configure("PillMuted.TLabel", background=self.colors["cool_soft"], foreground=self.colors["cool"], padding=(10, 4), font=("Segoe UI Semibold", 9))
        style.configure("Status.TLabel", background=self.colors["hero"], foreground=self.colors["text"], padding=(12, 10))

        # width=-2: 테마 기본값(최소 11글자 폭) 대신 글자 길이만큼만 차지해 버튼 줄이 잘리지 않게 한다.
        style.configure("Action.TButton", background=self.colors["surface"], foreground=self.colors["text"], padding=(10, 7), width=-2, relief="solid", borderwidth=1, font=("Segoe UI Semibold", 9))
        style.map(
            "Action.TButton",
            background=[("active", "#fff2e7"), ("disabled", self.colors["surface_alt"])],
            foreground=[("disabled", "#9e9a92")],
            bordercolor=[("active", self.colors["accent"]), ("!active", self.colors["line"])],
            lightcolor=[("active", self.colors["accent"]), ("!active", self.colors["line"])],
            darkcolor=[("active", self.colors["accent"]), ("!active", self.colors["line"])],
        )
        style.configure("Accent.TButton", background=self.colors["accent"], foreground="#ffffff", padding=(12, 8), width=-2, relief="flat", borderwidth=0, font=("Bahnschrift SemiBold", 10))
        style.map(
            "Accent.TButton",
            background=[("active", self.colors["accent_hover"]), ("disabled", "#dcb99d")],
            foreground=[("disabled", "#fff8f2")],
            bordercolor=[("active", "#c65f18"), ("!active", self.colors["accent"])],
        )
        style.configure("TEntry", padding=6, fieldbackground=self.colors["surface_alt"], foreground=self.colors["text"])
        style.configure("TCombobox", padding=6, fieldbackground=self.colors["surface_alt"], foreground=self.colors["text"], arrowsize=14)
        style.map("TCombobox", fieldbackground=[("readonly", self.colors["surface_alt"])], foreground=[("readonly", self.colors["text"])])
        style.configure("TCheckbutton", background=self.colors["surface"], foreground=self.colors["text"])
        style.configure("Card.TCheckbutton", background=self.colors["surface_alt"], foreground=self.colors["text"])
        style.configure("TRadiobutton", background=self.colors["surface"], foreground=self.colors["text"])
        style.configure("TScrollbar", background=self.colors["surface_alt"], troughcolor=self.colors["panel"], arrowsize=13)
        style.configure("Horizontal.TProgressbar", background=self.colors["accent"], troughcolor=self.colors["panel"], borderwidth=0)
        style.configure("TLabelframe", background=self.colors["surface"], foreground=self.colors["text"], bordercolor=self.colors["line"])
        style.configure("TLabelframe.Label", background=self.colors["surface"], foreground=self.colors["text"], font=("Segoe UI Semibold", 10))
        style.configure("TNotebook", background=self.colors["surface"], borderwidth=0)
        style.configure("TNotebook.Tab", background=self.colors["surface_alt"], foreground=self.colors["muted"], padding=(12, 8))
        style.map("TNotebook.Tab", background=[("selected", self.colors["accent"]), ("active", self.colors["cool_soft"])], foreground=[("selected", "#ffffff"), ("active", self.colors["text"])])
        style.configure("TSeparator", background=self.colors["line"])

    def _create_button_group(self, parent: ttk.Frame, tag: str, title: str) -> ttk.Frame:
        shell = ttk.Frame(parent, style="Surface.TFrame", padding=(14, 12))
        header = ttk.Frame(shell, style="Surface.TFrame")
        header.pack(fill="x")
        ttk.Label(header, text=tag, style="MiniTag.TLabel").pack(side="left")
        ttk.Label(header, text=title, style="SectionTitle.TLabel").pack(side="left", padx=(8, 0))
        row = ttk.Frame(shell, style="Surface.TFrame")
        row.pack(fill="x", pady=(10, 0))
        return row

    def _make_clickable(self, *widgets: ttk.Button) -> None:
        for widget in widgets:
            widget.configure(cursor="hand2")

    def _style_dialog(self, dialog: tk.Toplevel) -> None:
        dialog.configure(bg=self.colors["bg"])

    def _style_listbox(self, widget: tk.Listbox) -> None:
        widget.configure(
            bg=self.colors["surface_alt"],
            fg=self.colors["text"],
            selectbackground=self.colors["accent"],
            selectforeground=self.colors["bg"],
            highlightbackground=self.colors["line"],
            highlightcolor=self.colors["accent"],
            highlightthickness=1,
            relief="flat",
            borderwidth=0,
            activestyle="none",
        )

    def _style_text_widget(self, widget: tk.Text) -> None:
        widget.configure(
            bg=self.colors["surface_alt"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            selectbackground=self.colors["accent"],
            selectforeground=self.colors["bg"],
            highlightbackground=self.colors["line"],
            highlightcolor=self.colors["accent"],
            highlightthickness=1,
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=12,
        )

    def _build_ui(self) -> None:
        wrapper = ttk.Frame(self.root, style="App.TFrame", padding=(18, 18, 18, 14))
        wrapper.pack(fill="both", expand=True)
        wrapper.columnconfigure(0, weight=5)
        wrapper.columnconfigure(1, weight=2)
        wrapper.rowconfigure(2, weight=1)

        hero = ttk.Frame(wrapper, style="Hero.TFrame", padding=(18, 10))
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        hero.columnconfigure(0, weight=1)

        hero_brand = ttk.Frame(hero, style="Hero.TFrame")
        hero_brand.grid(row=0, column=0, sticky="w")
        ttk.Label(hero_brand, text="GC", style="LogoBadge.TLabel").pack(side="left")
        title_block = ttk.Frame(hero_brand, style="Hero.TFrame")
        title_block.pack(side="left", padx=(14, 0))
        ttk.Label(title_block, text=APP_TITLE, style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(
            title_block,
            text="여러 장 사진 자르기, AI 그림 칸 나누기, 저장, 글자 읽기를 한 화면에서 빠르게 처리하는 작업 도구입니다.",
            style="HeroBody.TLabel",
            wraplength=840,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        hero_pills = ttk.Frame(hero, style="Hero.TFrame")
        hero_pills.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(hero_pills, textvariable=self.mode_summary_var, style="Pill.TLabel").pack(side="left")
        ttk.Label(hero_pills, textvariable=self.zoom_var, style="PillMuted.TLabel").pack(side="left", padx=(8, 0))

        action_row = ttk.Frame(wrapper, style="App.TFrame")
        action_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        # 무리마다 버튼 수가 달라 같은 비율로 나누면 잘리므로, 필요한 만큼만 쓰고 남는 폭은 마지막 무리가 갖는다.
        action_row.columnconfigure(2, weight=1)

        source_row = self._create_button_group(action_row, "IMG", "사진 가져오기")
        source_row.master.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.open_button = ttk.Button(source_row, text="사진 열기", command=self.open_image, style="Accent.TButton")
        self.open_button.pack(side="left")
        self.paste_button = ttk.Button(source_row, text="붙여넣기", command=self.paste_clipboard_image, style="Action.TButton")
        self.paste_button.pack(side="left", padx=(8, 0))
        self.save_config_button = ttk.Button(source_row, text="저장", command=self.save_configuration, style="Action.TButton")
        self.save_config_button.pack(side="left", padx=(8, 0))
        self.load_config_button = ttk.Button(source_row, text="불러오기", command=self.load_configuration, style="Action.TButton")
        self.load_config_button.pack(side="left", padx=(8, 0))

        process_row = self._create_button_group(action_row, "CUT", "작업 실행")
        process_row.master.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self.batch_button = ttk.Button(process_row, text="여러 장", command=self.open_batch_process_dialog, style="Action.TButton")
        self.batch_button.pack(side="left")
        self.retry_batch_button = ttk.Button(process_row, text="다시", command=self.retry_failed_batch_jobs, style="Action.TButton")
        self.retry_batch_button.pack(side="left", padx=(8, 0))
        self.history_button = ttk.Button(process_row, text="기록", command=self.open_history_viewer, style="Action.TButton")
        self.history_button.pack(side="left", padx=(8, 0))
        self.ocr_button = ttk.Button(process_row, text="글자 읽기", command=self.run_ocr, style="Action.TButton")
        self.ocr_button.pack(side="left", padx=(8, 0))
        self.ocr_settings_button = ttk.Button(process_row, text="읽기 설정", command=self.open_ocr_settings_dialog, style="Action.TButton")
        self.ocr_settings_button.pack(side="left", padx=(8, 0))

        view_row = self._create_button_group(action_row, "VIEW", "화면 조절")
        view_row.master.grid(row=0, column=2, sticky="nsew")
        self.zoom_out_button = ttk.Button(view_row, text="-", command=lambda: self.zoom_by(1 / ZOOM_STEP), style="Action.TButton")
        self.zoom_out_button.pack(side="left")
        self.zoom_in_button = ttk.Button(view_row, text="+", command=lambda: self.zoom_by(ZOOM_STEP), style="Action.TButton")
        self.zoom_in_button.pack(side="left", padx=(8, 0))
        self.zoom_reset_button = ttk.Button(view_row, text="100%", command=self.reset_zoom, style="Action.TButton")
        self.zoom_reset_button.pack(side="left", padx=(8, 0))
        self.zoom_fit_button = ttk.Button(view_row, text="화면 맞춤", command=self.fit_to_view, style="Action.TButton")
        self.zoom_fit_button.pack(side="left", padx=(8, 0))

        canvas_shell = ttk.Frame(wrapper, style="Surface.TFrame", padding=(14, 14, 14, 14))
        canvas_shell.grid(row=2, column=0, sticky="nsew", padx=(0, 14))
        canvas_shell.columnconfigure(0, weight=1)
        canvas_shell.rowconfigure(2, weight=1)

        canvas_header = ttk.Frame(canvas_shell, style="Surface.TFrame")
        canvas_header.grid(row=0, column=0, sticky="ew")
        canvas_header.columnconfigure(0, weight=1)
        ttk.Label(canvas_header, textvariable=self.image_summary_var, style="PanelTitle.TLabel", justify="left").grid(row=0, column=0, sticky="w")
        # 영역을 다루는 버튼은 그림 바로 위에 둔다(윗줄 버튼이 좁은 창에서 잘리지 않게).
        edit_row = ttk.Frame(canvas_header, style="Surface.TFrame")
        edit_row.grid(row=0, column=1, sticky="e", padx=(12, 12))
        self.delete_button = ttk.Button(edit_row, text="지우기", command=self.delete_selected_rectangle, style="Action.TButton")
        self.delete_button.pack(side="left")
        self.clear_button = ttk.Button(edit_row, text="전체 지우기", command=self.clear_rectangles, style="Action.TButton")
        self.clear_button.pack(side="left", padx=(8, 0))
        self.grid_button = ttk.Button(edit_row, text="칸 나누기", command=self.open_grid_generator_dialog, style="Action.TButton")
        self.grid_button.pack(side="left", padx=(8, 0))
        self.configure_button = ttk.Button(edit_row, text="확정", command=self.apply_settings, style="Action.TButton")
        self.configure_button.pack(side="left", padx=(8, 0))
        ttk.Label(canvas_header, textvariable=self.selection_summary_var, style="PillMuted.TLabel").grid(row=0, column=2, sticky="e")

        instruction_label = ttk.Label(canvas_shell, textvariable=self.instruction_var, style="Hint.TLabel", wraplength=980, justify="left")
        instruction_label.grid(row=1, column=0, sticky="ew", pady=(10, 12))

        canvas_frame = ttk.Frame(canvas_shell, style="Surface.TFrame")
        canvas_frame.grid(row=2, column=0, sticky="nsew")
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            canvas_frame,
            background=self.colors["canvas"],
            highlightthickness=1,
            highlightbackground=self.colors["line"],
            highlightcolor=self.colors["accent"],
            relief="flat",
            bd=0,
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")

        y_scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        y_scrollbar.grid(row=0, column=1, sticky="ns")
        x_scrollbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        x_scrollbar.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=x_scrollbar.set, yscrollcommand=y_scrollbar.set)

        sidebar = ttk.Frame(wrapper, style="Panel.TFrame", padding=(14, 14, 14, 14))
        sidebar.grid(row=2, column=1, sticky="nsew")
        sidebar.columnconfigure(0, weight=1)

        # '현재 사진'·'자르는 영역'은 그림 위 머리글에 이미 보이므로 옆 칸에서는 뺐다.
        # 작은 화면에서도 '잘라서 저장'이 보이도록 저장 폴더 → AI 칸 나누기 → 저장 버튼 → 도움말 순으로 둔다.
        output_card = ttk.Frame(sidebar, style="Card.TFrame", padding=(12, 12))
        output_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        output_card.columnconfigure(0, weight=1)
        ttk.Label(output_card, text="저장 폴더", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(output_card, textvariable=self.output_dir_var, style="CardValue.TLabel", wraplength=250, justify="left").grid(row=1, column=0, sticky="w", pady=(6, 10))
        action_bar = ttk.Frame(output_card, style="Card.TFrame")
        action_bar.grid(row=2, column=0, sticky="ew")
        self.output_dir_button = ttk.Button(action_bar, text="저장 폴더", command=self.choose_output_directory, style="Action.TButton")
        self.output_dir_button.pack(side="left")
        self.set_cwd_button = ttk.Button(action_bar, text="현재 폴더", command=self.set_output_to_cwd, style="Action.TButton")
        self.set_cwd_button.pack(side="left", padx=(8, 0))

        quick_card = ttk.Frame(sidebar, style="Card.TFrame", padding=(12, 12))
        quick_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(quick_card, text="AI 그림 빠르게 나누기", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(
            quick_card,
            text="한 장에 4칸·9칸으로 그린 그림을 바로 나눠 저장합니다.",
            style="SidebarHint.TLabel",
            wraplength=250,
            justify="left",
        ).pack(anchor="w", pady=(6, 8))
        quick_bar = ttk.Frame(quick_card, style="Card.TFrame")
        quick_bar.pack(anchor="w")
        self.quick_grid_buttons: list[ttk.Button] = []
        for label, (rows, cols) in QUICK_GRIDS.items():
            button = ttk.Button(
                quick_bar,
                text=label,
                command=lambda r=rows, c=cols: self.quick_split(r, c),
                style="Action.TButton",
            )
            button.pack(side="left", padx=(0 if not self.quick_grid_buttons else 8, 0))
            self.quick_grid_buttons.append(button)
        ttk.Checkbutton(
            quick_card,
            text="칸 사이 여백 찾아 나누기",
            variable=self.detect_gutters_var,
            style="Card.TCheckbutton",
        ).pack(anchor="w", pady=(8, 0))

        focus_card = ttk.Frame(sidebar, style="Card.TFrame", padding=(12, 12))
        focus_card.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(focus_card, text="바로 하기", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(focus_card, textvariable=self.workspace_summary_var, style="SidebarValue.TLabel", wraplength=250, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(
            focus_card,
            text="바로 가기: Ctrl+V 붙여넣기, Ctrl+휠 확대/축소, Shift 정사각형, Delete 영역 지우기, Esc 끌기 취소",
            style="SidebarHint.TLabel",
            wraplength=250,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        self.split_button = ttk.Button(sidebar, text="잘라서 저장", command=self.split_image, style="Accent.TButton")
        self.split_button.grid(row=2, column=0, sticky="ew")
        self._make_clickable(
            self.open_button,
            self.paste_button,
            self.save_config_button,
            self.load_config_button,
            self.batch_button,
            self.retry_batch_button,
            self.history_button,
            self.ocr_button,
            self.ocr_settings_button,
            *self.quick_grid_buttons,
            self.zoom_out_button,
            self.zoom_in_button,
            self.zoom_reset_button,
            self.zoom_fit_button,
            self.delete_button,
            self.clear_button,
            self.grid_button,
            self.configure_button,
            self.output_dir_button,
            self.set_cwd_button,
            self.split_button,
        )

        status_bar = ttk.Label(wrapper, textvariable=self.status_var, style="Status.TLabel", anchor="w", justify="left")
        status_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0))

    def _bind_events(self) -> None:
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<ButtonPress-3>", self.on_right_press)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.root.bind("<Delete>", lambda _event: self.delete_selected_rectangle())
        self.root.bind("<Escape>", lambda _event: self.cancel_current_drag())
        self.root.bind("<Control-v>", self.paste_clipboard_image)
        self.root.bind("<Control-V>", self.paste_clipboard_image)

    def _show_placeholder(self) -> None:
        self.canvas.delete("all")
        self.canvas_image_id = None
        self.canvas.create_rectangle(140, 120, 900, 560, outline=self.colors["line"], width=2, dash=(8, 8))
        self.canvas.create_text(
            520,
            300,
            text="사진을 열거나 붙여넣어서 시작하세요",
            fill=self.colors["text"],
            font=("Bahnschrift SemiBold", 24),
        )
        self.canvas.create_text(
            520,
            352,
            text="영역을 그린 뒤 한 번에 잘라 저장할 수 있습니다.",
            fill=self.colors["muted"],
            font=("Segoe UI", 12),
        )
        self.canvas.configure(scrollregion=(0, 0, 1040, 700))

    def _update_controls(self) -> None:
        has_image = self.loaded_image is not None
        has_rectangles = bool(self.rectangles)
        has_output_dir = self.output_dir is not None and self.output_dir.is_dir()

        image_state = "normal" if has_image else "disabled"
        selected_state = "normal" if self.selected_rectangle_index is not None else "disabled"
        split_state = "normal" if has_image and self.is_configured and has_rectangles and has_output_dir else "disabled"

        if not has_image:
            self.canvas.config(cursor="")

        self.paste_button.configure(state="normal")
        self.save_config_button.configure(state=image_state)
        self.load_config_button.configure(state="normal")
        self.batch_button.configure(state="normal")
        retry_state = "normal" if self.last_batch_job and self.last_batch_failures else "disabled"
        self.retry_batch_button.configure(state=retry_state)
        self.history_button.configure(state="normal")
        self.ocr_button.configure(state="disabled" if self.ocr_running else image_state)
        self.ocr_settings_button.configure(state="normal")
        for button in self.quick_grid_buttons:
            button.configure(state=image_state)
        self.zoom_out_button.configure(state=image_state)
        self.zoom_in_button.configure(state=image_state)
        self.zoom_reset_button.configure(state=image_state)
        self.zoom_fit_button.configure(state=image_state)
        self.delete_button.configure(state=selected_state)
        self.clear_button.configure(state=image_state)
        self.grid_button.configure(state=image_state)
        self.configure_button.configure(state=image_state)
        self.output_dir_button.configure(state="normal")
        self.set_cwd_button.configure(state="normal")
        self.split_button.configure(state=split_state)

        if self.loaded_image is None:
            self.image_summary_var.set("사진이 아직 없습니다")
            self.selection_summary_var.set("영역 0개")
            self.mode_summary_var.set("사진 기다리는 중")
        else:
            self.image_summary_var.set(f"{self.loaded_image.display_name}\n{self.loaded_image.width} x {self.loaded_image.height}")
            selection_state = "저장 준비" if self.is_configured and has_rectangles else "고르는 중" if has_rectangles else "비어 있음"
            self.selection_summary_var.set(f"영역 {len(self.rectangles)}개 · {selection_state}")
            if split_state == "normal":
                self.mode_summary_var.set("저장 준비 끝")
            elif has_rectangles:
                self.mode_summary_var.set("영역 고르는 중")
            else:
                self.mode_summary_var.set("사진 불러옴")

        if has_output_dir:
            self.workspace_summary_var.set("지금 바로 저장하거나, 여러 장 자르기와 글자 읽기를 이어서 할 수 있습니다.")
        elif has_image:
            self.workspace_summary_var.set("저장 폴더만 정하면 바로 잘라서 저장할 수 있습니다.")
        else:
            self.workspace_summary_var.set("먼저 사진을 넣고 저장 폴더를 정해 주세요.")

    # ------------------------------------------------------------------
    # 사진 열기·붙여넣기
    # ------------------------------------------------------------------

    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="자를 사진 고르기",
            filetypes=SUPPORTED_FILE_TYPES,
        )
        if not path:
            return

        self._load_image_from_path(Path(path))

    def paste_clipboard_image(self, _event: tk.Event | None = None) -> str | None:
        if ImageGrab is None:
            detail = f"\n{IMAGEGRAB_IMPORT_ERROR}" if IMAGEGRAB_IMPORT_ERROR else ""
            messagebox.showerror("붙여넣기 실패", f"이 환경에서는 클립보드 그림을 쓸 수 없습니다.{detail}")
            return "break"

        try:
            clipboard_content = ImageGrab.grabclipboard()
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("붙여넣기 실패", f"클립보드 그림을 읽지 못했습니다.\n{core.describe_error(exc)}")
            return "break"

        if isinstance(clipboard_content, list):
            image_path = self._find_first_supported_image_path(clipboard_content)
            if image_path is None:
                messagebox.showwarning("붙여넣기 실패", "복사한 파일 중에 열 수 있는 그림 파일이 없습니다.")
                return "break"
            self._load_image_from_path(image_path)
            return "break"

        if clipboard_content is None or not isinstance(clipboard_content, Image.Image):
            messagebox.showwarning("붙여넣기 실패", "클립보드에 그림이 없습니다. 화면을 캡처하거나 그림을 복사한 뒤 다시 눌러 주세요.")
            return "break"

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_stem = f"clipboard_{stamp}"
        copied_image = clipboard_content.copy()
        self._load_image(
            image=copied_image,
            display_name=f"{save_stem}.png",
            save_stem=save_stem,
            format_name="PNG",  # 캡처는 손실 없는 PNG로 저장한다
            source_kind="clipboard",
            source_path=None,
        )
        self.status_var.set(f"클립보드 그림을 불러왔습니다: {copied_image.width} x {copied_image.height}")
        return "break"

    def _load_image_from_path(self, image_path: Path) -> bool:
        try:
            copied_image, format_name = core.open_image_file(image_path)
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("열기 실패", f"사진을 열지 못했습니다.\n{image_path.name}\n{core.describe_error(exc)}")
            return False

        self._load_image(
            image=copied_image,
            display_name=image_path.name,
            save_stem=image_path.stem,
            format_name=format_name,
            source_kind="file",
            source_path=image_path,
        )
        self.status_var.set(f"사진을 불러왔습니다: {image_path.name} ({copied_image.width} x {copied_image.height})")
        return True

    def _load_image(
        self,
        *,
        image: "Image.Image",
        display_name: str,
        save_stem: str,
        format_name: str | None,
        source_kind: str,
        source_path: Path | None,
    ) -> None:
        self.loaded_image = LoadedImage(
            display_name=display_name,
            save_stem=save_stem,
            image=image,
            format_name=format_name,
            path=source_path,
            source_kind=source_kind,
        )
        self.rectangles = []
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = False
        self.zoom = 1.0

        if source_path is not None:
            if not self.output_dir_is_user_selected:
                self._set_output_dir(source_path.parent)
        elif not self.output_dir_is_user_selected:
            self._set_output_dir(None)

        self.root.update_idletasks()
        self.fit_to_view(initial_load=True)
        self._update_controls()

    def _find_first_supported_image_path(self, clipboard_paths: list[object]) -> Path | None:
        for raw_path in clipboard_paths:
            candidate = Path(str(raw_path))
            if candidate.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES and candidate.is_file():
                return candidate
        return None

    # ------------------------------------------------------------------
    # 저장 폴더·배치 파일
    # ------------------------------------------------------------------

    def choose_output_directory(self) -> None:
        initial_dir = self.output_dir
        if initial_dir is None and self.loaded_image and self.loaded_image.path is not None:
            initial_dir = self.loaded_image.path.parent
        if initial_dir is None or not initial_dir.is_dir():
            initial_dir = Path.cwd()

        selected_dir = filedialog.askdirectory(
            title="저장 폴더 고르기",
            initialdir=str(initial_dir),
            mustexist=True,
        )
        if not selected_dir:
            return

        self._set_output_dir(Path(selected_dir), user_selected=True)
        self.status_var.set(f"저장 폴더를 정했습니다: {selected_dir}")

    def set_output_to_cwd(self) -> None:
        """저장 폴더를 지금 작업 폴더로 정한다."""
        cwd = Path.cwd()
        self._set_output_dir(cwd, user_selected=True)
        self.status_var.set(f"저장 폴더를 현재 폴더로 정했습니다: {cwd}")

    def _set_output_dir(self, path: Path | None, user_selected: bool = False) -> None:
        self.output_dir = path
        self.output_dir_is_user_selected = user_selected
        if self.output_dir is None:
            self.output_dir_var.set("아직 정하지 않음")
        else:
            self.output_dir_var.set(str(self.output_dir))
        self._update_controls()

    def save_configuration(self) -> None:
        if not self.loaded_image:
            return

        initial_path = self._get_default_config_path()
        target = filedialog.asksaveasfilename(
            title="배치 저장",
            initialdir=str(initial_path.parent),
            initialfile=initial_path.name,
            defaultextension=".json",
            filetypes=CONFIG_FILE_TYPES,
        )
        if not target:
            return

        data = {
            "version": 3,
            "image_path": str(self.loaded_image.path.resolve()) if self.loaded_image.path is not None else None,
            "image_source_kind": self.loaded_image.source_kind,
            "image_display_name": self.loaded_image.display_name,
            "output_dir": str(self.output_dir.resolve()) if self.output_dir is not None else None,
            "image_size": {
                "width": self.loaded_image.width,
                "height": self.loaded_image.height,
            },
            "zoom": self.zoom,
            "configured": self.is_configured,
            "rectangles": [rectangle.as_dict() for rectangle in self.rectangles],
        }

        try:
            core.write_text_atomic(Path(target), json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("저장 실패", f"배치 파일을 저장하지 못했습니다.\n{core.describe_error(exc)}")
            return

        self.status_var.set(f"배치를 저장했습니다: {Path(target).name}")

    def load_configuration(self) -> None:
        config_path = filedialog.askopenfilename(title="배치 불러오기", filetypes=CONFIG_FILE_TYPES)
        if not config_path:
            return

        try:
            layout = core.load_layout_file(Path(config_path))
        except core.LayoutError as exc:
            messagebox.showerror("불러오기 실패", str(exc))
            return

        saved_image_path = Path(layout.image_path) if layout.image_path else None
        if saved_image_path and saved_image_path.is_file():
            current_image_path = self.loaded_image.path.resolve() if self.loaded_image and self.loaded_image.path else None
            if current_image_path != saved_image_path.resolve():
                if not self._load_image_from_path(saved_image_path):
                    return
        elif not self.loaded_image:
            missing_source_message = (
                "이 배치는 클립보드 그림에서 만든 것입니다. 그림을 다시 붙여넣은 뒤 불러와 주세요."
                if layout.source_kind == "clipboard"
                else "배치에 적힌 원본 사진을 찾을 수 없습니다. 사진을 먼저 연 뒤 다시 불러와 주세요."
            )
            messagebox.showerror("불러오기 실패", missing_source_message)
            return

        assert self.loaded_image is not None
        current_size = (self.loaded_image.width, self.loaded_image.height)
        saved_size = layout.image_size or current_size
        rects = core.scale_rects(layout.rects, saved_size, current_size)
        self.rectangles = [CropRectangle.from_tuple(r) for r in core.clamp_rects(rects, *current_size)]
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = layout.configured and bool(self.rectangles)

        self.zoom = self._clamp_zoom(layout.zoom)
        self._render_image(reset_view=True)

        if saved_size != current_size:
            messagebox.showwarning(
                "크기 맞춤",
                "지금 사진의 크기가 배치를 저장할 때와 달라서 자를 영역을 크기에 맞게 늘이거나 줄였습니다.",
            )

        if layout.output_dir:
            saved_output_dir = Path(layout.output_dir)
            if saved_output_dir.is_dir():
                self._set_output_dir(saved_output_dir, user_selected=True)
            else:
                self._set_output_dir(None)
                messagebox.showwarning(
                    "저장 폴더 없음",
                    "배치에 적힌 저장 폴더가 더는 없습니다. 저장 폴더를 새로 골라 주세요.",
                )

        self.status_var.set(f"배치를 불러왔습니다: {Path(config_path).name} (영역 {len(self.rectangles)}개)")
        self._update_controls()

    def _get_default_config_path(self) -> Path:
        assert self.loaded_image is not None

        if self.loaded_image.path is not None:
            return self.loaded_image.path.parent / f"{self.loaded_image.save_stem}_crop_config.json"

        base_dir = self.output_dir if self.output_dir is not None else Path.cwd()
        return base_dir / f"{self.loaded_image.save_stem}_crop_config.json"

    # ------------------------------------------------------------------
    # 여러 장
    # ------------------------------------------------------------------

    def open_batch_process_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("여러 장 자르기")
        dialog.geometry("820x640")
        dialog.minsize(660, 520)
        dialog.transient(self.root)
        dialog.grab_set()
        self._style_dialog(dialog)

        config_source_var = tk.StringVar(value="current")
        json_path_var = tk.StringVar()
        grid_rule_var = tk.StringVar(value=next(iter(GRID_RULE_LABELS)))
        batch_gutter_var = tk.BooleanVar(value=self.detect_gutters_var.get())
        batch_output_dir_var = tk.StringVar()
        create_subfolder_var = tk.BooleanVar(value=True)
        file_list: list[Path] = []
        running = {"value": False}

        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill="both", expand=True)
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        files_frame = ttk.LabelFrame(main_frame, text="처리할 파일 목록", padding=10)
        files_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        files_frame.rowconfigure(0, weight=1)
        files_frame.columnconfigure(0, weight=1)

        listbox_frame = ttk.Frame(files_frame)
        listbox_frame.grid(row=0, column=0, sticky="nsew")
        listbox_frame.rowconfigure(0, weight=1)
        listbox_frame.columnconfigure(0, weight=1)

        file_listbox = tk.Listbox(listbox_frame, selectmode="extended")
        file_listbox.grid(row=0, column=0, sticky="nsew")
        self._style_listbox(file_listbox)

        list_yscroll = ttk.Scrollbar(listbox_frame, orient="vertical", command=file_listbox.yview)
        list_yscroll.grid(row=0, column=1, sticky="ns")
        file_listbox.configure(yscrollcommand=list_yscroll.set)

        list_xscroll = ttk.Scrollbar(listbox_frame, orient="horizontal", command=file_listbox.xview)
        list_xscroll.grid(row=1, column=0, sticky="ew")
        file_listbox.configure(xscrollcommand=list_xscroll.set)

        count_var = tk.StringVar(value="0개")
        ttk.Label(files_frame, textvariable=count_var).grid(row=1, column=0, sticky="w", pady=(6, 0))

        def update_file_listbox() -> None:
            file_listbox.delete(0, "end")
            for f in file_list:
                file_listbox.insert("end", str(f))
            count_var.set(f"{len(file_list)}개")

        def add_paths(paths: list[Path]) -> None:
            current = set(file_list)
            file_list.extend(p for p in sorted(set(paths)) if p not in current)
            update_file_listbox()

        def add_files() -> None:
            paths = filedialog.askopenfilenames(
                title="처리할 사진 고르기",
                filetypes=SUPPORTED_FILE_TYPES,
                parent=dialog,
            )
            if paths:
                add_paths([Path(p) for p in paths])

        def add_folder() -> None:
            dir_path = filedialog.askdirectory(
                title="사진이 든 폴더 고르기",
                mustexist=True,
                parent=dialog,
            )
            if not dir_path:
                return
            try:
                found = core.collect_images_in_folder(Path(dir_path))
            except OSError as exc:
                messagebox.showerror("폴더 읽기 실패", core.describe_error(exc), parent=dialog)
                return
            if not found:
                messagebox.showinfo("폴더 넣기", "이 폴더에는 넣을 사진이 없습니다(앞서 잘라 저장한 조각은 뺍니다).", parent=dialog)
                return
            add_paths(found)

        def remove_selected() -> None:
            selected_indices = file_listbox.curselection()
            if not selected_indices:
                return
            for i in sorted(selected_indices, reverse=True):
                del file_list[i]
            update_file_listbox()

        def clear_all() -> None:
            file_list.clear()
            update_file_listbox()

        file_buttons_frame = ttk.Frame(files_frame)
        file_buttons_frame.grid(row=0, column=1, sticky="n", padx=(10, 0))

        ttk.Button(file_buttons_frame, text="사진 넣기", command=add_files).pack(fill="x", pady=2)
        ttk.Button(file_buttons_frame, text="폴더 넣기", command=add_folder).pack(fill="x", pady=2)
        ttk.Button(file_buttons_frame, text="선택 빼기", command=remove_selected).pack(fill="x", pady=(10, 2))
        ttk.Button(file_buttons_frame, text="전부 비우기", command=clear_all).pack(fill="x", pady=2)

        config_frame = ttk.LabelFrame(main_frame, text="적용할 분할 규칙", padding=10)
        config_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)

        def browse_json() -> None:
            path = filedialog.askopenfilename(title="배치 파일 고르기", filetypes=CONFIG_FILE_TYPES, parent=dialog)
            if path:
                json_path_var.set(path)

        def toggle_inputs(*_: object) -> None:
            mode = config_source_var.get()
            json_path_entry.config(state="readonly" if mode == "json" else "disabled")
            json_browse_button.config(state="normal" if mode == "json" else "disabled")
            grid_combo.config(state="readonly" if mode == "grid" else "disabled")
            gutter_check.config(state="normal" if mode == "grid" else "disabled")

        current_settings_radio = ttk.Radiobutton(
            config_frame, text="지금 창에서 확정한 영역 쓰기", variable=config_source_var, value="current", command=toggle_inputs
        )
        current_settings_radio.grid(row=0, column=0, columnspan=3, sticky="w")

        if not self.is_configured or not self.rectangles or not self.loaded_image:
            current_settings_radio.config(state="disabled")
            config_source_var.set("grid")

        json_settings_radio = ttk.Radiobutton(
            config_frame, text="저장한 배치 파일 쓰기:", variable=config_source_var, value="json", command=toggle_inputs
        )
        json_settings_radio.grid(row=1, column=0, sticky="w", pady=(5, 0))
        json_path_entry = ttk.Entry(config_frame, textvariable=json_path_var, state="disabled")
        json_path_entry.grid(row=1, column=1, sticky="ew", padx=(5, 5), pady=(5, 0))
        json_browse_button = ttk.Button(config_frame, text="파일 찾기", command=browse_json, state="disabled")
        json_browse_button.grid(row=1, column=2, sticky="w", pady=(5, 0))

        grid_radio = ttk.Radiobutton(
            config_frame, text="AI 그림 자동 나누기:", variable=config_source_var, value="grid", command=toggle_inputs
        )
        grid_radio.grid(row=2, column=0, sticky="w", pady=(5, 0))
        grid_options = ttk.Frame(config_frame)
        grid_options.grid(row=2, column=1, columnspan=2, sticky="w", padx=(5, 0), pady=(5, 0))
        grid_combo = ttk.Combobox(grid_options, textvariable=grid_rule_var, values=list(GRID_RULE_LABELS), width=12, state="readonly")
        grid_combo.pack(side="left")
        gutter_check = ttk.Checkbutton(grid_options, text="사진마다 칸 사이 여백 찾기", variable=batch_gutter_var)
        gutter_check.pack(side="left", padx=(10, 0))
        toggle_inputs()

        output_frame = ttk.LabelFrame(main_frame, text="결과물 저장 위치", padding=10)
        output_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        output_frame.columnconfigure(0, weight=1)

        def choose_batch_output_dir() -> None:
            path = filedialog.askdirectory(title="결과물을 저장할 폴더 고르기", mustexist=True, parent=dialog)
            if path:
                batch_output_dir_var.set(path)

        ttk.Label(output_frame, textvariable=batch_output_dir_var).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        batch_output_dir_var.set(str(self.output_dir) if self.output_dir else "")
        ttk.Button(output_frame, text="폴더 고르기", command=choose_batch_output_dir).grid(row=0, column=1, sticky="e")

        subfolder_checkbox = ttk.Checkbutton(
            output_frame,
            text="원본 사진 이름으로 하위 폴더 만들기",
            variable=create_subfolder_var,
        )
        subfolder_checkbox.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=3, column=0, sticky="sew", pady=(10, 0))
        action_frame.columnconfigure(0, weight=1)

        progress_bar = ttk.Progressbar(action_frame, orient="horizontal", mode="determinate")
        progress_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        progress_text_var = tk.StringVar(value="")
        ttk.Label(action_frame, textvariable=progress_text_var).grid(row=1, column=0, sticky="w")

        action_buttons_frame = ttk.Frame(action_frame)
        action_buttons_frame.grid(row=1, column=1, sticky="e")

        def on_close() -> None:
            if running["value"]:
                progress_text_var.set("작업이 끝날 때까지 창을 닫을 수 없습니다.")
                return
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", on_close)

        def start_batch_processing() -> None:
            if not file_list:
                messagebox.showerror("여러 장", "처리할 파일이 없습니다. 목록에 사진을 넣어 주세요.", parent=dialog)
                return

            output_dir_str = batch_output_dir_var.get().strip()
            if not output_dir_str:
                messagebox.showerror("여러 장", "결과물을 저장할 폴더를 골라 주세요.", parent=dialog)
                return

            output_dir = Path(output_dir_str)
            if not output_dir.is_dir():
                messagebox.showerror("여러 장", "고른 저장 폴더가 없습니다. 다시 골라 주세요.", parent=dialog)
                return

            job = BatchJob(files=list(file_list), output_dir=output_dir, create_subfolders=create_subfolder_var.get())
            source = config_source_var.get()
            if source == "current":
                if not self.is_configured or not self.rectangles or not self.loaded_image:
                    messagebox.showerror("여러 장", "지금 창에 확정한 영역이 없습니다.", parent=dialog)
                    return
                job.rects = [r.as_tuple() for r in self.rectangles]
                # 지금 사진과 크기가 다른 사진에는 영역을 비율대로 맞춘다.
                job.source_size = (self.loaded_image.width, self.loaded_image.height)
            elif source == "json":
                json_path_str = json_path_var.get().strip()
                if not json_path_str:
                    messagebox.showerror("여러 장", "쓸 배치 파일을 골라 주세요.", parent=dialog)
                    return
                try:
                    layout = core.load_layout_file(Path(json_path_str), require_size=True)
                except core.LayoutError as exc:
                    messagebox.showerror("배치 파일 오류", str(exc), parent=dialog)
                    return
                job.rects = layout.rects
                job.source_size = layout.image_size
            else:
                job.grid = GRID_RULE_LABELS.get(grid_rule_var.get(), (2, 2))
                job.detect_gutters = batch_gutter_var.get()

            running["value"] = True
            start_button.config(state="disabled")
            close_button.config(state="disabled")
            progress_bar.config(maximum=len(job.files), value=0)
            progress_text_var.set(f"0 / {len(job.files)}")

            def on_progress(done: int, total: int) -> None:
                progress_bar.config(value=done)
                progress_text_var.set(f"{done} / {total}")

            def on_done() -> None:
                running["value"] = False
                if dialog.winfo_exists():
                    dialog.destroy()

            self._start_batch_job(job, on_progress, on_done, parent=dialog)

        start_button = ttk.Button(action_buttons_frame, text="여러 장 저장", command=start_batch_processing)
        start_button.pack(side="left", padx=5)
        close_button = ttk.Button(action_buttons_frame, text="창 닫기", command=on_close)
        close_button.pack(side="left", padx=5)

        dialog.wait_window()

    def _start_batch_job(
        self,
        job: BatchJob,
        on_progress: Callable[[int, int], None],
        on_done: Callable[[], None],
        parent: tk.Misc,
    ) -> None:
        def worker() -> None:
            result = self._perform_batch_job(job, lambda done, total: self._post(lambda: on_progress(done, total)))
            self._post(lambda: self._finish_batch_job(job, result, parent, on_done))

        threading.Thread(target=worker, daemon=True).start()

    def _perform_batch_job(
        self,
        job: BatchJob,
        report_progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, object]:
        """작업 스레드에서 돈다. 화면은 만지지 않는다."""
        total_files = len(job.files)
        saved_paths: list[Path] = []
        failed_paths: list[Path] = []
        errors: list[str] = []
        gutter_misses = 0

        for i, image_path in enumerate(job.files):
            try:
                current_image, format_name = core.open_image_file(image_path)
                width, height = current_image.size
                if job.grid is not None:
                    split = core.split_grid_auto(current_image, job.grid[0], job.grid[1], job.detect_gutters)
                    if job.detect_gutters and split.gutters_found < split.gutters_expected:
                        gutter_misses += 1
                    rects = core.clamp_rects(split.rects, width, height)
                else:
                    rects = list(job.rects or [])
                    if job.source_size is not None:
                        rects = core.scale_rects(rects, job.source_size, (width, height))
                    rects = core.clamp_rects(rects, width, height)

                if not rects:
                    raise ValueError("크기를 맞추고 나니 남는 영역이 없습니다.")

                stem = image_path.stem
                suffix = self._get_batch_output_suffix(image_path, format_name)

                current_output_dir = job.output_dir
                if job.create_subfolders:
                    current_output_dir = job.output_dir / stem
                    current_output_dir.mkdir(parents=True, exist_ok=True)

                icc = current_image.info.get("icc_profile")
                for index, rect in enumerate(rects, start=1):
                    cropped = current_image.crop(rect)
                    target_path = core.build_output_path(current_output_dir, f"{stem}_rect_{index:02d}", suffix)
                    core.save_image(cropped, target_path, icc)
                    saved_paths.append(target_path)
            except Exception as exc:
                failed_paths.append(image_path)
                errors.append(f"{image_path.name}: {core.describe_error(exc)}")
            finally:
                if report_progress is not None:
                    report_progress(i + 1, total_files)

        return {
            "total": total_files,
            "saved_paths": saved_paths,
            "failed_paths": failed_paths,
            "errors": errors,
            "gutter_misses": gutter_misses,
        }

    def _finish_batch_job(self, job: BatchJob, result: dict[str, object], parent: tk.Misc, on_done: Callable[[], None]) -> None:
        saved_paths: list[Path] = result["saved_paths"]  # type: ignore[assignment]
        failed_paths: list[Path] = result["failed_paths"]  # type: ignore[assignment]
        errors: list[str] = result["errors"]  # type: ignore[assignment]

        self.last_batch_job = job
        self.last_batch_failures = failed_paths
        self._update_controls()

        if saved_paths:
            self._append_history_entry(
                job_type="batch",
                source_images=[path.name for path in job.files],
                output_dir=job.output_dir,
                saved_paths=saved_paths,
                rectangles_count=len(job.rects or []) if job.grid is None else job.grid[0] * job.grid[1],
                details={"rule": job.describe_rule(), "failed": [str(p) for p in failed_paths[:50]]},
            )

        message = f"여러 장 작업이 끝났습니다.\n\n시도한 사진: {result['total']}장\n저장한 조각: {len(saved_paths)}개"
        if job.grid is not None and job.detect_gutters and result.get("gutter_misses"):
            message += f"\n칸 사이 여백을 다 찾지 못해 같은 간격으로 자른 사진: {result['gutter_misses']}장"
        if failed_paths:
            message += f"\n실패한 사진: {len(failed_paths)}장"
            message += "\n위쪽 '다시' 버튼으로 실패한 사진만 다시 돌릴 수 있습니다."
            if errors:
                shown = errors[:5]
                message += "\n\n실패 이유:\n" + "\n".join(shown)
                if len(errors) > len(shown):
                    message += f"\n…그 밖에 {len(errors) - len(shown)}건"
        self.status_var.set(f"여러 장 작업 끝: 조각 {len(saved_paths)}개 저장, 실패 {len(failed_paths)}장")
        on_done()
        messagebox.showinfo("여러 장 작업 끝", message, parent=self.root)

    def retry_failed_batch_jobs(self) -> None:
        if not self.last_batch_job or not self.last_batch_failures:
            messagebox.showinfo("다시", "다시 돌릴 실패한 사진이 없습니다.")
            return

        valid_failures = [path for path in self.last_batch_failures if path.is_file()]
        if not valid_failures:
            messagebox.showwarning("다시", "실패했던 사진 파일을 더는 찾을 수 없습니다.")
            self.last_batch_failures = []
            self._update_controls()
            return

        previous = self.last_batch_job
        if not previous.output_dir.is_dir():
            messagebox.showerror("다시", "지난번 저장 폴더를 찾을 수 없습니다. '여러 장'에서 새로 돌려 주세요.")
            return

        job = replace(previous, files=valid_failures)

        retry_dialog = tk.Toplevel(self.root)
        retry_dialog.title("실패한 사진 다시")
        retry_dialog.geometry("520x160")
        retry_dialog.transient(self.root)
        retry_dialog.grab_set()
        retry_dialog.protocol("WM_DELETE_WINDOW", lambda: None)  # 끝날 때까지 닫지 않는다
        self._style_dialog(retry_dialog)

        frame = ttk.Frame(retry_dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"실패했던 사진 {len(valid_failures)}장을 다시 처리합니다.").pack(anchor="w", pady=(0, 8))
        progress_bar = ttk.Progressbar(frame, orient="horizontal", mode="determinate", maximum=len(valid_failures))
        progress_bar.pack(fill="x", pady=(0, 8))
        progress_text_var = tk.StringVar(value="처리하는 중…")
        ttk.Label(frame, textvariable=progress_text_var).pack(anchor="w")

        def on_progress(done: int, total: int) -> None:
            progress_bar.config(value=done)
            progress_text_var.set(f"처리하는 중… {done} / {total}")

        def on_done() -> None:
            if retry_dialog.winfo_exists():
                retry_dialog.destroy()

        self._start_batch_job(job, on_progress, on_done, parent=retry_dialog)

    def _get_batch_output_suffix(self, image_path: Path, format_name: str | None = None) -> str:
        suffix = image_path.suffix.lower()
        if suffix in SUPPORTED_IMAGE_SUFFIXES:
            return suffix
        return core.suffix_from_format(format_name)

    # ------------------------------------------------------------------
    # 확대·축소
    # ------------------------------------------------------------------

    def zoom_by(self, factor: float, focus_event: tk.Event | None = None) -> None:
        if not self.loaded_image:
            return

        focus = (focus_event.x, focus_event.y) if focus_event is not None else None
        self._set_zoom(self.zoom * factor, focus_canvas=focus)

    def reset_zoom(self) -> None:
        if not self.loaded_image:
            return
        self._set_zoom(1.0)

    def fit_to_view(self, initial_load: bool = False) -> None:
        if not self.loaded_image:
            return

        self.root.update_idletasks()
        canvas_width = max(self.canvas.winfo_width(), 1)
        canvas_height = max(self.canvas.winfo_height(), 1)
        scale_x = canvas_width / self.loaded_image.width
        scale_y = canvas_height / self.loaded_image.height
        fit_zoom = self._clamp_zoom(min(scale_x, scale_y))
        self.zoom = fit_zoom if initial_load else self.zoom
        self._set_zoom(fit_zoom, reset_view=True)

    def _set_zoom(
        self,
        new_zoom: float,
        focus_canvas: tuple[int, int] | None = None,
        reset_view: bool = False,
    ) -> None:
        if not self.loaded_image:
            return

        clamped_zoom = self._clamp_zoom(new_zoom)
        if abs(clamped_zoom - self.zoom) < 1e-9 and not reset_view:
            return

        preserve_image_point: tuple[float, float] | None = None
        if focus_canvas is not None:
            preserve_image_point = self._canvas_point_to_image_point(*focus_canvas)

        self.zoom = clamped_zoom
        self._render_image(
            preserve_image_point=preserve_image_point,
            focus_canvas=focus_canvas,
            reset_view=reset_view,
        )

    def _clamp_zoom(self, value: float) -> float:
        upper = MAX_ZOOM
        if self.loaded_image is not None:
            pixels = max(1, self.loaded_image.width * self.loaded_image.height)
            upper = min(MAX_ZOOM, max(MIN_ZOOM, (MAX_DISPLAY_PIXELS / pixels) ** 0.5))
        return max(MIN_ZOOM, min(upper, value))

    def _render_image(
        self,
        preserve_image_point: tuple[float, float] | None = None,
        focus_canvas: tuple[int, int] | None = None,
        reset_view: bool = False,
    ) -> None:
        if not self.loaded_image:
            self._show_placeholder()
            return

        display_width = max(1, round(self.loaded_image.width * self.zoom))
        display_height = max(1, round(self.loaded_image.height * self.zoom))

        resample = getattr(Image, "Resampling", Image).LANCZOS
        resized = self.loaded_image.image.resize((display_width, display_height), resample)
        self.photo_image = ImageTk.PhotoImage(resized)

        self.canvas.delete("all")
        self.canvas_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.photo_image, tags=("image",))
        self.canvas.configure(scrollregion=(0, 0, display_width, display_height))

        self._refresh_overlays()
        self.zoom_var.set(f"{round(self.zoom * 100)}%")

        if reset_view:
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)

        if preserve_image_point is not None and focus_canvas is not None:
            self._restore_focus_point(preserve_image_point, focus_canvas, display_width, display_height)

        self._update_controls()

    def _restore_focus_point(
        self,
        image_point: tuple[float, float],
        focus_canvas: tuple[int, int],
        display_width: int,
        display_height: int,
    ) -> None:
        viewport_width = max(self.canvas.winfo_width(), 1)
        viewport_height = max(self.canvas.winfo_height(), 1)

        desired_left = image_point[0] * self.zoom - focus_canvas[0]
        desired_top = image_point[1] * self.zoom - focus_canvas[1]

        max_left = max(display_width - viewport_width, 0)
        max_top = max(display_height - viewport_height, 0)

        left = min(max(desired_left, 0), max_left)
        top = min(max(desired_top, 0), max_top)

        self.canvas.xview_moveto(left / display_width if display_width > 0 else 0)
        self.canvas.yview_moveto(top / display_height if display_height > 0 else 0)

    # ------------------------------------------------------------------
    # 마우스
    # ------------------------------------------------------------------

    def on_motion(self, event: tk.Event) -> None:
        if self.drag_context:
            return
        if not self.loaded_image:
            self.canvas.config(cursor="")
            return

        point = self._event_to_image_point(event)
        if not point:
            self.canvas.config(cursor="")
            return

        handle_pos = self._find_handle_at(*point)
        shared = None if handle_pos else self._find_shared_edge_at(*point)
        if handle_pos:
            self.canvas.config(cursor=self.HANDLE_CURSORS[handle_pos])
        elif shared is not None:
            self.canvas.config(cursor="sb_h_double_arrow" if shared.axis == "x" else "sb_v_double_arrow")
        elif self._find_rectangle_at(*point) is not None:
            self.canvas.config(cursor="fleur")
        else:
            self.canvas.config(cursor="crosshair")

    def on_left_press(self, event: tk.Event) -> None:
        if not self.loaded_image:
            return

        point = self._event_to_image_point(event)
        if not point:
            self.selected_rectangle_index = None
            self.drag_context = None
            self._refresh_overlays()
            return

        x, y = point

        if self.selected_rectangle_index is not None:
            handle_pos = self._find_handle_at(x, y)
            if handle_pos:
                self.drag_context = {
                    "kind": "resize",
                    "index": self.selected_rectangle_index,
                    "handle": handle_pos,
                    "origin": self.rectangles[self.selected_rectangle_index].normalized(),
                    "shift_pressed": (event.state & SHIFT_MASK) != 0,
                }
                self.status_var.set("고른 영역의 크기를 바꾸는 중입니다.")
                self._update_controls()
                return

        shared = self._find_shared_edge_at(x, y)
        if shared is not None:
            self.selected_rectangle_index = None
            self.drag_context = {
                "kind": "edge",
                "edge": shared,
                "start": x if shared.axis == "x" else y,
                "origin": [r.normalized() for r in self.rectangles],
            }
            self.status_var.set("두 칸 사이 경계를 옮기는 중입니다. 두 칸이 함께 바뀝니다.")
            self._refresh_overlays()
            self._update_controls()
            return

        index = self._find_rectangle_at(x, y)
        self.selected_rectangle_index = index

        if index is not None:
            rectangle = self.rectangles[index].normalized()
            self.drag_context = {
                "kind": "move",
                "index": index,
                "start_x": x,
                "start_y": y,
                "origin": rectangle,
            }
            self.status_var.set("고른 영역을 옮기는 중입니다.")
        else:
            self.rectangles.append(CropRectangle(x, y, x, y))
            self.selected_rectangle_index = len(self.rectangles) - 1
            self.drag_context = {
                "kind": "create",
                "index": self.selected_rectangle_index,
                "shift_pressed": (event.state & SHIFT_MASK) != 0,
            }
            self.is_configured = False
            self.status_var.set("새 영역을 그리는 중입니다. 마우스를 놓으면 자리 잡습니다.")

        self._refresh_overlays()
        self._update_controls()

    def on_left_drag(self, event: tk.Event) -> None:
        if not self.loaded_image or not self.drag_context:
            return

        point = self._event_to_image_point(event)
        if not point:
            return

        x, y = point
        kind = self.drag_context["kind"]

        if kind == "edge":
            edge = self.drag_context["edge"]
            origin = self.drag_context["origin"]
            assert isinstance(edge, core.SharedEdge) and isinstance(origin, list)
            delta = (x if edge.axis == "x" else y) - int(self.drag_context["start"])
            moved = core.move_shared_edge(
                [r.as_tuple() for r in origin], edge, delta, self.loaded_image.width, self.loaded_image.height
            )
            for index in (edge.first, edge.second):
                self.rectangles[index] = CropRectangle.from_tuple(moved[index])
            self.is_configured = False
        elif kind == "resize":
            index = int(self.drag_context["index"])
            handle = str(self.drag_context["handle"])
            origin = self.drag_context["origin"]
            assert isinstance(origin, CropRectangle)
            shift_pressed = bool(self.drag_context.get("shift_pressed"))

            self.rectangles[index] = self._resize_rectangle(origin, handle, x, y, shift_pressed)
            self.is_configured = False
        elif kind == "create":
            index = int(self.drag_context["index"])
            current = self.rectangles[index]

            end_x, end_y = x, y
            if self.drag_context.get("shift_pressed"):
                start_x, start_y = current.left, current.top
                dx = end_x - start_x
                dy = end_y - start_y
                side = max(abs(dx), abs(dy))
                end_x = start_x + (side if dx >= 0 else -side)
                end_y = start_y + (side if dy >= 0 else -side)

            self.rectangles[index] = CropRectangle(current.left, current.top, end_x, end_y)
            self.is_configured = False
        else:
            index = int(self.drag_context["index"])
            start_x = int(self.drag_context["start_x"])
            start_y = int(self.drag_context["start_y"])
            origin = self.drag_context["origin"]
            assert isinstance(origin, CropRectangle)
            self.rectangles[index] = self._move_rectangle_within_bounds(origin, x - start_x, y - start_y)
            self.is_configured = False

        self._refresh_overlays()
        self._update_controls()

    def on_left_release(self, _event: tk.Event) -> None:
        if self.drag_context and self.drag_context.get("kind") == "edge":
            self.drag_context = None
            self.status_var.set("두 칸 사이 경계를 옮겼습니다. 더 고치거나 '확정'을 누르세요.")
            self._refresh_overlays()
            self._update_controls()
            return
        if self.selected_rectangle_index is None or not self.drag_context:
            self.drag_context = None
            return

        normalized = self._normalize_rectangle(self.rectangles[self.selected_rectangle_index])
        if normalized is None:
            del self.rectangles[self.selected_rectangle_index]
            self.selected_rectangle_index = None
            self.status_var.set("너무 작은 영역은 저절로 지워집니다.")
        else:
            self.rectangles[self.selected_rectangle_index] = normalized
            self.status_var.set("영역을 바꿨습니다. 더 고치거나 '확정'을 누르세요.")

        self.drag_context = None
        self._refresh_overlays()
        self._update_controls()

    def on_right_press(self, event: tk.Event) -> None:
        if not self.loaded_image:
            return

        point = self._event_to_image_point(event)
        if not point:
            return

        index = self._find_rectangle_at(*point)
        if index is None:
            return

        self.selected_rectangle_index = index
        self.delete_selected_rectangle()

    def on_mousewheel(self, event: tk.Event) -> None:
        delta = getattr(event, "delta", 0) or 0
        if delta == 0:
            return
        # 터치패드는 120보다 작은 값을 보내므로 최소 한 칸은 움직이게 한다.
        steps = int(-delta / 120) or (-1 if delta > 0 else 1)

        if event.state & CONTROL_MASK:
            self.zoom_by(ZOOM_STEP if delta > 0 else 1 / ZOOM_STEP, focus_event=event)
            return

        if event.state & SHIFT_MASK:
            self.canvas.xview_scroll(steps, "units")
            return

        self.canvas.yview_scroll(steps, "units")

    def cancel_current_drag(self) -> None:
        context = self.drag_context
        if context and context.get("kind") == "edge" and isinstance(context.get("origin"), list):
            self.rectangles = list(context["origin"])  # type: ignore[arg-type]
            self.status_var.set("끌던 것을 취소했습니다.")
            self._refresh_overlays()
        elif context and self.selected_rectangle_index is not None:
            kind = context.get("kind")
            if kind == "create":
                del self.rectangles[self.selected_rectangle_index]
                self.selected_rectangle_index = None
            elif kind in {"move", "resize"} and isinstance(context.get("origin"), CropRectangle):
                self.rectangles[self.selected_rectangle_index] = context["origin"]  # type: ignore[assignment]
            self.status_var.set("끌던 것을 취소했습니다.")
            self._refresh_overlays()

        self.drag_context = None
        self._update_controls()

    def delete_selected_rectangle(self) -> None:
        if self.selected_rectangle_index is None:
            return

        del self.rectangles[self.selected_rectangle_index]
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = False
        self._refresh_overlays()
        self._update_controls()
        self.status_var.set("고른 영역을 지웠습니다.")

    def clear_rectangles(self) -> None:
        if not self.loaded_image:
            return

        self.rectangles = []
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = False
        self._refresh_overlays()
        self._update_controls()
        self.status_var.set("영역을 모두 지웠습니다.")

    # ------------------------------------------------------------------
    # 칸 나누기
    # ------------------------------------------------------------------

    def open_grid_generator_dialog(self) -> None:
        if not self.loaded_image:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("칸 나누기")
        dialog.geometry("360x250")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        self._style_dialog(dialog)

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="가로줄 수(행)").grid(row=0, column=0, sticky="w", pady=5)
        rows_var = tk.StringVar(value="2")
        rows_entry = ttk.Entry(frame, textvariable=rows_var, width=10)
        rows_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        ttk.Label(frame, text="세로줄 수(열)").grid(row=1, column=0, sticky="w", pady=5)
        cols_var = tk.StringVar(value="2")
        cols_entry = ttk.Entry(frame, textvariable=cols_var, width=10)
        cols_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0))

        ttk.Label(frame, text="칸 사이 여백(픽셀)").grid(row=2, column=0, sticky="w", pady=5)
        padding_var = tk.StringVar(value="0")
        padding_entry = ttk.Entry(frame, textvariable=padding_var, width=10)
        padding_entry.grid(row=2, column=1, sticky="ew", padx=(10, 0))

        auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="여백 자동 찾기(AI 그림용, 위 여백 값은 쓰지 않음)",
            variable=auto_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=4, column=0, columnspan=2, pady=(16, 0))

        def on_generate(_event: tk.Event | None = None) -> None:
            try:
                rows = int(rows_var.get().strip())
                cols = int(cols_var.get().strip())
                padding = int(padding_var.get().strip() or "0")
                if rows <= 0 or cols <= 0 or padding < 0 or rows > 50 or cols > 50:
                    raise ValueError
            except ValueError:
                messagebox.showerror("입력 오류", "행·열은 1~50, 여백은 0 이상의 정수로 넣어 주세요.", parent=dialog)
                return

            if auto_var.get():
                ok = self._apply_auto_grid(rows, cols, detect_gutters=True, confirm=False)
            else:
                ok = self.generate_grid_rectangles(rows, cols, padding, parent=dialog)
            if ok:
                dialog.destroy()

        generate_button = ttk.Button(button_frame, text="칸 만들기", command=on_generate)
        generate_button.pack(side="left", padx=5)

        cancel_button = ttk.Button(button_frame, text="닫기", command=dialog.destroy)
        cancel_button.pack(side="left", padx=5)
        dialog.bind("<Return>", on_generate)
        rows_entry.focus_set()

        dialog.wait_window()

    def generate_grid_rectangles(self, rows: int, cols: int, padding: int, parent: tk.Misc | None = None) -> bool:
        if not self.loaded_image:
            return False

        try:
            rects = core.uniform_grid(self.loaded_image.width, self.loaded_image.height, rows, cols, padding)
        except ValueError as exc:
            messagebox.showerror("칸 나누기", str(exc), parent=parent or self.root)
            return False

        self.rectangles = [CropRectangle.from_tuple(r) for r in core.clamp_rects(rects, self.loaded_image.width, self.loaded_image.height)]
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = False

        self._refresh_overlays()
        self._update_controls()
        self.status_var.set(f"{rows}×{cols} 칸으로 영역 {len(self.rectangles)}개를 만들었습니다. 확인 후 '확정'을 누르세요.")
        return True

    def _apply_auto_grid(self, rows: int, cols: int, detect_gutters: bool, confirm: bool) -> bool:
        assert self.loaded_image is not None
        image = self.loaded_image.image
        try:
            split = core.split_grid_auto(image, rows, cols, detect_gutters)
        except ValueError as exc:
            messagebox.showerror("칸 나누기", str(exc))
            return False
        rects = core.clamp_rects(split.rects, image.width, image.height)
        if len(rects) != rows * cols:
            messagebox.showerror("칸 나누기", "그림이 너무 작아 칸을 나눌 수 없습니다.")
            return False
        self.rectangles = [CropRectangle.from_tuple(r) for r in rects]
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = confirm
        self._refresh_overlays()
        self._update_controls()
        self.last_grid_message = core.describe_grid_split(split) if detect_gutters else f"{rows}×{cols} {len(rects)}칸으로 같은 간격으로 나눴습니다."
        self.status_var.set(self.last_grid_message)
        return True

    def quick_split(self, rows: int, cols: int) -> None:
        """「4칸」「9칸」: 영역을 만들고 확정까지 한 뒤, 저장 폴더가 있으면 바로 저장할지 묻는다."""
        if not self.loaded_image:
            return
        if not self._apply_auto_grid(rows, cols, self.detect_gutters_var.get(), confirm=True):
            return
        message = self.last_grid_message
        if self.output_dir is not None and self.output_dir.is_dir():
            if messagebox.askyesno("바로 저장", f"{message}\n\n저장 폴더: {self.output_dir}\n지금 잘라서 저장할까요?"):
                self.split_image()
        else:
            messagebox.showinfo("칸 나누기", f"{message}\n\n저장 폴더를 정한 뒤 '잘라서 저장'을 누르세요.")

    def apply_settings(self) -> None:
        if not self.loaded_image:
            return

        self.rectangles = self._normalize_rectangles_collection(self.rectangles)
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = bool(self.rectangles)
        self._refresh_overlays()
        self._update_controls()

        if self.rectangles:
            self.status_var.set(f"영역 {len(self.rectangles)}개로 확정했습니다.")
        else:
            self.status_var.set("확정할 영역이 아직 없습니다.")

    # ------------------------------------------------------------------
    # 한 장 저장
    # ------------------------------------------------------------------

    def split_image(self) -> None:
        if not self.loaded_image or not self.is_configured or not self.rectangles:
            return

        if self.output_dir is None or not self.output_dir.is_dir():
            messagebox.showerror("저장 실패", "먼저 저장 폴더를 정해 주세요.")
            return

        output_dir = self.output_dir
        stem = self.loaded_image.save_stem
        suffix = self._resolve_output_suffix()
        icc = self.loaded_image.image.info.get("icc_profile")
        saved_paths: list[Path] = []
        error_text: str | None = None

        for index, rectangle in enumerate(self.rectangles, start=1):
            try:
                rect = rectangle.normalized()
                cropped = self.loaded_image.image.crop((rect.left, rect.top, rect.right, rect.bottom))
                target_path = core.build_output_path(output_dir, f"{stem}_rect_{index:02d}", suffix)
                core.save_image(cropped, target_path, icc)
                saved_paths.append(target_path)
            except Exception as exc:  # pragma: no cover - tkinter dialog flow
                error_text = f"{index}번 영역 저장 중: {core.describe_error(exc)}"
                break

        if saved_paths:
            self._append_history_entry(
                job_type="single",
                source_images=[self.loaded_image.display_name],
                output_dir=output_dir,
                saved_paths=saved_paths,
                rectangles_count=len(self.rectangles),
            )

        if error_text:
            messagebox.showerror(
                "저장 실패",
                f"{error_text}\n\n그 전까지 {len(saved_paths)}개는 저장했습니다.\n저장 폴더: {output_dir}",
            )
            return

        self.status_var.set(f"조각 {len(saved_paths)}개를 저장했습니다: {output_dir}")
        messagebox.showinfo(
            "저장 끝",
            f"잘라 낸 조각 {len(saved_paths)}개를 저장했습니다.\n\n저장 폴더:\n{output_dir}",
        )

    def _resolve_output_suffix(self) -> str:
        assert self.loaded_image is not None

        if self.loaded_image.path is not None:
            suffix = self.loaded_image.path.suffix.lower()
            if suffix in SUPPORTED_IMAGE_SUFFIXES:
                return suffix
        return core.suffix_from_format(self.loaded_image.format_name)

    def _suffix_from_format_name(self, format_name: str | None) -> str:
        return core.suffix_from_format(format_name)

    def _build_output_path(self, output_dir: Path, base_name: str, suffix: str) -> Path:
        return core.build_output_path(output_dir, base_name, suffix)

    def _save_cropped_image(self, image: "Image.Image", target_path: Path) -> None:
        core.save_image(image, target_path)

    # ------------------------------------------------------------------
    # 글자 읽기
    # ------------------------------------------------------------------

    def _ocr_targets(self) -> list[tuple[str, "Image.Image"]]:
        """읽을 조각들. 영역이 없으면 사진 전체."""
        assert self.loaded_image is not None
        image = self.loaded_image.image
        targets: list[tuple[str, "Image.Image"]] = []
        for index, rectangle in enumerate(self.rectangles, start=1):
            rect = rectangle.normalized()
            if rect.right - rect.left < MIN_RECT_SIZE or rect.bottom - rect.top < MIN_RECT_SIZE:
                continue
            targets.append((f"영역 {index}", image.crop((rect.left, rect.top, rect.right, rect.bottom))))
        if not targets:
            targets.append(("사진 전체", image.copy()))
        return targets

    def run_ocr(self) -> None:
        if not self.loaded_image:
            messagebox.showwarning("글자 읽기", "먼저 사진을 열거나 붙여넣어 주세요.")
            return
        if self.ocr_running:
            return
        if self.ocr_settings.engine == "cpp":
            self.run_cpp_ocr()
            return

        targets = self._ocr_targets()
        settings = replace(self.ocr_settings)
        source_name = self.loaded_image.display_name
        save_stem = self.loaded_image.save_stem
        self._set_ocr_running(True)
        self.status_var.set(f"글자 읽기를 시작합니다: {len(targets)}개 조각 (내 PC Ollama)")

        def worker() -> None:
            started = time.perf_counter()
            results: list[tuple[str, str]] = []
            model = ""
            error: str | None = None
            try:
                client = core.OllamaClient(settings.ollama_host, timeout=settings.timeout_sec)
                model = client.pick_vision_model(settings.ollama_model)
                for index, (label, crop) in enumerate(targets, start=1):
                    self._post(lambda i=index, m=model: self.status_var.set(f"글자 읽는 중… {i}/{len(targets)} (모델 {m})"))
                    results.append((label, client.read_text(model, crop)))
            except core.OcrError as exc:
                error = str(exc)
            except Exception as exc:  # pragma: no cover - 예상 밖 오류도 화면에 알린다
                error = core.describe_error(exc)
            elapsed = time.perf_counter() - started
            self._post(lambda: self._finish_ocr("ollama", model, source_name, save_stem, results, error, elapsed))

        threading.Thread(target=worker, daemon=True).start()

    def _set_ocr_running(self, running: bool) -> None:
        self.ocr_running = running
        self._update_controls()

    def _finish_ocr(
        self,
        engine: str,
        model: str,
        source_name: str,
        save_stem: str,
        results: list[tuple[str, str]],
        error: str | None,
        elapsed: float,
        confidences: list[object] | None = None,
    ) -> None:
        self._set_ocr_running(False)
        if results:
            items = []
            for i, (label, text) in enumerate(results):
                items.append(
                    {
                        "file": label,
                        "text": text[:2000],
                        "confidence": confidences[i] if confidences and i < len(confidences) else None,
                    }
                )
            self._append_history_entry(
                job_type="ocr",
                source_images=[source_name],
                output_dir=None,
                saved_paths=[],
                rectangles_count=len(results),
                details={
                    "ocr": {
                        "engine": engine,
                        "model": model,
                        "elapsed_sec": round(elapsed, 2),
                        "items_count": len(items),
                        "items_preview": items,
                    }
                },
            )
        if error and not results:
            self.status_var.set("글자 읽기를 하지 못했습니다.")
            messagebox.showerror("글자 읽기", error)
            return
        self.status_var.set(f"글자 읽기 끝: {len(results)}개 조각, {elapsed:.1f}초")
        self._show_ocr_result_window(engine, model, save_stem, results, error, elapsed)

    def _show_ocr_result_window(
        self,
        engine: str,
        model: str,
        save_stem: str,
        results: list[tuple[str, str]],
        error: str | None,
        elapsed: float,
    ) -> None:
        window = tk.Toplevel(self.root)
        window.title("읽은 글자")
        window.geometry("760x560")
        window.transient(self.root)
        self._style_dialog(window)

        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        engine_label = f"모델 {model}" if engine == "ollama" else "C++ 실행기"
        summary = f"{engine_label} · 조각 {len(results)}개 · {elapsed:.1f}초"
        if error:
            summary += "\n중간에 멈췄습니다: " + error.splitlines()[0]
        ttk.Label(frame, text=summary, justify="left").grid(row=0, column=0, sticky="w", pady=(0, 8))

        text_frame = ttk.Frame(frame)
        text_frame.grid(row=1, column=0, sticky="nsew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        text_widget = tk.Text(text_frame, wrap="word", font=("Malgun Gothic", 11))
        text_widget.grid(row=0, column=0, sticky="nsew")
        self._style_text_widget(text_widget)
        scroll = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        text_widget.configure(yscrollcommand=scroll.set)
        text_widget.insert("1.0", core.format_ocr_results(results))

        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, sticky="e", pady=(10, 0))

        def copy_all() -> None:
            content = text_widget.get("1.0", "end-1c")
            window.clipboard_clear()
            window.clipboard_append(content)
            self.status_var.set("읽은 글자를 클립보드에 복사했습니다.")

        def save_text() -> None:
            initial_dir = self.output_dir if self.output_dir and self.output_dir.is_dir() else Path.cwd()
            target = filedialog.asksaveasfilename(
                title="읽은 글자 저장",
                parent=window,
                initialdir=str(initial_dir),
                initialfile=f"{save_stem}_글자.txt",
                defaultextension=".txt",
                filetypes=TEXT_FILE_TYPES,
            )
            if not target:
                return
            try:
                core.write_text_atomic(Path(target), text_widget.get("1.0", "end-1c"))
            except OSError as exc:
                messagebox.showerror("저장 실패", core.describe_error(exc), parent=window)
                return
            self.status_var.set(f"읽은 글자를 저장했습니다: {target}")

        ttk.Button(buttons, text="전부 복사", command=copy_all).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="텍스트로 저장", command=save_text).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="닫기", command=window.destroy).pack(side="left")

    def open_ocr_settings_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("글자 읽기 설정")
        dialog.geometry("640x430")
        dialog.minsize(560, 400)
        dialog.transient(self.root)
        dialog.grab_set()
        self._style_dialog(dialog)

        settings = self.ocr_settings
        engine_var = tk.StringVar(value=settings.engine)
        host_var = tk.StringVar(value=settings.ollama_host)
        model_var = tk.StringVar(value=settings.ollama_model)
        timeout_var = tk.StringVar(value=str(settings.timeout_sec))
        info_var = tk.StringVar(value="모델을 비워 두면 그림을 읽을 수 있는 모델을 자동으로 고릅니다.")

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="읽는 방식").grid(row=0, column=0, sticky="w")
        engine_frame = ttk.Frame(frame)
        engine_frame.grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(engine_frame, text="내 PC Ollama (기본)", variable=engine_var, value="ollama").pack(side="left")
        ttk.Radiobutton(engine_frame, text="C++ 실행기 (고급)", variable=engine_var, value="cpp").pack(side="left", padx=(12, 0))

        ttk.Label(frame, text="Ollama 주소").grid(row=1, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=host_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(10, 0))

        ttk.Label(frame, text="모델").grid(row=2, column=0, sticky="w", pady=(10, 0))
        model_combo = ttk.Combobox(frame, textvariable=model_var, values=[])
        model_combo.grid(row=2, column=1, sticky="ew", pady=(10, 0))
        find_button = ttk.Button(frame, text="모델 찾기")
        find_button.grid(row=2, column=2, sticky="e", padx=(8, 0), pady=(10, 0))

        ttk.Label(frame, text="기다리는 시간(초)").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=timeout_var, width=10).grid(row=3, column=1, sticky="w", pady=(10, 0))

        ttk.Label(frame, textvariable=info_var, wraplength=580, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w", pady=(12, 0)
        )

        cpp_frame = ttk.LabelFrame(frame, text="C++ 실행기 (고급)", padding=10)
        cpp_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        ttk.Label(
            cpp_frame,
            text=f"직접 빌드한 실행기와 모델 파일(detector.engine, recognizer.engine)이 있어야 합니다.\n모델 폴더: {DEFAULT_OCR_MODEL_DIR}",
            wraplength=560,
            justify="left",
        ).pack(anchor="w")
        ttk.Button(cpp_frame, text="모델 넣기", command=self.import_ocr_model_package).pack(anchor="w", pady=(8, 0))

        def find_models() -> None:
            host = host_var.get()
            find_button.config(state="disabled")
            info_var.set("Ollama에서 모델을 찾는 중…")

            def worker() -> None:
                try:
                    client = core.OllamaClient(host, timeout=30)
                    names = client.list_models()
                    vision = client.vision_models()
                except core.OcrError as exc:
                    message = str(exc)
                    self._post(lambda: (find_button.config(state="normal"), info_var.set(message)))
                    return

                def show() -> None:
                    find_button.config(state="normal")
                    model_combo.config(values=vision)
                    if vision:
                        info_var.set(f"그림을 읽을 수 있는 모델 {len(vision)}개: {', '.join(vision)}")
                        if not model_var.get().strip():
                            model_var.set(vision[0])
                    else:
                        info_var.set(core.no_vision_model_message(names))

                self._post(show)

            threading.Thread(target=worker, daemon=True).start()

        find_button.config(command=find_models)

        def save() -> None:
            try:
                host = core.normalize_local_host(host_var.get())
            except core.OcrError as exc:
                messagebox.showerror("설정 저장", str(exc), parent=dialog)
                return
            try:
                timeout = int(timeout_var.get().strip())
                if not 10 <= timeout <= 3600:
                    raise ValueError
            except ValueError:
                messagebox.showerror("설정 저장", "기다리는 시간은 10~3600초 사이 정수로 넣어 주세요.", parent=dialog)
                return
            self.ocr_settings = core.OcrSettings(
                engine=engine_var.get(),
                ollama_host=host,
                ollama_model=model_var.get().strip(),
                timeout_sec=timeout,
            )
            try:
                core.save_ocr_settings(self.ocr_settings_path, self.ocr_settings)
            except OSError as exc:
                messagebox.showwarning("설정 저장", f"이번 실행에는 적용했지만 파일로 저장하지 못했습니다.\n{core.describe_error(exc)}", parent=dialog)
            self.status_var.set("글자 읽기 설정을 저장했습니다.")
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=3, sticky="e", pady=(16, 0))
        ttk.Button(buttons, text="저장", command=save).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="닫기", command=dialog.destroy).pack(side="left")

        dialog.wait_window()

    # C++ 실행기(고급) -----------------------------------------------------

    def _resolve_cpp_ocr_executable(self) -> Path:
        candidates = [
            APP_DIR / "bin" / "ocr_trt_runner.exe",
            APP_DIR / "bin" / "ocr_trt_runner",
            APP_DIR / "cpp" / "ocr_engine" / "build" / "Release" / "ocr_trt_runner.exe",
            APP_DIR / "cpp" / "ocr_engine" / "build" / "ocr_trt_runner.exe",
            APP_DIR / "cpp" / "ocr_engine" / "build" / "ocr_trt_runner",
        ]
        for path in candidates:
            if path.is_file():
                return path
        return candidates[0]

    def _validate_ocr_model_dir(self, model_dir: Path) -> tuple[bool, list[str]]:
        missing = [name for name in REQUIRED_OCR_MODEL_FILES if not (model_dir / name).is_file()]
        return len(missing) == 0, missing

    def import_ocr_model_package(self) -> None:
        package_path = filedialog.askopenfilename(
            title="글자 읽기 모델 ZIP 고르기",
            filetypes=[("ZIP 파일", "*.zip"), ("모든 파일", "*.*")],
        )
        if not package_path:
            return

        destination = DEFAULT_OCR_MODEL_DIR
        try:
            # 임시 폴더에 풀지 않고, 필요한 두 파일만 ZIP에서 바로 꺼내 쓴다.
            with zipfile.ZipFile(package_path, "r") as zf:
                members = {Path(info.filename).name: info for info in zf.infolist() if not info.is_dir()}
                missing = [name for name in REQUIRED_OCR_MODEL_FILES if name not in members]
                if missing:
                    messagebox.showerror(
                        "모델 넣기 실패",
                        f"ZIP 안에서 다음 파일을 찾지 못했습니다: {', '.join(missing)}",
                    )
                    return
                destination.mkdir(parents=True, exist_ok=True)
                for file_name in REQUIRED_OCR_MODEL_FILES:
                    with zf.open(members[file_name]) as src, open(destination / file_name, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        except (OSError, zipfile.BadZipFile) as exc:
            detail = "ZIP 파일이 손상됐습니다." if isinstance(exc, zipfile.BadZipFile) else core.describe_error(exc)
            messagebox.showerror("모델 넣기 실패", f"모델 ZIP을 처리하지 못했습니다.\n{detail}")
            return

        self.status_var.set(f"글자 읽기 모델을 넣었습니다: {destination}")
        messagebox.showinfo("모델 넣기 끝", f"모델 파일을 넣었습니다.\n{destination}")

    def run_cpp_ocr(self) -> None:
        if not self.loaded_image:
            messagebox.showwarning("글자 읽기", "먼저 사진을 열거나 붙여넣어 주세요.")
            return

        executable = self._resolve_cpp_ocr_executable()
        if not executable.is_file():
            messagebox.showerror(
                "실행기 없음",
                (
                    "C++ 글자 읽기 실행기를 찾지 못했습니다.\n\n"
                    f"찾은 곳: {executable}\n"
                    "cpp/ocr_engine을 빌드하거나, '읽기 설정'에서 '내 PC Ollama'로 바꿔 주세요."
                ),
            )
            return

        is_valid_model, missing_files = self._validate_ocr_model_dir(DEFAULT_OCR_MODEL_DIR)
        if not is_valid_model:
            messagebox.showerror(
                "모델 파일 없음",
                (
                    f"필요한 모델 파일: {', '.join(REQUIRED_OCR_MODEL_FILES)}\n"
                    f"빠진 파일: {', '.join(missing_files)}\n\n"
                    "'읽기 설정'의 '모델 넣기'로 ZIP을 넣어 주세요."
                ),
            )
            return

        targets = self._ocr_targets()
        source_name = self.loaded_image.display_name
        save_stem = self.loaded_image.save_stem
        work_dir = self.data_dir / ".ocr_work" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self._set_ocr_running(True)
        self.status_var.set("C++ 실행기로 글자를 읽는 중…")

        def worker() -> None:
            started = time.perf_counter()
            results: list[tuple[str, str]] = []
            confidences: list[object] = []
            error: str | None = None
            try:
                input_dir = work_dir / "inputs"
                input_dir.mkdir(parents=True, exist_ok=True)
                output_json = work_dir / "ocr_result.json"
                names: dict[str, str] = {}
                for index, (label, crop) in enumerate(targets, start=1):
                    file_name = f"crop_{index:02d}.png"
                    core.save_image(crop, input_dir / file_name)
                    names[file_name] = label
                command = [
                    str(executable),
                    "--input-dir", str(input_dir),
                    "--output-json", str(output_json),
                    "--model-dir", str(DEFAULT_OCR_MODEL_DIR),
                ]
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=CPP_OCR_TIMEOUT_SEC,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                if completed.returncode != 0:
                    raise core.OcrError(
                        f"C++ 실행기가 실패했습니다(종료 코드 {completed.returncode}).\n{(completed.stderr or '').strip()[:800]}"
                    )
                if not output_json.is_file():
                    raise core.OcrError("C++ 실행기가 결과 파일(ocr_result.json)을 만들지 않았습니다.")
                data = json.loads(output_json.read_text(encoding="utf-8"))
                items = data.get("results", []) if isinstance(data, dict) else []
                for item in items if isinstance(items, list) else []:
                    if not isinstance(item, dict):
                        continue
                    file_name = Path(str(item.get("file", "-"))).name
                    results.append((names.get(file_name, file_name), str(item.get("text", "")).strip()))
                    confidences.append(item.get("confidence"))
            except subprocess.TimeoutExpired:
                error = f"C++ 실행기가 {CPP_OCR_TIMEOUT_SEC}초 안에 끝나지 않았습니다."
            except (core.OcrError, ValueError) as exc:
                error = str(exc)
            except Exception as exc:
                error = core.describe_error(exc)
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)
            elapsed = time.perf_counter() - started
            self._post(lambda: self._finish_ocr("cpp", "", source_name, save_stem, results, error, elapsed, confidences))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 작업 기록
    # ------------------------------------------------------------------

    def _history_file_path(self) -> Path:
        return self.history_path

    def _append_history_entry(
        self,
        job_type: str,
        source_images: list[str],
        output_dir: Path | None,
        saved_paths: list[Path],
        rectangles_count: int,
        details: dict[str, object] | None = None,
    ) -> None:
        entry = core.make_history_entry(job_type, source_images, output_dir, saved_paths, rectangles_count, details)
        try:
            core.append_history(self._history_file_path(), entry)
        except OSError:
            self.status_var.set("작업은 끝났지만 작업 기록 파일에 적지 못했습니다.")

    def _read_history_entries(self, limit: int = HISTORY_PAGE_SIZE, skip: int = 0) -> tuple[list[dict[str, object]], bool]:
        return core.read_recent_history(self._history_file_path(), limit=limit, skip=skip)

    def open_history_viewer(self) -> None:
        first_page, has_more_initial = self._read_history_entries()
        if not first_page:
            messagebox.showinfo("기록", "아직 남은 작업 기록이 없습니다.")
            return

        entries: list[dict[str, object]] = list(first_page)
        state = {"has_more": has_more_initial}

        dialog = tk.Toplevel(self.root)
        dialog.title("작업 기록")
        dialog.geometry("980x600")
        dialog.transient(self.root)
        self._style_dialog(dialog)

        container = ttk.Frame(dialog, padding=12)
        container.pack(fill="both", expand=True)
        container.rowconfigure(2, weight=1)
        container.columnconfigure(0, weight=1)

        filter_frame = ttk.Frame(container)
        filter_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        filter_frame.columnconfigure(7, weight=1)

        ttk.Label(filter_frame, text="시작일(YYYY-MM-DD)").grid(row=0, column=0, sticky="w")
        start_date_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=start_date_var, width=12).grid(row=0, column=1, padx=(4, 10))

        ttk.Label(filter_frame, text="종료일").grid(row=0, column=2, sticky="w")
        end_date_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=end_date_var, width=12).grid(row=0, column=3, padx=(4, 10))

        ttk.Label(filter_frame, text="작업 종류").grid(row=0, column=4, sticky="w")
        job_type_var = tk.StringVar(value="전체")
        ttk.Combobox(
            filter_frame,
            textvariable=job_type_var,
            values=list(JOB_FILTER_LABELS),
            width=9,
            state="readonly",
        ).grid(row=0, column=5, padx=(4, 10))

        ttk.Label(filter_frame, text="읽은 글자 검색").grid(row=0, column=6, sticky="w")
        ocr_query_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=ocr_query_var, width=20).grid(row=0, column=7, sticky="ew", padx=(4, 8))

        ttk.Label(filter_frame, text="정렬").grid(row=0, column=8, sticky="w")
        sort_var = tk.StringVar(value="최신순")
        ttk.Combobox(
            filter_frame,
            textvariable=sort_var,
            values=["최신순", "오래된순", "저장개수순"],
            width=10,
            state="readonly",
        ).grid(row=0, column=9, padx=(4, 8))

        preset_frame = ttk.Frame(container)
        preset_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(preset_frame, text="빠른 기간").pack(side="left", padx=(0, 6))

        notebook = ttk.Notebook(container)
        notebook.grid(row=2, column=0, sticky="nsew")

        history_tab = ttk.Frame(notebook, padding=8)
        history_tab.columnconfigure(0, weight=1)
        history_tab.rowconfigure(0, weight=1)
        notebook.add(history_tab, text="기록 목록")

        list_frame = ttk.Frame(history_tab)
        list_frame.grid(row=0, column=0, sticky="nsew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        listbox = Listbox(list_frame, exportselection=False)
        listbox.grid(row=0, column=0, sticky="nsew")
        self._style_listbox(listbox)
        list_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
        list_scroll.grid(row=0, column=1, sticky="ns")
        listbox.configure(yscrollcommand=list_scroll.set)

        ocr_tab = ttk.Frame(notebook, padding=8)
        ocr_tab.columnconfigure(0, weight=1)
        ocr_tab.rowconfigure(1, weight=1)
        notebook.add(ocr_tab, text="읽은 글자")
        ocr_control_frame = ttk.Frame(ocr_tab)
        ocr_control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ocr_control_frame.columnconfigure(2, weight=1)
        ttk.Label(ocr_control_frame, text="확신도 기준(C++ 실행기 결과만)").grid(row=0, column=0, sticky="w")
        confidence_threshold_var = tk.DoubleVar(value=0.0)
        confidence_scale = ttk.Scale(
            ocr_control_frame,
            from_=0.0,
            to=1.0,
            variable=confidence_threshold_var,
            orient="horizontal",
            length=220,
        )
        confidence_scale.grid(row=0, column=1, padx=(8, 8), sticky="w")
        confidence_value_label = ttk.Label(ocr_control_frame, text="0.00")
        confidence_value_label.grid(row=0, column=2, sticky="w")

        ocr_text = tk.Text(ocr_tab, wrap="word", state="disabled")
        ocr_text.grid(row=1, column=0, sticky="nsew")
        self._style_text_widget(ocr_text)

        json_tab = ttk.Frame(notebook, padding=8)
        json_tab.columnconfigure(0, weight=1)
        json_tab.rowconfigure(0, weight=1)
        notebook.add(json_tab, text="자세히")
        detail_text = tk.Text(json_tab, wrap="word", state="disabled")
        detail_text.grid(row=0, column=0, sticky="nsew")
        self._style_text_widget(detail_text)

        footer = ttk.Frame(container)
        footer.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        footer.columnconfigure(0, weight=1)
        loaded_var = tk.StringVar()
        ttk.Label(footer, textvariable=loaded_var).grid(row=0, column=0, sticky="w")
        more_button = ttk.Button(footer, text="더 보기")
        more_button.grid(row=0, column=1, sticky="e")

        filtered_entries: list[dict[str, object]] = []

        def update_loaded_label() -> None:
            text = f"최근 기록 {len(entries)}건을 불러왔습니다(검색·필터는 불러온 범위 안에서)."
            if state["has_more"]:
                text += " 더 오래된 기록이 있습니다."
            loaded_var.set(text)
            more_button.config(state="normal" if state["has_more"] else "disabled")

        def _parse_date(date_text: str, is_end: bool) -> datetime | None:
            value = date_text.strip()
            if not value:
                return None
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                return None
            if is_end:
                return parsed.replace(hour=23, minute=59, second=59)
            return parsed

        def _render_text(widget: tk.Text, value: str) -> None:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.insert("end", value)
            widget.configure(state="disabled")

        def _ocr_items(entry: dict[str, object]) -> list[dict[str, object]]:
            details = entry.get("details")
            if not isinstance(details, dict):
                return []
            ocr_info = details.get("ocr")
            if not isinstance(ocr_info, dict):
                return []
            items = ocr_info.get("items_preview")
            return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

        def _format_entry_label(entry: dict[str, object]) -> str:
            ts = str(entry.get("timestamp", "-")).replace("T", " ")
            job = str(entry.get("job_type", "single"))
            job_label = core.JOB_TYPE_LABELS.get(job, job)
            sources = entry.get("source_images")
            first_source = str(sources[0]) if isinstance(sources, list) and sources else ""
            if job == "ocr":
                return f"[{ts}] {job_label} · 조각 {len(_ocr_items(entry))}개 · {first_source}"
            count = core.safe_int(entry.get("saved_count"))
            source_count = core.safe_int(entry.get("source_count"), len(sources) if isinstance(sources, list) else 0)
            if job == "batch":
                return f"[{ts}] {job_label} · 사진 {source_count}장 · 조각 {count}개 저장"
            return f"[{ts}] {job_label} · 조각 {count}개 저장 · {first_source}"

        def _match_ocr_text(entry: dict[str, object], query: str) -> bool:
            if not query:
                return True
            lowered = query.lower()
            return any(lowered in str(item.get("text", "")).lower() for item in _ocr_items(entry))

        def _apply_quick_preset(days: int) -> None:
            today = datetime.now().date()
            start_date = today - timedelta(days=days - 1)
            start_date_var.set(start_date.strftime("%Y-%m-%d"))
            end_date_var.set(today.strftime("%Y-%m-%d"))
            refresh_history_list()

        def render_selected(_event: tk.Event | None = None) -> None:
            selected = listbox.curselection()
            if not selected or selected[0] >= len(filtered_entries):
                return
            entry = filtered_entries[selected[0]]
            _render_text(detail_text, json.dumps(entry, ensure_ascii=False, indent=2))

            threshold = float(confidence_threshold_var.get())
            lines: list[str] = []
            for idx, item in enumerate(_ocr_items(entry), start=1):
                text = str(item.get("text", "")).strip()
                label = str(item.get("file", "-"))
                conf = item.get("confidence")
                conf_value: float | None = None
                if isinstance(conf, (int, float)) and not isinstance(conf, bool):
                    conf_value = float(conf)
                elif isinstance(conf, str):
                    try:
                        conf_value = float(conf)
                    except ValueError:
                        conf_value = None
                if conf_value is not None and conf_value < threshold:
                    continue
                mark = ""
                if conf_value is not None:
                    mark = f" (확신도 {conf_value:.2f}{', 낮음' if conf_value < 0.5 else ''})"
                lines.append(f"{idx:02d}. {label}{mark}\n{text}\n")
            _render_text(
                ocr_text,
                "\n".join(lines) if lines else "고른 기록에 읽은 글자가 없거나 확신도 기준에 맞는 결과가 없습니다.",
            )

        def refresh_history_list(*_args: object) -> None:
            filtered_entries.clear()
            listbox.delete(0, "end")

            start_date = _parse_date(start_date_var.get(), is_end=False)
            end_date = _parse_date(end_date_var.get(), is_end=True)
            selected_job = JOB_FILTER_LABELS.get(job_type_var.get().strip())
            query = ocr_query_var.get().strip()

            for entry in entries:
                try:
                    entry_ts: datetime | None = datetime.fromisoformat(str(entry.get("timestamp", "")))
                except ValueError:
                    entry_ts = None

                if start_date and entry_ts and entry_ts < start_date:
                    continue
                if end_date and entry_ts and entry_ts > end_date:
                    continue
                if selected_job is not None and str(entry.get("job_type", "single")) != selected_job:
                    continue
                if query and not _match_ocr_text(entry, query):
                    continue
                filtered_entries.append(entry)

            selected_sort = sort_var.get().strip()
            if selected_sort == "오래된순":
                filtered_entries.sort(key=lambda item: str(item.get("timestamp", "")))
            elif selected_sort == "저장개수순":
                filtered_entries.sort(key=lambda item: core.safe_int(item.get("saved_count")), reverse=True)
            else:
                filtered_entries.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)

            for idx, entry in enumerate(filtered_entries):
                listbox.insert(idx, _format_entry_label(entry))

            if filtered_entries:
                listbox.selection_set(0)
                render_selected()
            else:
                _render_text(detail_text, "조건에 맞는 기록이 없습니다.")
                _render_text(ocr_text, "고른 기록이 없습니다.")
            update_loaded_label()

        def load_more() -> None:
            page, has_more = self._read_history_entries(skip=len(entries))
            entries.extend(page)
            state["has_more"] = has_more and bool(page)
            refresh_history_list()

        more_button.config(command=load_more)

        ttk.Button(preset_frame, text="오늘", command=lambda: _apply_quick_preset(1)).pack(side="left", padx=(0, 4))
        ttk.Button(preset_frame, text="7일", command=lambda: _apply_quick_preset(7)).pack(side="left", padx=(0, 4))
        ttk.Button(preset_frame, text="30일", command=lambda: _apply_quick_preset(30)).pack(side="left", padx=(0, 4))

        apply_filter_btn = ttk.Button(filter_frame, text="찾기", command=refresh_history_list)
        apply_filter_btn.grid(row=0, column=10, padx=(0, 6))
        reset_filter_btn = ttk.Button(
            filter_frame,
            text="처음으로",
            command=lambda: (
                start_date_var.set(""),
                end_date_var.set(""),
                job_type_var.set("전체"),
                ocr_query_var.set(""),
                sort_var.set("최신순"),
                refresh_history_list(),
            ),
        )
        reset_filter_btn.grid(row=0, column=11)

        listbox.bind("<<ListboxSelect>>", render_selected)
        confidence_scale.configure(command=lambda _value: (confidence_value_label.configure(text=f"{confidence_threshold_var.get():.2f}"), render_selected()))
        refresh_history_list()

    # ------------------------------------------------------------------
    # 좌표 계산
    # ------------------------------------------------------------------

    def _event_to_image_point(self, event: tk.Event) -> tuple[int, int] | None:
        return self._canvas_point_to_image_point(event.x, event.y, clamp=True)

    def _canvas_point_to_image_point(
        self,
        canvas_x: int,
        canvas_y: int,
        clamp: bool = False,
    ) -> tuple[int, int] | None:
        if not self.loaded_image:
            return None

        image_x = round(self.canvas.canvasx(canvas_x) / self.zoom)
        image_y = round(self.canvas.canvasy(canvas_y) / self.zoom)

        if clamp:
            image_x = min(max(image_x, 0), self.loaded_image.width)
            image_y = min(max(image_y, 0), self.loaded_image.height)
            return image_x, image_y

        if 0 <= image_x <= self.loaded_image.width and 0 <= image_y <= self.loaded_image.height:
            return image_x, image_y
        return None

    def _find_rectangle_at(self, x: int, y: int) -> int | None:
        for index in range(len(self.rectangles) - 1, -1, -1):
            rectangle = self.rectangles[index].normalized()
            if rectangle.left <= x <= rectangle.right and rectangle.top <= y <= rectangle.bottom:
                return index
        return None

    def _find_shared_edge_at(self, x: int, y: int) -> core.SharedEdge | None:
        """이웃 두 칸의 공유 경계(또는 그 사이 여백) 위인지. 화면에서 손잡이 크기만큼 여유를 둔다."""
        if len(self.rectangles) < 2:
            return None
        tolerance = HANDLE_SIZE / max(self.zoom, 1e-6)
        return core.find_shared_edge([r.as_tuple() for r in self.rectangles], x, y, tolerance)

    def _find_handle_at(self, x: int, y: int) -> str | None:
        if self.selected_rectangle_index is None or self.selected_rectangle_index >= len(self.rectangles):
            return None

        rect = self.rectangles[self.selected_rectangle_index]
        hitboxes = self._get_handle_hitboxes(rect)

        for name, (x1, y1, x2, y2) in hitboxes.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                return name
        return None

    def _move_rectangle_within_bounds(self, rectangle: CropRectangle, dx: int, dy: int) -> CropRectangle:
        assert self.loaded_image is not None

        normalized = rectangle.normalized()
        width = normalized.right - normalized.left
        height = normalized.bottom - normalized.top
        max_left = max(self.loaded_image.width - width, 0)
        max_top = max(self.loaded_image.height - height, 0)

        left = min(max(normalized.left + dx, 0), max_left)
        top = min(max(normalized.top + dy, 0), max_top)
        return CropRectangle(left, top, left + width, top + height)

    def _resize_rectangle(
        self, rect: CropRectangle, handle: str, mx: int, my: int, shift_pressed: bool = False
    ) -> CropRectangle:
        l, t, r, b = rect.left, rect.top, rect.right, rect.bottom

        is_corner_handle = "-" in handle
        if shift_pressed and is_corner_handle:
            orig_width = r - l
            orig_height = b - t

            if orig_width != 0 and orig_height != 0:
                aspect_ratio = orig_width / orig_height

                fl, ft, fr, fb = float(l), float(t), float(r), float(b)
                fmx = float(mx)

                if handle == "bottom-right":  # 고정점: 왼쪽 위
                    fr = fmx
                    fb = ft + (fr - fl) / aspect_ratio
                elif handle == "top-left":  # 고정점: 오른쪽 아래
                    fl = fmx
                    ft = fb - (fr - fl) / aspect_ratio
                elif handle == "top-right":  # 고정점: 왼쪽 아래
                    fr = fmx
                    ft = fb - (fr - fl) / aspect_ratio
                elif handle == "bottom-left":  # 고정점: 오른쪽 위
                    fl = fmx
                    fb = ft + (fr - fl) / aspect_ratio

                return CropRectangle(round(fl), round(ft), round(fr), round(fb))

        if "top" in handle:
            t = my
        if "bottom" in handle:
            b = my
        if "left" in handle:
            l = mx
        if "right" in handle:
            r = mx

        return CropRectangle(l, t, r, b)

    def _normalize_rectangle(self, rectangle: CropRectangle) -> CropRectangle | None:
        assert self.loaded_image is not None
        rects = core.clamp_rects([rectangle.as_tuple()], self.loaded_image.width, self.loaded_image.height)
        return CropRectangle.from_tuple(rects[0]) if rects else None

    def _normalize_rectangles_collection(self, rectangles: list[CropRectangle]) -> list[CropRectangle]:
        assert self.loaded_image is not None
        rects = core.clamp_rects([r.as_tuple() for r in rectangles], self.loaded_image.width, self.loaded_image.height)
        return [CropRectangle.from_tuple(r) for r in rects]

    # ------------------------------------------------------------------
    # 겹쳐 그리기
    # ------------------------------------------------------------------

    def _refresh_overlays(self) -> None:
        self.canvas.delete("overlay")
        if not self.loaded_image:
            return

        for index, rectangle in enumerate(self.rectangles):
            rect = rectangle.normalized()
            selected = index == self.selected_rectangle_index
            outline = self.colors["accent"] if selected else self.colors["cool"]
            fill = "#3b1f08" if selected else "#0d2731"
            width = 3 if selected else 2
            dash = None if selected else (8, 4)

            left = round(rect.left * self.zoom)
            top = round(rect.top * self.zoom)
            right = round(rect.right * self.zoom)
            bottom = round(rect.bottom * self.zoom)

            self.canvas.create_rectangle(
                left,
                top,
                right,
                bottom,
                fill=fill,
                outline=outline,
                width=width,
                dash=dash,
                stipple="gray25",
                tags=("overlay",),
            )
            self.canvas.create_text(
                left + 8,
                top + 8,
                text=str(index + 1),
                anchor="nw",
                fill=outline,
                font=("Malgun Gothic", 11, "bold"),
                tags=("overlay",),
            )

            if selected:
                self._draw_handles(rect)

    def _draw_handles(self, rect: CropRectangle) -> None:
        handle_offset = HANDLE_SIZE / 2
        fill = self.colors["accent"]
        outline = self.colors["text"]
        tags = ("overlay", "handle")

        positions = self._get_handle_canvas_positions(rect)

        for pos in positions.values():
            self.canvas.create_rectangle(
                pos[0] - handle_offset,
                pos[1] - handle_offset,
                pos[0] + handle_offset,
                pos[1] + handle_offset,
                fill=fill,
                outline=outline,
                tags=tags,
            )

    def _get_handle_canvas_positions(self, rect: CropRectangle) -> dict[str, tuple[float, float]]:
        r = rect.normalized()
        left = r.left * self.zoom
        top = r.top * self.zoom
        right = r.right * self.zoom
        bottom = r.bottom * self.zoom
        mid_x = (left + right) / 2
        mid_y = (top + bottom) / 2

        return {
            "top-left": (left, top),
            "top-right": (right, top),
            "bottom-left": (left, bottom),
            "bottom-right": (right, bottom),
            "top": (mid_x, top),
            "bottom": (mid_x, bottom),
            "left": (left, mid_y),
            "right": (right, mid_y),
        }

    def _get_handle_hitboxes(self, rect: CropRectangle) -> dict[str, tuple[float, float, float, float]]:
        if not self.loaded_image:
            return {}

        handle_size_in_image_coords = HANDLE_SIZE / self.zoom
        offset = handle_size_in_image_coords / 2

        r = rect.normalized()
        mid_x = (r.left + r.right) / 2
        mid_y = (r.top + r.bottom) / 2

        return {
            "top-left": (r.left - offset, r.top - offset, r.left + offset, r.top + offset),
            "top-right": (r.right - offset, r.top - offset, r.right + offset, r.top + offset),
            "bottom-left": (r.left - offset, r.bottom - offset, r.left + offset, r.bottom + offset),
            "bottom-right": (r.right - offset, r.bottom - offset, r.right + offset, r.bottom + offset),
            "top": (mid_x - offset, r.top - offset, mid_x + offset, r.top + offset),
            "bottom": (mid_x - offset, r.bottom - offset, mid_x + offset, r.bottom + offset),
            "left": (r.left - offset, mid_y - offset, r.left + offset, mid_y + offset),
            "right": (r.right - offset, mid_y - offset, r.right + offset, mid_y + offset),
        }


def main() -> int:
    if PIL_IMPORT_ERROR is not None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "실행 오류",
            "Pillow가 필요합니다.\n\n현재 폴더에서 아래 명령을 먼저 실행하세요.\n\npip install -r requirements.txt",
        )
        root.destroy()
        return 1

    import argparse

    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("image", nargs="?", help="시작하면서 열 사진(실행 파일 위에 사진을 끌어 놓아도 된다)")
    parser.add_argument("--quick-grid", choices=list(QUICK_GRIDS), help="사진을 연 뒤 4칸·9칸으로 나눠 둔다(저장은 하지 않음)")
    args, _unknown = parser.parse_known_args()

    root = tk.Tk()
    app = AutoCropApp(root)
    if args.image:
        image_path = Path(args.image)
        if app._load_image_from_path(image_path) and args.quick_grid:
            rows, cols = QUICK_GRIDS[args.quick_grid]
            app._apply_auto_grid(rows, cols, app.detect_gutters_var.get(), confirm=True)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
