from __future__ import annotations

import json
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

PIL_IMPORT_ERROR: ImportError | None = None

try:
    from PIL import Image, ImageTk
except ImportError as exc:  # pragma: no cover - handled at runtime
    Image = None
    ImageTk = None
    PIL_IMPORT_ERROR = exc


APP_TITLE = "Auto Crop Splitter"
SUPPORTED_FILE_TYPES = [
    ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff"),
    ("All files", "*.*"),
]
CONFIG_FILE_TYPES = [
    ("JSON files", "*.json"),
    ("All files", "*.*"),
]
MIN_RECT_SIZE = 4
MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
ZOOM_STEP = 1.25
CONTROL_MASK = 0x0004
SHIFT_MASK = 0x0001


@dataclass
class LoadedImage:
    path: Path
    image: "Image.Image"
    format_name: str | None

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
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1440x940")
        self.root.minsize(1080, 720)

        self.loaded_image: LoadedImage | None = None
        self.photo_image: "ImageTk.PhotoImage | None" = None
        self.canvas_image_id: int | None = None
        self.zoom = 1.0

        self.rectangles: list[CropRectangle] = []
        self.selected_rectangle_index: int | None = None
        self.drag_context: dict[str, object] | None = None
        self.is_configured = False

        self.zoom_var = tk.StringVar(value="100%")
        self.status_var = tk.StringVar(
            value="이미지를 열고 마우스로 필요한 영역을 드래그해 선택한 뒤 '설정'과 '분할 시작'을 누르세요."
        )
        self.instruction_var = tk.StringVar(
            value=(
                "드래그로 새 사각형을 만들고, 기존 사각형을 드래그하면 이동합니다. "
                "Ctrl+마우스휠 또는 확대/축소 버튼으로 배율을 조정할 수 있습니다."
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

        self.save_config_button = ttk.Button(toolbar, text="설정 저장", command=self.save_configuration)
        self.save_config_button.pack(side="left", padx=(8, 0))

        self.load_config_button = ttk.Button(toolbar, text="설정 불러오기", command=self.load_configuration)
        self.load_config_button.pack(side="left", padx=(8, 0))

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

        self.configure_button = ttk.Button(toolbar, text="설정", command=self.apply_settings)
        self.configure_button.pack(side="left", padx=(16, 0))

        self.split_button = ttk.Button(toolbar, text="분할 시작", command=self.split_image)
        self.split_button.pack(side="left", padx=(8, 0))

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
        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<ButtonPress-3>", self.on_right_press)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.root.bind("<Delete>", lambda _event: self.delete_selected_rectangle())
        self.root.bind("<Escape>", lambda _event: self.cancel_current_drag())

    def _show_placeholder(self) -> None:
        self.canvas.delete("all")
        self.canvas_image_id = None
        self.canvas.create_text(
            520,
            340,
            text="이미지를 열면 여기에 표시됩니다.",
            fill="#d1d5db",
            font=("Malgun Gothic", 20, "bold"),
        )
        self.canvas.configure(scrollregion=(0, 0, 1040, 700))

    def _update_controls(self) -> None:
        has_image = self.loaded_image is not None
        has_rectangles = bool(self.rectangles)

        image_state = "normal" if has_image else "disabled"
        selected_state = "normal" if self.selected_rectangle_index is not None else "disabled"
        split_state = "normal" if has_image and self.is_configured and has_rectangles else "disabled"

        self.save_config_button.configure(state=image_state)
        self.load_config_button.configure(state="normal")
        self.zoom_out_button.configure(state=image_state)
        self.zoom_in_button.configure(state=image_state)
        self.zoom_reset_button.configure(state=image_state)
        self.zoom_fit_button.configure(state=image_state)
        self.delete_button.configure(state=selected_state)
        self.clear_button.configure(state=image_state)
        self.configure_button.configure(state=image_state)
        self.split_button.configure(state=split_state)

    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="분할할 이미지를 선택하세요",
            filetypes=SUPPORTED_FILE_TYPES,
        )
        if not path:
            return

        self._load_image_from_path(Path(path))

    def _load_image_from_path(self, image_path: Path) -> bool:
        try:
            with Image.open(image_path) as source_image:
                copied_image = source_image.copy()
                format_name = source_image.format
        except Exception as exc:  # pragma: no cover - tkinter dialog flow
            messagebox.showerror("열기 실패", f"이미지를 열 수 없습니다.\n{exc}")
            return False

        self.loaded_image = LoadedImage(path=image_path, image=copied_image, format_name=format_name)
        self.rectangles = []
        self.selected_rectangle_index = None
        self.drag_context = None
        self.is_configured = False
        self.zoom = 1.0

        self.root.update_idletasks()
        self.fit_to_view(initial_load=True)
        self.status_var.set(
            f"불러온 이미지: {image_path.name} ({copied_image.width} x {copied_image.height})"
        )
        self._update_controls()
        return True

    def save_configuration(self) -> None:
        if not self.loaded_image:
            return

        initial_path = self.loaded_image.path.parent / f"{self.loaded_image.path.stem}_crop_config.json"
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
            "version": 2,
            "image_path": str(self.loaded_image.path.resolve()),
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
        if saved_image_path and saved_image_path.exists():
            if not self.loaded_image or self.loaded_image.path.resolve() != saved_image_path.resolve():
                if not self._load_image_from_path(saved_image_path):
                    return
        elif not self.loaded_image:
            messagebox.showerror(
                "불러오기 실패",
                "설정 파일의 원본 이미지를 찾을 수 없습니다. 먼저 이미지를 연 뒤 다시 시도하세요.",
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

        self.status_var.set(f"설정 파일을 불러왔습니다: {Path(config_path).name}")
        self._update_controls()

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
            self.drag_context = {"kind": "create", "index": self.selected_rectangle_index}
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

        if kind == "create":
            index = int(self.drag_context["index"])
            current = self.rectangles[index]
            self.rectangles[index] = CropRectangle(current.left, current.top, x, y)
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

        output_dir = self.loaded_image.path.parent
        stem = self.loaded_image.path.stem
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

        self.status_var.set(f"{len(saved_paths)}개 조각을 저장했습니다. 저장 위치: {output_dir}")
        messagebox.showinfo(
            "분할 완료",
            f"{len(saved_paths)}개 파일을 저장했습니다.\n\n저장 위치:\n{output_dir}",
        )

    def _resolve_output_suffix(self) -> str:
        assert self.loaded_image is not None

        suffix = self.loaded_image.path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff"}:
            return suffix
        return ".png"

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

        normalized_rectangles.sort(key=lambda item: (item.top, item.left, item.bottom, item.right))
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
