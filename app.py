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


APP_TITLE = "그리드 크롭 이미지 고도화 프로젝트"
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
        self.output_dir_var = tk.StringVar(value="저장 폴더: 선택되지 않음")
        self.status_var = tk.StringVar(
            value="이미지를 열거나 Ctrl+V로 클립보드 이미지를 붙여넣은 뒤, 영역을 지정하고 저장 폴더를 확인하세요."
        )
        self.instruction_var = tk.StringVar(
            value=(
                "드래그로 새 사각형을 만들고(Shift: 정사각형), '그리드 생성'으로 자동 분할하세요. 기존 사각형을 드래그하면 이동합니다. 핸들을 드래그하여 크기를 조절할 수 있습니다(Shift: 비율 유지). "
                "Ctrl+V로 클립보드 이미지를 붙여넣거나, Ctrl+마우스휠로 배율을 조정할 수 있습니다."
            )
        )

        self._build_ui()
        self._bind_events()
        self._show_placeholder()
        self._update_controls()

    def _build_ui(self) -> None:
        wrapper = ttk.Frame(self.root, padding=12)
        wrapper.pack(fill="both", expand=True)

        toolbar = ttk.Frame(wrapper)
        toolbar.pack(fill="x", pady=(0, 8))

        self.open_button = ttk.Button(toolbar, text="이미지 열기", command=self.open_image)
        self.open_button.pack(side="left")

        self.paste_button = ttk.Button(toolbar, text="클립보드 붙여넣기", command=self.paste_clipboard_image)
        self.paste_button.pack(side="left", padx=(8, 0))

        self.save_config_button = ttk.Button(toolbar, text="설정 저장", command=self.save_configuration)
        self.save_config_button.pack(side="left", padx=(8, 0))

        self.load_config_button = ttk.Button(toolbar, text="설정 불러오기", command=self.load_configuration)
        self.load_config_button.pack(side="left", padx=(8, 0))

        self.batch_button = ttk.Button(toolbar, text="배치 처리", command=self.open_batch_process_dialog)
        self.batch_button.pack(side="left", padx=(16, 0))
        self.retry_batch_button = ttk.Button(toolbar, text="실패 재시도", command=self.retry_failed_batch_jobs)
        self.retry_batch_button.pack(side="left", padx=(8, 0))

        self.history_button = ttk.Button(toolbar, text="이력 뷰어", command=self.open_history_viewer)
        self.history_button.pack(side="left", padx=(8, 0))

        self.ocr_button = ttk.Button(toolbar, text="OCR (C++/TRT)", command=self.run_cpp_ocr)
        self.ocr_button.pack(side="left", padx=(8, 0))
        self.import_model_button = ttk.Button(toolbar, text="모델 가져오기", command=self.import_ocr_model_package)
        self.import_model_button.pack(side="left", padx=(8, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=12)

        self.zoom_out_button = ttk.Button(toolbar, text="축소", command=lambda: self.zoom_by(1 / ZOOM_STEP))
        self.zoom_out_button.pack(side="left")

        self.zoom_in_button = ttk.Button(toolbar, text="확대", command=lambda: self.zoom_by(ZOOM_STEP))
        self.zoom_in_button.pack(side="left", padx=(8, 0))

        self.zoom_reset_button = ttk.Button(toolbar, text="100%", command=self.reset_zoom)
        self.zoom_reset_button.pack(side="left", padx=(8, 0))

        self.zoom_fit_button = ttk.Button(toolbar, text="맞춤", command=self.fit_to_view)
        self.zoom_fit_button.pack(side="left", padx=(8, 0))

        ttk.Label(toolbar, textvariable=self.zoom_var, width=8, anchor="center").pack(side="left", padx=(8, 0))

        ttk.Separator(toolbar, orient="vertical").pack(side="left", fill="y", padx=12)

        self.delete_button = ttk.Button(toolbar, text="선택 삭제", command=self.delete_selected_rectangle)
        self.delete_button.pack(side="left")

        self.clear_button = ttk.Button(toolbar, text="전체 초기화", command=self.clear_rectangles)
        self.clear_button.pack(side="left", padx=(8, 0))

        self.grid_button = ttk.Button(toolbar, text="그리드 생성", command=self.open_grid_generator_dialog)
        self.grid_button.pack(side="left", padx=(8, 0))

        self.configure_button = ttk.Button(toolbar, text="설정", command=self.apply_settings)
        self.configure_button.pack(side="left", padx=(8, 0))

        self.split_button = ttk.Button(toolbar, text="분할 시작", command=self.split_image)
        self.split_button.pack(side="left", padx=(8, 0))

        output_frame = ttk.Frame(wrapper)
        output_frame.pack(fill="x", pady=(0, 8))

        ttk.Label(output_frame, text="저장 폴더").pack(side="left")
        self.output_dir_button = ttk.Button(output_frame, text="폴더 선택", command=self.choose_output_directory)
        self.output_dir_button.pack(side="left", padx=(8, 0))

        self.set_cwd_button = ttk.Button(output_frame, text="현재 폴더로 지정", command=self.set_output_to_cwd)
        self.set_cwd_button.pack(side="left", padx=(8, 0))
        ttk.Label(output_frame, textvariable=self.output_dir_var).pack(side="left", padx=(12, 0))

        instruction_label = ttk.Label(wrapper, textvariable=self.instruction_var, wraplength=1320)
        instruction_label.pack(fill="x", pady=(0, 10))

        canvas_frame = ttk.Frame(wrapper)
        canvas_frame.pack(fill="both", expand=True)
        canvas_frame.columnconfigure(0, weight=1)
        canvas_frame.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, background="#111827", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        y_scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        y_scrollbar.grid(row=0, column=1, sticky="ns")

        x_scrollbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        x_scrollbar.grid(row=1, column=0, sticky="ew")

        self.canvas.configure(xscrollcommand=x_scrollbar.set, yscrollcommand=y_scrollbar.set)

        status_bar = ttk.Label(
            wrapper,
            textvariable=self.status_var,
            anchor="w",
            relief="sunken",
            padding=(8, 6),
        )
        status_bar.pack(fill="x", pady=(10, 0))

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
        self.canvas.create_text(
            520,
            340,
            text="이미지를 열거나 Ctrl+V로 붙여넣으면 여기에 표시됩니다.",
            fill="#d1d5db",
            font=("Malgun Gothic", 20, "bold"),
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

    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="분할할 이미지를 선택하세요",
            filetypes=SUPPORTED_FILE_TYPES,
        )
        if not path:
            return

        self._load_image_from_path(Path(path))

    def paste_clipboard_image(self, _event: tk.Event | None = None) -> str | None:
        if ImageGrab is None:
            detail = f"\n{IMAGEGRAB_IMPORT_ERROR}" if IMAGEGRAB_IMPORT_ERROR else ""
            messagebox.showerror("붙여넣기 실패", f"현재 환경에서는 클립보드 이미지를 읽을 수 없습니다.{detail}")
            return "break"

        try:
            clipboard_content = ImageGrab.grabclipboard()
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("붙여넣기 실패", f"클립보드 이미지를 가져올 수 없습니다.\n{exc}")
            return "break"

        if isinstance(clipboard_content, list):
            image_path = self._find_first_supported_image_path(clipboard_content)
            if image_path is None:
                messagebox.showwarning("붙여넣기 실패", "클립보드에 이미지 데이터가 없거나 지원하지 않는 형식입니다.")
                return "break"
            self._load_image_from_path(image_path)
            return "break"

        if clipboard_content is None or not isinstance(clipboard_content, Image.Image):
            messagebox.showwarning("붙여넣기 실패", "클립보드에 이미지가 없습니다. 먼저 화면 캡처나 이미지 복사를 해주세요.")
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
        self.status_var.set(f"클립보드 이미지를 불러왔습니다: {copied_image.width} x {copied_image.height}")
        return "break"

    def _load_image_from_path(self, image_path: Path) -> bool:
        try:
            with Image.open(image_path) as source_image:
                copied_image = source_image.copy()
                format_name = source_image.format
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("열기 실패", f"이미지를 열 수 없습니다.\n{exc}")
            return False

        self._load_image(
            image=copied_image,
            display_name=image_path.name,
            save_stem=image_path.stem,
            format_name=format_name,
            source_kind="file",
            source_path=image_path,
        )
        self.status_var.set(
            f"불러온 이미지: {image_path.name} ({copied_image.width} x {copied_image.height})"
        )
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
            title="저장 폴더를 선택하세요",
            initialdir=str(initial_dir),
            mustexist=True,
        )
        if not selected_dir:
            return

        self._set_output_dir(Path(selected_dir), user_selected=True)
        self.status_var.set(f"저장 폴더를 설정했습니다: {selected_dir}")

    def set_output_to_cwd(self) -> None:
        """Set the output directory to the current working directory."""
        cwd = Path.cwd()
        self._set_output_dir(cwd, user_selected=True)
        self.status_var.set(f"저장 폴더를 현재 작업 폴더로 설정했습니다: {cwd}")

    def _set_output_dir(self, path: Path | None, user_selected: bool = False) -> None:
        self.output_dir = path
        self.output_dir_is_user_selected = user_selected
        if self.output_dir is None:
            self.output_dir_var.set("저장 폴더: 선택되지 않음")
        else:
            self.output_dir_var.set(f"저장 폴더: {self.output_dir}")
        self._update_controls()

    def save_configuration(self) -> None:
        if not self.loaded_image:
            return

        initial_path = self._get_default_config_path()
        target = filedialog.asksaveasfilename(
            title="설정 저장",
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
            messagebox.showerror("저장 실패", f"설정 파일을 저장할 수 없습니다.\n{exc}")
            return

        self.status_var.set(f"설정 파일을 저장했습니다: {Path(target).name}")

    def load_configuration(self) -> None:
        config_path = filedialog.askopenfilename(title="설정 불러오기", filetypes=CONFIG_FILE_TYPES)
        if not config_path:
            return

        try:
            data = json.loads(Path(config_path).read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("불러오기 실패", f"설정 파일을 읽을 수 없습니다.\n{exc}")
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
                "설정 파일의 원본 이미지를 찾을 수 없습니다. 먼저 클립보드 이미지를 다시 붙여넣은 뒤 시도하세요."
                if saved_image_source_kind == "clipboard"
                else "설정 파일의 원본 이미지를 찾을 수 없습니다. 먼저 이미지를 연 뒤 다시 시도하세요."
            )
            messagebox.showerror(
                "불러오기 실패",
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
                "크기 보정",
                "설정 파일의 이미지 크기와 현재 이미지 크기가 달라 비율에 맞춰 좌표를 보정했습니다.",
            )

        saved_output_dir = Path(data.get("output_dir", "")) if data.get("output_dir") else None
        if saved_output_dir is not None:
            if saved_output_dir.exists() and saved_output_dir.is_dir():
                self._set_output_dir(saved_output_dir, user_selected=True)
            else:
                self._set_output_dir(None)
                messagebox.showwarning(
                    "저장 폴더 확인 필요",
                    "설정 파일에 저장된 폴더가 존재하지 않습니다. 저장 폴더를 다시 선택하세요.",
                )

        self.status_var.set(f"설정 파일을 불러왔습니다: {Path(config_path).name}")
        self._update_controls()

    def _get_default_config_path(self) -> Path:
        assert self.loaded_image is not None

        if self.loaded_image.path is not None:
            return self.loaded_image.path.parent / f"{self.loaded_image.save_stem}_crop_config.json"

        base_dir = self.output_dir if self.output_dir is not None else Path.cwd()
        return base_dir / f"{self.loaded_image.save_stem}_crop_config.json"

    def open_batch_process_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("다중 파일 배치 처리")
        dialog.geometry("800x600")
        dialog.minsize(640, 480)
        dialog.transient(self.root)
        dialog.grab_set()

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

        ttk.Button(file_buttons_frame, text="파일 추가", command=add_files).pack(fill="x", pady=2)
        ttk.Button(file_buttons_frame, text="폴더 추가", command=add_folder).pack(fill="x", pady=2)
        ttk.Button(file_buttons_frame, text="선택 삭제", command=remove_selected).pack(fill="x", pady=(10, 2))
        ttk.Button(file_buttons_frame, text="전체 삭제", command=clear_all).pack(fill="x", pady=2)

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
        json_browse_button = ttk.Button(config_frame, text="찾아보기...", command=browse_json, state="disabled")
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
        ttk.Button(output_frame, text="폴더 선택", command=choose_batch_output_dir).grid(row=0, column=1, sticky="e")

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

        start_button = ttk.Button(action_buttons_frame, text="배치 작업 시작", command=start_batch_processing)
        start_button.pack(side="left", padx=5)
        close_button = ttk.Button(action_buttons_frame, text="닫기", command=dialog.destroy)
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
                self.status_var.set("사각형 크기를 조절하는 중입니다.")
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
            self.status_var.set("선택한 사각형을 이동하는 중입니다.")
        else:
            self.rectangles.append(CropRectangle(x, y, x, y))
            self.selected_rectangle_index = len(self.rectangles) - 1
            self.drag_context = {
                "kind": "create",
                "index": self.selected_rectangle_index,
                "shift_pressed": (event.state & SHIFT_MASK) != 0,
            }
            self.is_configured = False
            self.status_var.set("새 사각형을 만드는 중입니다. 드래그를 놓으면 영역이 확정됩니다.")

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
            self.status_var.set("너무 작은 사각형은 자동으로 제거했습니다.")
        else:
            self.rectangles[self.selected_rectangle_index] = normalized
            self.status_var.set("사각형을 조정했습니다. 계속 수정하거나 '설정'을 누르세요.")

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
        self.status_var.set("선택한 사각형을 삭제했습니다.")

    def clear_rectangles(self) -> None:
        if not self.loaded_image:
            return

        self.rectangles = []
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = False
        self._refresh_overlays()
        self._update_controls()
        self.status_var.set("모든 사각형을 초기화했습니다.")

    def open_grid_generator_dialog(self) -> None:
        if not self.loaded_image:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("그리드 생성")
        dialog.geometry("320x200")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=15)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="행 (Rows):").grid(row=0, column=0, sticky="w", pady=5)
        rows_var = tk.StringVar(value="2")
        rows_entry = ttk.Entry(frame, textvariable=rows_var, width=10)
        rows_entry.grid(row=0, column=1, sticky="ew", padx=(10, 0))

        ttk.Label(frame, text="열 (Columns):").grid(row=1, column=0, sticky="w", pady=5)
        cols_var = tk.StringVar(value="2")
        cols_entry = ttk.Entry(frame, textvariable=cols_var, width=10)
        cols_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0))

        ttk.Label(frame, text="간격 (Padding, px):").grid(row=2, column=0, sticky="w", pady=5)
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
                messagebox.showerror("입력 오류", "행, 열, 간격에 유효한 양의 정수를 입력하세요.", parent=dialog)
                return

            self.generate_grid_rectangles(rows, cols, padding)
            dialog.destroy()

        generate_button = ttk.Button(button_frame, text="생성", command=on_generate)
        generate_button.pack(side="left", padx=5)

        cancel_button = ttk.Button(button_frame, text="취소", command=dialog.destroy)
        cancel_button.pack(side="left", padx=5)

        dialog.wait_window()

    def generate_grid_rectangles(self, rows: int, cols: int, padding: int) -> None:
        if not self.loaded_image:
            return

        img_width, img_height = self.loaded_image.width, self.loaded_image.height
        total_padding_x, total_padding_y = padding * (cols + 1), padding * (rows + 1)
        if total_padding_x >= img_width or total_padding_y >= img_height:
            messagebox.showerror("오류", "간격의 총합이 이미지 크기보다 큽니다.")
            return

        cell_width, cell_height = (img_width - total_padding_x) / cols, (img_height - total_padding_y) / rows
        if cell_width < 1 or cell_height < 1:
            messagebox.showerror("오류", "셀 크기가 1px 미만이 될 수 없습니다. 행/열 또는 간격을 줄여주세요.")
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
        self.status_var.set(f"{rows}x{cols} 그리드를 생성했습니다. 총 {len(self.rectangles)}개 사각형.")

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
            self.status_var.set(f"설정 완료: 저장할 사각형 {len(self.rectangles)}개를 확정했습니다.")
        else:
            self.status_var.set("설정할 사각형이 없습니다. 드래그로 영역을 먼저 추가하세요.")

    def split_image(self) -> None:
        if not self.loaded_image or not self.is_configured or not self.rectangles:
            return

        if self.output_dir is None or not self.output_dir.is_dir():
            messagebox.showerror("저장 실패", "분할 이미지를 저장할 폴더를 먼저 선택하세요.")
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
            messagebox.showerror("저장 실패", f"분할 저장 중 오류가 발생했습니다.\n{exc}")
            return

        self._append_history_entry(
            job_type="single",
            source_images=[self.loaded_image.display_name],
            output_dir=output_dir,
            saved_paths=saved_paths,
            rectangles_count=len(self.rectangles),
        )
        self.status_var.set(f"{len(saved_paths)}개 조각을 저장했습니다. 저장 위치: {output_dir}")
        messagebox.showinfo(
            "분할 완료",
            f"{len(saved_paths)}개 파일을 저장했습니다.\n\n저장 위치:\n{output_dir}",
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
                    raise ValueError("크기 보정 후 유효한 사각형이 없습니다.")

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
            message = f"배치 처리가 완료되었습니다.\n\n총 {total_files}개 파일 처리 시도\n성공적으로 저장된 조각: {saved_count}개"
            if error_count > 0:
                message += f"\n오류 발생: {error_count}개 파일"
                message += "\n(툴바의 '실패 재시도' 버튼으로 실패 파일만 다시 실행할 수 있습니다.)"
                if errors and len(errors) < 5:
                    message += "\n\n오류 상세:\n" + "\n".join(errors)
            messagebox.showinfo("완료", message, parent=dialog)
            dialog.destroy()

        dialog.after(0, show_final_message)

    def retry_failed_batch_jobs(self) -> None:
        if not self.last_batch_context or not self.last_batch_failures:
            messagebox.showinfo("실패 재시도", "재시도할 배치 실패 이력이 없습니다.")
            return

        valid_failures = [path for path in self.last_batch_failures if path.exists() and path.is_file()]
        if not valid_failures:
            messagebox.showwarning("실패 재시도", "이전 실패 파일을 찾을 수 없습니다.")
            self.last_batch_failures = []
            self._update_controls()
            return

        output_dir_raw = self.last_batch_context.get("output_dir")
        output_dir = output_dir_raw if isinstance(output_dir_raw, Path) else None
        if output_dir is None or not output_dir.exists():
            messagebox.showerror("실패 재시도", "이전 배치의 출력 폴더를 찾을 수 없습니다.")
            return

        crop_rects_raw = self.last_batch_context.get("crop_rects", [])
        crop_rects = crop_rects_raw if isinstance(crop_rects_raw, list) else []
        if not crop_rects:
            messagebox.showerror("실패 재시도", "이전 배치의 분할 규칙이 없어 재시도를 진행할 수 없습니다.")
            return

        source_image_size_raw = self.last_batch_context.get("source_image_size")
        source_image_size = source_image_size_raw if isinstance(source_image_size_raw, tuple) else None
        create_subfolders_raw = self.last_batch_context.get("create_subfolders", True)
        create_subfolders = bool(create_subfolders_raw)

        retry_dialog = tk.Toplevel(self.root)
        retry_dialog.title("배치 실패 재시도")
        retry_dialog.geometry("520x160")
        retry_dialog.transient(self.root)
        retry_dialog.grab_set()

        frame = ttk.Frame(retry_dialog, padding=12)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=f"실패 파일 {len(valid_failures)}개를 재시도합니다.").pack(anchor="w", pady=(0, 8))
        progress_bar = ttk.Progressbar(frame, orient="horizontal", mode="determinate")
        progress_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text="재시도 중...").pack(anchor="w")

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
            messagebox.showinfo("이력 뷰어", "아직 저장 이력이 없습니다.")
            return

        dialog = tk.Toplevel(self.root)
        dialog.title("크롭 이력 뷰어")
        dialog.geometry("920x560")
        dialog.transient(self.root)

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

        json_tab = ttk.Frame(notebook, padding=8)
        json_tab.columnconfigure(0, weight=1)
        json_tab.rowconfigure(0, weight=1)
        notebook.add(json_tab, text="상세 JSON")
        detail_text = tk.Text(json_tab, wrap="word", state="disabled")
        detail_text.grid(row=0, column=0, sticky="nsew")

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
            outline = "#ef4444" if selected else "#f59e0b"
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
                outline=outline,
                width=width,
                dash=dash,
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
        fill = "#ef4444"
        outline = "white"
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
