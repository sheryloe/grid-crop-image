from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import Listbox
from tkinter import filedialog, messagebox, ttk

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


APP_TITLE = "Grid Crop Studio"
SUPPORTED_FILE_TYPES = [
    ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
    ("All files", "*.*"),
]
CONFIG_FILE_TYPES = [
    ("JSON files", "*.json"),
    ("All files", "*.*"),
]
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
MIN_RECT_SIZE = 4
HANDLE_SIZE = 8  # In canvas pixels
MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25
CONTROL_MASK = 0x0004
SHIFT_MASK = 0x0001
HISTORY_FILENAME = ".crop_history.jsonl"
DEFAULT_OCR_MODEL_DIR = Path("cpp/ocr_engine/models")
REQUIRED_OCR_MODEL_FILES = ("detector.engine", "recognizer.engine")


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
        self.root.geometry("1440x940")
        self.root.minsize(1080, 720)

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
        self.last_batch_context: dict[str, object] | None = None
        self.last_batch_failures: list[Path] = []

        self.zoom_var = tk.StringVar(value="100%")
        self.output_dir_var = tk.StringVar(value="아직 정하지 않음")
        self.status_var = tk.StringVar(
            value="사진을 열거나 붙여넣으면 바로 자르기 작업을 시작할 수 있습니다."
        )
        self.instruction_var = tk.StringVar(
            value=(
                "빈 화면에서 드래그하면 자를 영역이 생깁니다. 영역 안을 끌면 이동하고, 모서리를 끌면 크기가 바뀝니다. "
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

        style.configure("Action.TButton", background=self.colors["surface"], foreground=self.colors["text"], padding=(12, 9), relief="solid", borderwidth=1, font=("Segoe UI Semibold", 9))
        style.map(
            "Action.TButton",
            background=[("active", "#fff2e7"), ("disabled", self.colors["surface_alt"])],
            foreground=[("disabled", "#9e9a92")],
            bordercolor=[("active", self.colors["accent"]), ("!active", self.colors["line"])],
            lightcolor=[("active", self.colors["accent"]), ("!active", self.colors["line"])],
            darkcolor=[("active", self.colors["accent"]), ("!active", self.colors["line"])],
        )
        style.configure("Accent.TButton", background=self.colors["accent"], foreground="#ffffff", padding=(14, 10), relief="flat", borderwidth=0, font=("Bahnschrift SemiBold", 10))
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

    def _create_info_card(self, parent: ttk.Frame, title: str, value_var: tk.StringVar) -> ttk.Frame:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(12, 12))
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, textvariable=value_var, style="CardValue.TLabel", wraplength=250, justify="left").pack(anchor="w", pady=(6, 0))
        return card

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

        hero = ttk.Frame(wrapper, style="Hero.TFrame", padding=(22, 18))
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        hero.columnconfigure(0, weight=1)

        hero_brand = ttk.Frame(hero, style="Hero.TFrame")
        hero_brand.grid(row=0, column=0, sticky="w")
        ttk.Label(hero_brand, text="GC", style="LogoBadge.TLabel").pack(side="left")
        title_block = ttk.Frame(hero_brand, style="Hero.TFrame")
        title_block.pack(side="left", padx=(14, 0))
        ttk.Label(title_block, text=APP_TITLE, style="HeroTitle.TLabel").pack(anchor="w")
        ttk.Label(
            title_block,
            text="여러 장 사진 자르기, 저장, 글자 읽기를 한 화면에서 빠르게 처리하는 작업 도구입니다.",
            style="HeroBody.TLabel",
            wraplength=840,
            justify="left",
        ).pack(anchor="w", pady=(6, 0))

        hero_pills = ttk.Frame(hero, style="Hero.TFrame")
        hero_pills.grid(row=0, column=1, rowspan=2, sticky="e")
        ttk.Label(hero_pills, textvariable=self.mode_summary_var, style="Pill.TLabel").pack(side="left")
        ttk.Label(hero_pills, textvariable=self.zoom_var, style="PillMuted.TLabel").pack(side="left", padx=(8, 0))

        action_row = ttk.Frame(wrapper, style="App.TFrame")
        action_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        action_row.columnconfigure(0, weight=3)
        action_row.columnconfigure(1, weight=4)
        action_row.columnconfigure(2, weight=3)

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
        self.ocr_button = ttk.Button(process_row, text="글자 읽기", command=self.run_cpp_ocr, style="Action.TButton")
        self.ocr_button.pack(side="left", padx=(8, 0))
        self.import_model_button = ttk.Button(process_row, text="모델 넣기", command=self.import_ocr_model_package, style="Action.TButton")
        self.import_model_button.pack(side="left", padx=(8, 0))

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
        ttk.Separator(view_row, orient="vertical").pack(side="left", fill="y", padx=10)
        self.delete_button = ttk.Button(view_row, text="지우기", command=self.delete_selected_rectangle, style="Action.TButton")
        self.delete_button.pack(side="left")
        self.clear_button = ttk.Button(view_row, text="전체 지우기", command=self.clear_rectangles, style="Action.TButton")
        self.clear_button.pack(side="left", padx=(8, 0))
        self.grid_button = ttk.Button(view_row, text="칸 나누기", command=self.open_grid_generator_dialog, style="Action.TButton")
        self.grid_button.pack(side="left", padx=(8, 0))
        self.configure_button = ttk.Button(view_row, text="확정", command=self.apply_settings, style="Action.TButton")
        self.configure_button.pack(side="left", padx=(8, 0))

        canvas_shell = ttk.Frame(wrapper, style="Surface.TFrame", padding=(14, 14, 14, 14))
        canvas_shell.grid(row=2, column=0, sticky="nsew", padx=(0, 14))
        canvas_shell.columnconfigure(0, weight=1)
        canvas_shell.rowconfigure(2, weight=1)

        canvas_header = ttk.Frame(canvas_shell, style="Surface.TFrame")
        canvas_header.grid(row=0, column=0, sticky="ew")
        canvas_header.columnconfigure(0, weight=1)
        ttk.Label(canvas_header, textvariable=self.image_summary_var, style="PanelTitle.TLabel", justify="left").grid(row=0, column=0, sticky="w")
        ttk.Label(canvas_header, textvariable=self.selection_summary_var, style="PillMuted.TLabel").grid(row=0, column=1, sticky="e")

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

        image_card = self._create_info_card(sidebar, "현재 사진", self.image_summary_var)
        image_card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        selection_card = self._create_info_card(sidebar, "자르는 영역", self.selection_summary_var)
        selection_card.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        output_card = ttk.Frame(sidebar, style="Card.TFrame", padding=(12, 12))
        output_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        output_card.columnconfigure(0, weight=1)
        ttk.Label(output_card, text="저장 폴더", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(output_card, textvariable=self.output_dir_var, style="CardValue.TLabel", wraplength=250, justify="left").grid(row=1, column=0, sticky="w", pady=(6, 10))
        action_bar = ttk.Frame(output_card, style="Card.TFrame")
        action_bar.grid(row=2, column=0, sticky="ew")
        self.output_dir_button = ttk.Button(action_bar, text="저장 폴더", command=self.choose_output_directory, style="Action.TButton")
        self.output_dir_button.pack(side="left")
        self.set_cwd_button = ttk.Button(action_bar, text="현재 폴더", command=self.set_output_to_cwd, style="Action.TButton")
        self.set_cwd_button.pack(side="left", padx=(8, 0))

        focus_card = ttk.Frame(sidebar, style="Card.TFrame", padding=(12, 12))
        focus_card.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(focus_card, text="바로 하기", style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(focus_card, textvariable=self.workspace_summary_var, style="SidebarValue.TLabel", wraplength=250, justify="left").pack(anchor="w", pady=(6, 0))
        ttk.Label(
            focus_card,
            text="바로 가기: Ctrl+V 붙여넣기, Ctrl+휠 확대/축소, Shift 정사각형, Delete 영역 지우기",
            style="SidebarHint.TLabel",
            wraplength=250,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

        self.split_button = ttk.Button(sidebar, text="잘라서 저장", command=self.split_image, style="Accent.TButton")
        self.split_button.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        self._make_clickable(
            self.open_button,
            self.paste_button,
            self.save_config_button,
            self.load_config_button,
            self.batch_button,
            self.retry_batch_button,
            self.history_button,
            self.ocr_button,
            self.import_model_button,
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
        retry_state = "normal" if self.last_batch_context and self.last_batch_failures else "disabled"
        self.retry_batch_button.configure(state=retry_state)
        self.history_button.configure(state="normal")
        self.ocr_button.configure(state=image_state)
        self.import_model_button.configure(state="normal")
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

    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="Select an image to crop",
            filetypes=SUPPORTED_FILE_TYPES,
        )
        if not path:
            return

        self._load_image_from_path(Path(path))

    def paste_clipboard_image(self, _event: tk.Event | None = None) -> str | None:
        if ImageGrab is None:
            detail = f"\n{IMAGEGRAB_IMPORT_ERROR}" if IMAGEGRAB_IMPORT_ERROR else ""
            messagebox.showerror("Paste Failed", f"Clipboard images are not available in this environment.{detail}")
            return "break"

        try:
            clipboard_content = ImageGrab.grabclipboard()
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("Paste Failed", f"Could not read the clipboard image.\n{exc}")
            return "break"

        if isinstance(clipboard_content, list):
            image_path = self._find_first_supported_image_path(clipboard_content)
            if image_path is None:
                messagebox.showwarning("Paste Failed", "The clipboard does not contain a supported image.")
                return "break"
            self._load_image_from_path(image_path)
            return "break"

        if clipboard_content is None or not isinstance(clipboard_content, Image.Image):
            messagebox.showwarning("Paste Failed", "No image is available in the clipboard.")
            return "break"

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_stem = f"clipboard_{stamp}"
        copied_image = clipboard_content.copy()
        format_name = clipboard_content.format or "PNG"
        self._load_image(
            image=copied_image,
            display_name=f"{save_stem}.png",
            save_stem=save_stem,
            format_name=format_name,
            source_kind="clipboard",
            source_path=None,
        )
        self.status_var.set(f"Clipboard image loaded: {copied_image.width} x {copied_image.height}")
        return "break"

    def _load_image_from_path(self, image_path: Path) -> bool:
        try:
            with Image.open(image_path) as source_image:
                copied_image = source_image.copy()
                format_name = source_image.format
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("Open Failed", f"Could not open the image.\n{exc}")
            return False

        self._load_image(
            image=copied_image,
            display_name=image_path.name,
            save_stem=image_path.stem,
            format_name=format_name,
            source_kind="file",
            source_path=image_path,
        )
        self.status_var.set(f"Loaded image: {image_path.name} ({copied_image.width} x {copied_image.height})")
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
            if candidate.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES and candidate.exists():
                return candidate
        return None

    def choose_output_directory(self) -> None:
        initial_dir = self.output_dir
        if initial_dir is None and self.loaded_image and self.loaded_image.path is not None:
            initial_dir = self.loaded_image.path.parent
        if initial_dir is None:
            initial_dir = Path.cwd()

        selected_dir = filedialog.askdirectory(
            title="Choose an output folder",
            initialdir=str(initial_dir),
            mustexist=True,
        )
        if not selected_dir:
            return

        self._set_output_dir(Path(selected_dir), user_selected=True)
        self.status_var.set(f"Output folder set: {selected_dir}")

    def set_output_to_cwd(self) -> None:
        """Set the output directory to the current working directory."""
        cwd = Path.cwd()
        self._set_output_dir(cwd, user_selected=True)
        self.status_var.set(f"Output folder set to workspace: {cwd}")

    def _set_output_dir(self, path: Path | None, user_selected: bool = False) -> None:
        self.output_dir = path
        self.output_dir_is_user_selected = user_selected
        if self.output_dir is None:
            self.output_dir_var.set("Not selected")
        else:
            self.output_dir_var.set(str(self.output_dir))
        self._update_controls()

    def save_configuration(self) -> None:
        if not self.loaded_image:
            return

        initial_path = self._get_default_config_path()
        target = filedialog.asksaveasfilename(
            title="Save layout",
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
            Path(target).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("Save Failed", f"Could not save the layout file.\n{exc}")
            return

        self.status_var.set(f"Layout saved: {Path(target).name}")

    def load_configuration(self) -> None:
        config_path = filedialog.askopenfilename(title="Load layout", filetypes=CONFIG_FILE_TYPES)
        if not config_path:
            return

        try:
            data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("Load Failed", f"Could not read the layout file.\n{exc}")
            return

        saved_image_path = Path(data.get("image_path", "")) if data.get("image_path") else None
        saved_image_source_kind = str(data.get("image_source_kind") or "file")
        if saved_image_path and saved_image_path.exists():
            current_image_path = self.loaded_image.path.resolve() if self.loaded_image and self.loaded_image.path else None
            if current_image_path != saved_image_path.resolve():
                if not self._load_image_from_path(saved_image_path):
                    return
        elif not self.loaded_image:
            missing_source_message = (
                "The layout expects a clipboard image. Paste the source image again and retry."
                if saved_image_source_kind == "clipboard"
                else "The layout references a source image that could not be found. Open the image first and retry."
            )
            messagebox.showerror(
                "Load Failed",
                missing_source_message,
            )
            return

        assert self.loaded_image is not None
        size_info = data.get("image_size", {})
        saved_width = int(size_info.get("width") or self.loaded_image.width)
        saved_height = int(size_info.get("height") or self.loaded_image.height)
        ratio_x = self.loaded_image.width / saved_width if saved_width else 1.0
        ratio_y = self.loaded_image.height / saved_height if saved_height else 1.0

        rectangles: list[CropRectangle] = []
        for item in data.get("rectangles", []):
            if not isinstance(item, dict):
                continue
            rectangles.append(
                CropRectangle(
                    left=round(float(item.get("left", 0)) * ratio_x),
                    top=round(float(item.get("top", 0)) * ratio_y),
                    right=round(float(item.get("right", 0)) * ratio_x),
                    bottom=round(float(item.get("bottom", 0)) * ratio_y),
                )
            )

        self.rectangles = self._normalize_rectangles_collection(rectangles)
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = bool(data.get("configured")) and bool(self.rectangles)

        saved_zoom = float(data.get("zoom") or 1.0)
        self.zoom = self._clamp_zoom(saved_zoom)
        self._render_image(reset_view=True)

        if saved_width != self.loaded_image.width or saved_height != self.loaded_image.height:
            messagebox.showwarning(
                "Layout Scaled",
                "The source image size differs from the saved layout, so the crop coordinates were scaled to fit.",
            )

        saved_output_dir = Path(data.get("output_dir", "")) if data.get("output_dir") else None
        if saved_output_dir is not None:
            if saved_output_dir.exists() and saved_output_dir.is_dir():
                self._set_output_dir(saved_output_dir, user_selected=True)
            else:
                self._set_output_dir(None)
                messagebox.showwarning(
                    "Output Folder Missing",
                    "The saved output folder no longer exists. Choose a new output folder.",
                )

        self.status_var.set(f"Layout loaded: {Path(config_path).name}")
        self._update_controls()

    def _get_default_config_path(self) -> Path:
        assert self.loaded_image is not None

        if self.loaded_image.path is not None:
            return self.loaded_image.path.parent / f"{self.loaded_image.save_stem}_crop_config.json"

        base_dir = self.output_dir if self.output_dir is not None else Path.cwd()
        return base_dir / f"{self.loaded_image.save_stem}_crop_config.json"

    def open_batch_process_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("여러 장 자르기")
        dialog.geometry("800x600")
        dialog.minsize(640, 480)
        dialog.transient(self.root)
        dialog.grab_set()
        self._style_dialog(dialog)

        # --- Variables ---
        config_source_var = tk.StringVar(value="current")
        json_path_var = tk.StringVar()
        batch_output_dir_var = tk.StringVar()
        create_subfolder_var = tk.BooleanVar(value=True)
        file_list: list[Path] = []

        # --- Main frame ---
        main_frame = ttk.Frame(dialog, padding=15)
        main_frame.pack(fill="both", expand=True)
        main_frame.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)

        # --- File List Frame ---
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

        def update_file_listbox() -> None:
            file_listbox.delete(0, "end")
            for f in file_list:
                file_listbox.insert("end", str(f))

        def add_files() -> None:
            paths = filedialog.askopenfilenames(
                title="처리할 이미지들을 선택하세요",
                filetypes=SUPPORTED_FILE_TYPES,
                parent=dialog,
            )
            if not paths:
                return

            new_paths = {Path(p) for p in paths}
            current_paths = set(file_list)
            file_list.extend(sorted(list(new_paths - current_paths)))
            update_file_listbox()

        def add_folder() -> None:
            dir_path = filedialog.askdirectory(
                title="이미지가 포함된 폴더를 선택하세요",
                mustexist=True,
                parent=dialog,
            )
            if not dir_path:
                return

            folder_path = Path(dir_path)
            new_paths = set()
            for suffix in SUPPORTED_IMAGE_SUFFIXES:
                new_paths.update(folder_path.rglob(f"*{suffix.lower()}"))
                new_paths.update(folder_path.rglob(f"*{suffix.upper()}"))

            current_paths = set(file_list)
            file_list.extend(sorted(list(new_paths - current_paths)))
            update_file_listbox()

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

        # --- Config Frame ---
        config_frame = ttk.LabelFrame(main_frame, text="적용할 분할 규칙", padding=10)
        config_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        config_frame.columnconfigure(1, weight=1)

        def browse_json() -> None:
            path = filedialog.askopenfilename(title="설정 파일 불러오기", filetypes=CONFIG_FILE_TYPES, parent=dialog)
            if path:
                json_path_var.set(path)

        def toggle_json_input(*_: object) -> None:
            is_json_mode = config_source_var.get() == "json"
            state = "normal" if is_json_mode else "disabled"
            json_path_entry.config(state="readonly" if is_json_mode else "disabled")
            json_browse_button.config(state=state)

        current_settings_radio = ttk.Radiobutton(
            config_frame, text="현재 창의 분할 설정 사용", variable=config_source_var, value="current", command=toggle_json_input
        )
        current_settings_radio.grid(row=0, column=0, columnspan=3, sticky="w")

        if not self.is_configured or not self.rectangles:
            current_settings_radio.config(state="disabled")
            config_source_var.set("json")

        json_settings_radio = ttk.Radiobutton(
            config_frame, text="JSON 설정 파일 사용:", variable=config_source_var, value="json", command=toggle_json_input
        )
        json_settings_radio.grid(row=1, column=0, sticky="w", pady=(5, 0))
        json_path_entry = ttk.Entry(config_frame, textvariable=json_path_var, state="disabled")
        json_path_entry.grid(row=1, column=1, sticky="ew", padx=(5, 5), pady=(5, 0))
        json_browse_button = ttk.Button(config_frame, text="파일 찾기", command=browse_json, state="disabled")
        json_browse_button.grid(row=1, column=2, sticky="w", pady=(5, 0))
        toggle_json_input()

        # --- Output Frame ---
        output_frame = ttk.LabelFrame(main_frame, text="결과물 저장 위치", padding=10)
        output_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        output_frame.columnconfigure(0, weight=1)

        def choose_batch_output_dir() -> None:
            path = filedialog.askdirectory(title="결과물을 저장할 폴더를 선택하세요", mustexist=True, parent=dialog)
            if path:
                batch_output_dir_var.set(path)

        ttk.Label(output_frame, textvariable=batch_output_dir_var).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        batch_output_dir_var.set(str(self.output_dir) if self.output_dir else "폴더를 선택하세요...")
        ttk.Button(output_frame, text="폴더 고르기", command=choose_batch_output_dir).grid(row=0, column=1, sticky="e")

        subfolder_checkbox = ttk.Checkbutton(
            output_frame,
            text="각 원본 이미지 이름으로 하위 폴더 생성",
            variable=create_subfolder_var,
        )
        subfolder_checkbox.grid(row=1, column=0, columnspan=2, sticky="w", pady=(5, 0))

        # --- Action Frame ---
        action_frame = ttk.Frame(main_frame)
        action_frame.grid(row=3, column=0, sticky="sew", pady=(10, 0))
        action_frame.columnconfigure(0, weight=1)

        progress_bar = ttk.Progressbar(action_frame, orient="horizontal", mode="determinate")
        progress_bar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        action_buttons_frame = ttk.Frame(action_frame)
        action_buttons_frame.grid(row=1, column=0, columnspan=2, sticky="e")

        def start_batch_processing() -> None:
            if not file_list:
                messagebox.showerror("오류", "처리할 파일이 없습니다. 목록에 파일을 추가하세요.", parent=dialog)
                return

            output_dir_str = batch_output_dir_var.get()
            if not output_dir_str or "폴더를 선택하세요" in output_dir_str:
                messagebox.showerror("오류", "결과물을 저장할 폴더를 선택하세요.", parent=dialog)
                return

            output_dir = Path(output_dir_str)
            if not output_dir.is_dir():
                messagebox.showerror("오류", "선택한 저장 폴더가 유효하지 않습니다.", parent=dialog)
                return

            crop_rects: list[CropRectangle] | None = None
            source_image_size: tuple[int, int] | None = None

            source = config_source_var.get()
            if source == "current":
                if not self.is_configured or not self.rectangles:
                    messagebox.showerror("오류", "현재 창에 유효한 분할 설정이 없습니다.", parent=dialog)
                    return
                crop_rects = self.rectangles

            elif source == "json":
                json_path_str = json_path_var.get()
                if not json_path_str:
                    messagebox.showerror("오류", "사용할 JSON 설정 파일을 선택하세요.", parent=dialog)
                    return

                json_path = Path(json_path_str)
                if not json_path.is_file():
                    messagebox.showerror("오류", "선택한 JSON 파일이 존재하지 않습니다.", parent=dialog)
                    return

                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                    rect_data = data.get("rectangles", [])
                    if not rect_data:
                        raise ValueError("JSON 파일에 사각형 정보가 없습니다.")

                    crop_rects = [
                        CropRectangle(
                            left=int(item.get("left", 0)),
                            top=int(item.get("top", 0)),
                            right=int(item.get("right", 0)),
                            bottom=int(item.get("bottom", 0)),
                        )
                        for item in rect_data
                    ]

                    size_info = data.get("image_size", {})
                    saved_width = int(size_info.get("width", 0))
                    saved_height = int(size_info.get("height", 0))
                    if saved_width <= 0 or saved_height <= 0:
                        raise ValueError("JSON 파일에 유효한 이미지 크기 정보가 없습니다.")
                    source_image_size = (saved_width, saved_height)

                except Exception as exc:
                    messagebox.showerror("JSON 오류", f"JSON 파일을 읽는 중 오류가 발생했습니다.\n{exc}", parent=dialog)
                    return

            if not crop_rects:
                messagebox.showerror("오류", "적용할 분할 규칙을 가져올 수 없습니다.", parent=dialog)
                return

            start_button.config(state="disabled")
            close_button.config(state="disabled")

            thread = threading.Thread(
                target=self._perform_batch_job,
                args=(
                    dialog,
                    progress_bar,
                    file_list,
                    crop_rects,
                    output_dir,
                    source_image_size,
                    create_subfolder_var.get(),
                ),
                daemon=True,
            )
            thread.start()

        start_button = ttk.Button(action_buttons_frame, text="여러 장 저장", command=start_batch_processing)
        start_button.pack(side="left", padx=5)
        close_button = ttk.Button(action_buttons_frame, text="창 닫기", command=dialog.destroy)
        close_button.pack(side="left", padx=5)

        dialog.wait_window()

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
        return max(MIN_ZOOM, min(MAX_ZOOM, value))

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

        if display_width > 0:
            self.canvas.xview_moveto(left / display_width)
        else:
            self.canvas.xview_moveto(0)

        if display_height > 0:
            self.canvas.yview_moveto(top / display_height)
        else:
            self.canvas.yview_moveto(0)

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
        if handle_pos:
            self.canvas.config(cursor=self.HANDLE_CURSORS[handle_pos])
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

        # Check for resize handle press on the selected rectangle
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
                self.status_var.set("Resizing the selected crop region.")
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
            self.status_var.set("Moving the selected crop region.")
        else:
            self.rectangles.append(CropRectangle(x, y, x, y))
            self.selected_rectangle_index = len(self.rectangles) - 1
            self.drag_context = {
                "kind": "create",
                "index": self.selected_rectangle_index,
                "shift_pressed": (event.state & SHIFT_MASK) != 0,
            }
            self.is_configured = False
            self.status_var.set("Drawing a new crop region. Release the mouse to place it.")

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

        if kind == "resize":
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
        if self.selected_rectangle_index is None or not self.drag_context:
            self.drag_context = None
            return

        normalized = self._normalize_rectangle(self.rectangles[self.selected_rectangle_index])
        if normalized is None:
            del self.rectangles[self.selected_rectangle_index]
            self.selected_rectangle_index = None
            self.status_var.set("Very small crop regions are removed automatically.")
        else:
            self.rectangles[self.selected_rectangle_index] = normalized
            self.status_var.set("Crop region updated. Keep editing or confirm the layout.")

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
        if event.state & CONTROL_MASK:
            self.zoom_by(ZOOM_STEP if event.delta > 0 else 1 / ZOOM_STEP, focus_event=event)
            return

        if event.state & SHIFT_MASK:
            self.canvas.xview_scroll(int(-event.delta / 120), "units")
            return

        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def cancel_current_drag(self) -> None:
        if self.drag_context and self.drag_context.get("kind") == "create" and self.selected_rectangle_index is not None:
            del self.rectangles[self.selected_rectangle_index]
            self.selected_rectangle_index = None
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
        self.status_var.set("Selected crop region deleted.")

    def clear_rectangles(self) -> None:
        if not self.loaded_image:
            return

        self.rectangles = []
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = False
        self._refresh_overlays()
        self._update_controls()
        self.status_var.set("All crop regions cleared.")

    def open_grid_generator_dialog(self) -> None:
        if not self.loaded_image:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("칸 나누기")
        dialog.geometry("320x200")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        self._style_dialog(dialog)

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Rows").grid(row=0, column=0, sticky="w", pady=5)
        rows_var = tk.StringVar(value="2")
        rows_entry = ttk.Entry(frame, textvariable=rows_var, width=10)
        rows_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        ttk.Label(frame, text="Columns").grid(row=1, column=0, sticky="w", pady=5)
        cols_var = tk.StringVar(value="2")
        cols_entry = ttk.Entry(frame, textvariable=cols_var, width=10)
        cols_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0))

        ttk.Label(frame, text="Padding (px)").grid(row=2, column=0, sticky="w", pady=5)
        padding_var = tk.StringVar(value="0")
        padding_entry = ttk.Entry(frame, textvariable=padding_var, width=10)
        padding_entry.grid(row=2, column=1, sticky="ew", padx=(10, 0))

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=3, column=0, columnspan=2, pady=(20, 0))

        def on_generate() -> None:
            try:
                rows = int(rows_var.get())
                cols = int(cols_var.get())
                padding = int(padding_var.get())
                if rows <= 0 or cols <= 0 or padding < 0:
                    raise ValueError("Values must be positive.")
            except ValueError:
                messagebox.showerror("Input Error", "Enter valid positive integers for rows, columns, and padding.", parent=dialog)
                return

            self.generate_grid_rectangles(rows, cols, padding)
            dialog.destroy()

        generate_button = ttk.Button(button_frame, text="칸 만들기", command=on_generate)
        generate_button.pack(side="left", padx=5)

        cancel_button = ttk.Button(button_frame, text="닫기", command=dialog.destroy)
        cancel_button.pack(side="left", padx=5)

        dialog.wait_window()

    def generate_grid_rectangles(self, rows: int, cols: int, padding: int) -> None:
        if not self.loaded_image:
            return

        img_width, img_height = self.loaded_image.width, self.loaded_image.height
        total_padding_x, total_padding_y = padding * (cols + 1), padding * (rows + 1)
        if total_padding_x >= img_width or total_padding_y >= img_height:
            messagebox.showerror("Grid Error", "The total padding is larger than the image dimensions.")
            return

        cell_width, cell_height = (img_width - total_padding_x) / cols, (img_height - total_padding_y) / rows
        if cell_width < 1 or cell_height < 1:
            messagebox.showerror("Grid Error", "Cell size would fall below 1px. Reduce rows, columns, or padding.")
            return

        self.rectangles = []
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = False

        self.rectangles = [
            CropRectangle(
                round(padding + c * (cell_width + padding)),
                round(padding + r * (cell_height + padding)),
                round(padding + c * (cell_width + padding) + cell_width),
                round(padding + r * (cell_height + padding) + cell_height),
            )
            for r in range(rows)
            for c in range(cols)
        ]

        self._refresh_overlays()
        self._update_controls()
        self.status_var.set(f"Generated a {rows} x {cols} grid with {len(self.rectangles)} crop regions.")

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
            self.status_var.set(f"Layout confirmed with {len(self.rectangles)} crop regions.")
        else:
            self.status_var.set("No crop regions are available to confirm yet.")

    def split_image(self) -> None:
        if not self.loaded_image or not self.is_configured or not self.rectangles:
            return

        if self.output_dir is None or not self.output_dir.is_dir():
            messagebox.showerror("Export Failed", "Choose an output folder before exporting crops.")
            return

        output_dir = self.output_dir
        stem = self.loaded_image.save_stem
        suffix = self._resolve_output_suffix()
        saved_paths: list[Path] = []

        try:
            for index, rectangle in enumerate(self.rectangles, start=1):
                cropped = self.loaded_image.image.crop(
                    (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)
                )
                target_path = self._build_output_path(output_dir, f"{stem}_rect_{index:02d}", suffix)
                self._save_cropped_image(cropped, target_path)
                saved_paths.append(target_path)
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("Export Failed", f"An error occurred while exporting crops.\n{exc}")
            return

        self._append_history_entry(
            job_type="single",
            source_images=[self.loaded_image.display_name],
            output_dir=output_dir,
            saved_paths=saved_paths,
            rectangles_count=len(self.rectangles),
        )
        self.status_var.set(f"Exported {len(saved_paths)} crops to {output_dir}")
        messagebox.showinfo(
            "Export Complete",
            f"Saved {len(saved_paths)} cropped files.\n\nOutput:\n{output_dir}",
        )

    def _perform_batch_job(
        self,
        dialog: tk.Toplevel,
        progress_bar: ttk.Progressbar,
        file_list: list[Path],
        crop_rects: list[CropRectangle],
        output_dir: Path,
        source_image_size: tuple[int, int] | None,
        create_subfolders: bool,
    ) -> None:
        total_files = len(file_list)
        progress_bar["maximum"] = total_files
        saved_count = 0
        error_count = 0
        errors: list[str] = []
        failed_paths: list[Path] = []
        saved_paths: list[Path] = []

        for i, image_path in enumerate(file_list):
            try:
                with Image.open(image_path) as source_image:
                    current_image = source_image.copy()

                rects_to_apply = crop_rects
                if source_image_size is not None:
                    saved_width, saved_height = source_image_size
                    current_width, current_height = current_image.width, current_image.height
                    ratio_x = current_width / saved_width if saved_width else 1.0
                    ratio_y = current_height / saved_height if saved_height else 1.0

                    scaled_rects = [
                        CropRectangle(
                            left=round(rect.left * ratio_x),
                            top=round(rect.top * ratio_y),
                            right=round(rect.right * ratio_x),
                            bottom=round(rect.bottom * ratio_y),
                        )
                        for rect in crop_rects
                    ]
                    rects_to_apply = self._normalize_rectangles_collection(scaled_rects)

                if not rects_to_apply:
                    raise ValueError("No valid crop regions remain after scaling.")

                stem = image_path.stem
                suffix = self._get_batch_output_suffix(image_path)

                current_output_dir = output_dir
                if create_subfolders:
                    current_output_dir = output_dir / stem
                    current_output_dir.mkdir(parents=True, exist_ok=True)

                for index, rectangle in enumerate(rects_to_apply, start=1):
                    normalized_rect = rectangle.normalized()
                    cropped = current_image.crop(
                        (normalized_rect.left, normalized_rect.top, normalized_rect.right, normalized_rect.bottom)
                    )
                    target_path = self._build_output_path(current_output_dir, f"{stem}_rect_{index:02d}", suffix)
                    self._save_cropped_image(cropped, target_path)
                    saved_count += 1
                    saved_paths.append(target_path)
            except Exception as exc:
                error_count += 1
                failed_paths.append(image_path)
                errors.append(f"{image_path.name}: {exc}")
            finally:
                dialog.after(0, lambda p=i + 1: progress_bar.config(value=p))

        def show_final_message() -> None:
            self.last_batch_context = {
                "crop_rects": [rect for rect in crop_rects],
                "output_dir": output_dir,
                "source_image_size": source_image_size,
                "create_subfolders": create_subfolders,
            }
            self.last_batch_failures = failed_paths
            self._update_controls()

            if saved_paths:
                self._append_history_entry(
                    job_type="batch",
                    source_images=[path.name for path in file_list],
                    output_dir=output_dir,
                    saved_paths=saved_paths,
                    rectangles_count=len(crop_rects),
                )
            message = f"Batch processing finished.\n\nFiles attempted: {total_files}\nCrops saved: {saved_count}"
            if error_count > 0:
                message += f"\nFiles with errors: {error_count}"
                message += "\nUse 'Retry Failed' in the toolbar to rerun only the failed files."
                if errors and len(errors) < 5:
                    message += "\n\nError details:\n" + "\n".join(errors)
            messagebox.showinfo("Batch Complete", message, parent=dialog)
            dialog.destroy()

        dialog.after(0, show_final_message)

    def retry_failed_batch_jobs(self) -> None:
        if not self.last_batch_context or not self.last_batch_failures:
            messagebox.showinfo("Retry Failed", "There are no failed batch items to retry.")
            return

        valid_failures = [path for path in self.last_batch_failures if path.exists() and path.is_file()]
        if not valid_failures:
            messagebox.showwarning("Retry Failed", "The previously failed files can no longer be found.")
            self.last_batch_failures = []
            self._update_controls()
            return

        output_dir_raw = self.last_batch_context.get("output_dir")
        output_dir = output_dir_raw if isinstance(output_dir_raw, Path) else None
        if output_dir is None or not output_dir.exists():
            messagebox.showerror("Retry Failed", "The previous batch output folder could not be found.")
            return

        crop_rects_raw = self.last_batch_context.get("crop_rects", [])
        crop_rects = crop_rects_raw if isinstance(crop_rects_raw, list) else []
        if not crop_rects:
            messagebox.showerror("Retry Failed", "The previous batch crop layout is missing.")
            return

        source_image_size_raw = self.last_batch_context.get("source_image_size")
        source_image_size = source_image_size_raw if isinstance(source_image_size_raw, tuple) else None
        create_subfolders_raw = self.last_batch_context.get("create_subfolders", True)
        create_subfolders = bool(create_subfolders_raw)

        retry_dialog = tk.Toplevel(self.root)
        retry_dialog.title("실패한 사진 다시")
        retry_dialog.geometry("520x160")
        retry_dialog.transient(self.root)
        retry_dialog.grab_set()
        self._style_dialog(retry_dialog)

        frame = ttk.Frame(retry_dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"Retrying {len(valid_failures)} failed source files.").pack(anchor="w", pady=(0, 8))
        progress_bar = ttk.Progressbar(frame, orient="horizontal", mode="determinate")
        progress_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text="Running...").pack(anchor="w")

        thread = threading.Thread(
            target=self._perform_batch_job,
            args=(
                retry_dialog,
                progress_bar,
                valid_failures,
                crop_rects,
                output_dir,
                source_image_size,
                create_subfolders,
            ),
            daemon=True,
        )
        thread.start()

    def _get_batch_output_suffix(self, image_path: Path) -> str:
        suffix = image_path.suffix.lower()
        if suffix in SUPPORTED_IMAGE_SUFFIXES:
            return suffix
        return ".png"

    def _resolve_output_suffix(self) -> str:
        assert self.loaded_image is not None

        if self.loaded_image.path is not None:
            suffix = self.loaded_image.path.suffix.lower()
        else:
            suffix = self._suffix_from_format_name(self.loaded_image.format_name)

        if suffix in SUPPORTED_IMAGE_SUFFIXES:
            return suffix
        return ".png"

    def _suffix_from_format_name(self, format_name: str | None) -> str:
        if not format_name:
            return ".png"

        normalized = format_name.strip().upper()
        format_to_suffix = {
            "PNG": ".png",
            "JPEG": ".jpg",
            "JPG": ".jpg",
            "BMP": ".bmp",
            "GIF": ".gif",
            "WEBP": ".webp",
            "TIFF": ".tiff",
            "TIF": ".tif",
        }
        return format_to_suffix.get(normalized, ".png")

    def _build_output_path(self, output_dir: Path, base_name: str, suffix: str) -> Path:
        target = output_dir / f"{base_name}{suffix}"
        attempt = 1
        while target.exists():
            target = output_dir / f"{base_name}_{attempt}{suffix}"
            attempt += 1
        return target

    def _save_cropped_image(self, image: "Image.Image", target_path: Path) -> None:
        suffix = target_path.suffix.lower()
        if suffix in {".jpg", ".jpeg"} and image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        image.save(target_path)

    def _resolve_cpp_ocr_executable(self) -> Path:
        candidates = [
            Path.cwd() / "bin" / "ocr_trt_runner.exe",
            Path.cwd() / "bin" / "ocr_trt_runner",
            Path.cwd() / "cpp" / "ocr_engine" / "build" / "ocr_trt_runner.exe",
            Path.cwd() / "cpp" / "ocr_engine" / "build" / "ocr_trt_runner",
        ]
        for path in candidates:
            if path.exists() and path.is_file():
                return path
        return candidates[0]

    def _validate_ocr_model_dir(self, model_dir: Path) -> tuple[bool, list[str]]:
        missing = [name for name in REQUIRED_OCR_MODEL_FILES if not (model_dir / name).exists()]
        return len(missing) == 0, missing

    def import_ocr_model_package(self) -> None:
        package_path = filedialog.askopenfilename(
            title="OCR 모델 ZIP 파일 선택",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if not package_path:
            return

        destination = DEFAULT_OCR_MODEL_DIR
        destination.mkdir(parents=True, exist_ok=True)

        temp_extract_dir = Path(tempfile.mkdtemp(prefix="ocr_model_import_"))
        try:
            with zipfile.ZipFile(package_path, "r") as zf:
                zf.extractall(temp_extract_dir)

            candidate_dirs = [temp_extract_dir] + [p for p in temp_extract_dir.iterdir() if p.is_dir()]
            selected_dir: Path | None = None
            for candidate in candidate_dirs:
                is_valid, _missing = self._validate_ocr_model_dir(candidate)
                if is_valid:
                    selected_dir = candidate
                    break

            if selected_dir is None:
                messagebox.showerror(
                    "모델 가져오기 실패",
                    "ZIP 내부에서 detector.engine / recognizer.engine 파일을 찾지 못했습니다.",
                )
                return

            for file_name in REQUIRED_OCR_MODEL_FILES:
                shutil.copy2(selected_dir / file_name, destination / file_name)

            self.status_var.set(f"OCR 모델 가져오기 완료: {destination}")
            messagebox.showinfo("모델 가져오기 완료", f"모델 파일을 적용했습니다.\n{destination}")
        except (OSError, zipfile.BadZipFile) as exc:
            messagebox.showerror("모델 가져오기 실패", f"모델 ZIP 처리 중 오류가 발생했습니다.\n{exc}")
        finally:
            shutil.rmtree(temp_extract_dir, ignore_errors=True)

    def run_cpp_ocr(self) -> None:
        if not self.loaded_image:
            messagebox.showwarning("OCR", "먼저 이미지를 불러오세요.")
            return

        if not self.rectangles:
            messagebox.showwarning("OCR", "OCR 대상 영역이 없습니다. 사각형을 먼저 지정하세요.")
            return

        executable = self._resolve_cpp_ocr_executable()
        if not executable.exists():
            messagebox.showerror(
                "OCR 실행 파일 없음",
                (
                    "C++ TensorRT OCR 실행 파일을 찾지 못했습니다.\n\n"
                    f"기대 경로: {executable}\n"
                    "먼저 cpp/ocr_engine을 빌드해 주세요."
                ),
            )
            return

        if not DEFAULT_OCR_MODEL_DIR.exists():
            messagebox.showerror(
                "OCR 모델 경로 없음",
                (
                    "TensorRT OCR 모델 폴더를 찾지 못했습니다.\n\n"
                    f"기대 경로: {DEFAULT_OCR_MODEL_DIR}\n"
                    "모델/엔진 파일을 준비해 주세요."
                ),
            )
            return
        is_valid_model, missing_files = self._validate_ocr_model_dir(DEFAULT_OCR_MODEL_DIR)
        if not is_valid_model:
            messagebox.showerror(
                "OCR 모델 파일 누락",
                (
                    f"다음 모델 파일이 필요합니다: {', '.join(REQUIRED_OCR_MODEL_FILES)}\n"
                    f"누락 파일: {', '.join(missing_files)}\n\n"
                    "툴바의 '모델 가져오기'를 눌러 ZIP을 가져오세요."
                ),
            )
            return

        with tempfile.TemporaryDirectory(prefix="autocrop_ocr_") as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            input_dir = temp_dir / "inputs"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_json = temp_dir / "ocr_result.json"

            for index, rectangle in enumerate(self.rectangles, start=1):
                normalized = rectangle.normalized()
                cropped = self.loaded_image.image.crop(
                    (normalized.left, normalized.top, normalized.right, normalized.bottom)
                )
                cropped_path = input_dir / f"crop_{index:02d}.png"
                self._save_cropped_image(cropped, cropped_path)

            command = [
                str(executable),
                "--input-dir",
                str(input_dir),
                "--output-json",
                str(output_json),
                "--model-dir",
                str(DEFAULT_OCR_MODEL_DIR),
            ]

            try:
                completed = subprocess.run(command, check=False, capture_output=True, text=True)
            except OSError as exc:
                messagebox.showerror("OCR 실행 실패", f"OCR 엔진 실행 중 오류가 발생했습니다.\n{exc}")
                return

            if completed.returncode != 0:
                stderr = completed.stderr.strip() or "(stderr 없음)"
                messagebox.showerror(
                    "OCR 실패",
                    f"OCR 엔진이 실패했습니다 (exit code: {completed.returncode}).\n\n{stderr}",
                )
                return

            if not output_json.exists():
                messagebox.showerror("OCR 실패", "OCR 결과 파일(ocr_result.json)이 생성되지 않았습니다.")
                return

            try:
                with output_json.open("r", encoding="utf-8") as fp:
                    data = json.load(fp)
            except (OSError, json.JSONDecodeError) as exc:
                messagebox.showerror("OCR 실패", f"OCR 결과를 읽을 수 없습니다.\n{exc}")
                return

            lines: list[str] = []
            structured_ocr_items: list[dict[str, object]] = []
            if isinstance(data, dict):
                items = data.get("results", [])
                if isinstance(items, list):
                    for item in items[:20]:
                        if not isinstance(item, dict):
                            continue
                        file_name = str(item.get("file", "-"))
                        text = str(item.get("text", "")).strip()
                        confidence = item.get("confidence")
                        conf = confidence if confidence is not None else "-"
                        lines.append(f"{file_name} | conf={conf} | {text}")
                        structured_ocr_items.append(
                            {
                                "file": file_name,
                                "text": text,
                                "confidence": confidence,
                            }
                        )

            preview = "\n".join(lines) if lines else "결과를 읽었지만 표시할 OCR 항목이 없습니다."
            self._append_history_entry(
                job_type="ocr",
                source_images=[self.loaded_image.display_name],
                output_dir=DEFAULT_OCR_MODEL_DIR,
                saved_paths=[],
                rectangles_count=len(self.rectangles),
                details={
                    "ocr": {
                        "result_file": str(output_json),
                        "items_count": len(structured_ocr_items),
                        "items_preview": structured_ocr_items,
                    }
                },
            )
            self.status_var.set(f"OCR 완료: {len(lines)}개 항목 미리보기 갱신")
            messagebox.showinfo("OCR 완료", preview)

    def _history_file_path(self) -> Path:
        return Path.cwd() / HISTORY_FILENAME

    def _append_history_entry(
        self,
        job_type: str,
        source_images: list[str],
        output_dir: Path,
        saved_paths: list[Path],
        rectangles_count: int,
        details: dict[str, object] | None = None,
    ) -> None:
        history_path = self._history_file_path()
        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "job_type": job_type,
            "source_images": source_images,
            "output_dir": str(output_dir),
            "saved_paths": [str(path) for path in saved_paths],
            "saved_count": len(saved_paths),
            "rectangles_count": rectangles_count,
        }
        if details is not None:
            entry["details"] = details
        try:
            with history_path.open("a", encoding="utf-8") as fp:
                fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            self.status_var.set("분할 저장은 완료됐지만 이력 기록 파일을 저장하지 못했습니다.")

    def _read_history_entries(self, limit: int = 300) -> list[dict[str, object]]:
        history_path = self._history_file_path()
        if not history_path.exists():
            return []

        entries: list[dict[str, object]] = []
        try:
            with history_path.open("r", encoding="utf-8") as fp:
                for line in fp:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(parsed, dict):
                        entries.append(parsed)
        except OSError:
            return []
        return entries[-limit:][::-1]

    def open_history_viewer(self) -> None:
        entries = self._read_history_entries()
        if not entries:
            messagebox.showinfo("History", "No saved job history is available yet.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("Crop History")
        dialog.geometry("920x560")
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
        ttk.Entry(filter_frame, textvariable=start_date_var, width=14).grid(row=0, column=1, padx=(4, 12))

        ttk.Label(filter_frame, text="종료일(YYYY-MM-DD)").grid(row=0, column=2, sticky="w")
        end_date_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=end_date_var, width=14).grid(row=0, column=3, padx=(4, 12))

        ttk.Label(filter_frame, text="작업유형").grid(row=0, column=4, sticky="w")
        job_type_var = tk.StringVar(value="전체")
        ttk.Combobox(
            filter_frame,
            textvariable=job_type_var,
            values=["전체", "single", "batch", "ocr"],
            width=10,
            state="readonly",
        ).grid(row=0, column=5, padx=(4, 12))

        ttk.Label(filter_frame, text="OCR 텍스트 검색").grid(row=0, column=6, sticky="w")
        ocr_query_var = tk.StringVar()
        ttk.Entry(filter_frame, textvariable=ocr_query_var, width=24).grid(row=0, column=7, sticky="ew", padx=(4, 8))

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
        preset_frame.grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Label(preset_frame, text="빠른 기간").pack(side="left", padx=(0, 6))

        notebook = ttk.Notebook(container)
        notebook.grid(row=2, column=0, sticky="nsew")

        history_tab = ttk.Frame(notebook, padding=8)
        history_tab.columnconfigure(0, weight=1)
        history_tab.rowconfigure(0, weight=1)
        notebook.add(history_tab, text="이력 목록")

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
        notebook.add(ocr_tab, text="OCR 결과")
        ocr_control_frame = ttk.Frame(ocr_tab)
        ocr_control_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ocr_control_frame.columnconfigure(2, weight=1)
        ttk.Label(ocr_control_frame, text="Confidence 임계값").grid(row=0, column=0, sticky="w")
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
        notebook.add(json_tab, text="상세 JSON")
        detail_text = tk.Text(json_tab, wrap="word", state="disabled")
        detail_text.grid(row=0, column=0, sticky="nsew")
        self._style_text_widget(detail_text)

        filtered_entries: list[dict[str, object]] = []

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

        def _format_entry_label(entry: dict[str, object]) -> str:
            ts = str(entry.get("timestamp", "-"))
            job = str(entry.get("job_type", "single"))
            if job == "ocr":
                details = entry.get("details", {})
                details_dict = details if isinstance(details, dict) else {}
                ocr_info = details_dict.get("ocr", {})
                ocr_dict = ocr_info if isinstance(ocr_info, dict) else {}
                items_count = int(ocr_dict.get("items_count", 0) or 0)
                return f"[{ts}] ocr / {items_count}개 텍스트"
            count = int(entry.get("saved_count", 0) or 0)
            return f"[{ts}] {job} / {count}개 저장"

        def _match_ocr_text(entry: dict[str, object], query: str) -> bool:
            if not query:
                return True
            details = entry.get("details")
            if not isinstance(details, dict):
                return False
            ocr_info = details.get("ocr")
            if not isinstance(ocr_info, dict):
                return False
            items = ocr_info.get("items_preview")
            if not isinstance(items, list):
                return False
            lowered = query.lower()
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", ""))
                if lowered in text.lower():
                    return True
            return False

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

            details = entry.get("details")
            ocr_preview_lines: list[str] = []
            if isinstance(details, dict):
                ocr_info = details.get("ocr")
                if isinstance(ocr_info, dict):
                    items = ocr_info.get("items_preview", [])
                    if isinstance(items, list):
                        for idx, item in enumerate(items, start=1):
                            if not isinstance(item, dict):
                                continue
                            text = str(item.get("text", "")).strip()
                            file_name = str(item.get("file", "-"))
                            conf = item.get("confidence")
                            threshold = float(confidence_threshold_var.get())
                            conf_value: float | None = None
                            if isinstance(conf, (int, float)):
                                conf_value = float(conf)
                            elif isinstance(conf, str):
                                try:
                                    conf_value = float(conf)
                                except ValueError:
                                    conf_value = None
                            if conf_value is not None and conf_value < threshold:
                                continue
                            low_tag = "⚠️" if conf_value is not None and conf_value < 0.5 else "✅"
                            ocr_preview_lines.append(
                                f"{idx:02d}. {low_tag} file={file_name} | confidence={conf if conf is not None else '-'} | {text}"
                            )
            ocr_text_value = (
                "\n".join(ocr_preview_lines)
                if ocr_preview_lines
                else "선택된 항목에 OCR 상세 결과가 없거나 임계값 조건에 맞는 결과가 없습니다."
            )
            _render_text(ocr_text, ocr_text_value)

        def refresh_history_list(*_args: object) -> None:
            filtered_entries.clear()
            listbox.delete(0, "end")

            start_date = _parse_date(start_date_var.get(), is_end=False)
            end_date = _parse_date(end_date_var.get(), is_end=True)
            selected_job = job_type_var.get().strip()
            query = ocr_query_var.get().strip()

            for entry in entries:
                ts_raw = str(entry.get("timestamp", ""))
                try:
                    entry_ts = datetime.fromisoformat(ts_raw)
                except ValueError:
                    entry_ts = None

                if start_date and entry_ts and entry_ts < start_date:
                    continue
                if end_date and entry_ts and entry_ts > end_date:
                    continue

                job = str(entry.get("job_type", "single"))
                if selected_job != "전체" and job != selected_job:
                    continue

                if query and not _match_ocr_text(entry, query):
                    continue

                filtered_entries.append(entry)

            selected_sort = sort_var.get().strip()
            if selected_sort == "오래된순":
                filtered_entries.sort(key=lambda item: str(item.get("timestamp", "")))
            elif selected_sort == "저장개수순":
                filtered_entries.sort(key=lambda item: int(item.get("saved_count", 0) or 0), reverse=True)
            else:
                filtered_entries.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)

            for idx, entry in enumerate(filtered_entries):
                listbox.insert(idx, _format_entry_label(entry))

            if filtered_entries:
                listbox.selection_set(0)
                render_selected()
            else:
                _render_text(detail_text, "필터 조건에 맞는 이력이 없습니다.")
                _render_text(ocr_text, "선택된 OCR 이력이 없습니다.")

        ttk.Button(preset_frame, text="오늘", command=lambda: _apply_quick_preset(1)).pack(side="left", padx=(0, 4))
        ttk.Button(preset_frame, text="7일", command=lambda: _apply_quick_preset(7)).pack(side="left", padx=(0, 4))
        ttk.Button(preset_frame, text="30일", command=lambda: _apply_quick_preset(30)).pack(side="left", padx=(0, 4))

        apply_filter_btn = ttk.Button(filter_frame, text="필터 적용", command=refresh_history_list)
        apply_filter_btn.grid(row=0, column=10, padx=(0, 6))
        reset_filter_btn = ttk.Button(
            filter_frame,
            text="초기화",
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

    def _find_handle_at(self, x: int, y: int) -> str | None:
        if self.selected_rectangle_index is None:
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

                # Use float for calculations
                fl, ft, fr, fb = float(l), float(t), float(r), float(b)
                fmx = float(mx)

                if handle == "bottom-right":  # Anchor: top-left
                    fr = fmx
                    fb = ft + (fr - fl) / aspect_ratio
                elif handle == "top-left":  # Anchor: bottom-right
                    fl = fmx
                    ft = fb - (fr - fl) / aspect_ratio
                elif handle == "top-right":  # Anchor: bottom-left
                    fr = fmx
                    ft = fb - (fr - fl) / aspect_ratio
                elif handle == "bottom-left":  # Anchor: top-right
                    fl = fmx
                    fb = ft + (fr - fl) / aspect_ratio

                return CropRectangle(round(fl), round(ft), round(fr), round(fb))

        # Default behavior
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

        normalized = rectangle.normalized()
        left = min(max(normalized.left, 0), self.loaded_image.width)
        top = min(max(normalized.top, 0), self.loaded_image.height)
        right = min(max(normalized.right, 0), self.loaded_image.width)
        bottom = min(max(normalized.bottom, 0), self.loaded_image.height)

        if right - left < MIN_RECT_SIZE or bottom - top < MIN_RECT_SIZE:
            return None

        return CropRectangle(left, top, right, bottom)

    def _normalize_rectangles_collection(self, rectangles: list[CropRectangle]) -> list[CropRectangle]:
        normalized_rectangles: list[CropRectangle] = []
        seen: set[tuple[int, int, int, int]] = set()

        for rectangle in rectangles:
            normalized = self._normalize_rectangle(rectangle)
            if normalized is None:
                continue
            key = (normalized.left, normalized.top, normalized.right, normalized.bottom)
            if key in seen:
                continue
            seen.add(key)
            normalized_rectangles.append(normalized)

        return normalized_rectangles

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

    root = tk.Tk()
    AutoCropApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
