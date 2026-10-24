"""Reference-to-pixel workspace, shared with the MCP reference endpoints."""
from __future__ import annotations

import tkinter as tk
from tkinter import filedialog

from PIL import Image, ImageTk

from .model import PixelError
from .reference import decoded_asset, make_draft
from .reference_ui_images import checker
from .messages import user_error
from .ui import BG, PANEL, FIELD, FG, MUTED, ACCENT, GREEN, SMALL, FONT, place_dialog


class ReferenceDialog:
    def __init__(self, editor):
        self.editor = editor
        self.dialog = d = tk.Toplevel(editor.root)
        d.title("图片 → 像素底稿 · 原图 / 底稿 / 当前工程")
        d.configure(bg=BG)
        d.transient(editor.root)
        place_dialog(d, editor.root, 1180, 780)
        d.minsize(960, 650)
        self.job = self.poll_job = None
        self.quiet, self.pending, self.crop_drag = False, False, None
        self.photos = {}
        self.style_window = None
        self.variables = {key: tk.StringVar() for key in ("width", "height", "colors", "brightness", "contrast", "saturation", "alpha_threshold", "style", "fit", "brief")}
        self.crop_vars = [tk.StringVar() for _ in range(4)]
        header = tk.Frame(d, bg=PANEL, padx=20, pady=14)
        header.pack(fill="x")
        editor.label(header, "图片 → 像素底稿", font=("Microsoft YaHei UI", 16, "bold")).pack(side="left")
        editor.button(header, "导入普通图片", lambda: self.load("subject"), True).pack(side="right", padx=5)
        self.cutout_button = editor.button(header, "去背景", self.cutout)
        self.cutout_button.pack(side="right", padx=5)
        footer = tk.Frame(d, bg=PANEL, padx=18, pady=12)
        footer.pack(side="bottom", fill="x")
        self.create_button = editor.button(footer, "生成像素底稿", self.begin, True)
        self.create_button.pack(side="right")
        editor.button(footer, "复制 AI 指令", self.copy_prompt).pack(side="right", padx=8)
        self.status = editor.label(footer, "", MUTED, SMALL, justify="left", wraplength=390)
        self.status.pack(side="left")
        body = tk.Frame(d, bg=BG, padx=14, pady=12)
        body.pack(fill="both", expand=True)
        outer = tk.Frame(body, bg=PANEL, width=265)
        outer.pack(side="left", fill="y", padx=(0, 12))
        outer.pack_propagate(False)
        controls = editor._scroll_panel(outer)
        editor._section(controls, "像素化设置")
        editor.button(controls, "使用工程内参考", lambda: self.send("/reference/setup", self.payload(action="use_project")), font=SMALL, pady=4).pack(fill="x", pady=3)
        editor.label(controls, "按原图细节设置尺寸与色数，\n在右侧预览后再生成。", MUTED, SMALL,
                     justify="left", wraplength=220).pack(anchor="w", pady=5)
        row = tk.Frame(controls, bg=PANEL)
        row.pack(fill="x", pady=8)
        for key, text in (("width", "宽"), ("height", "高"), ("colors", "色数")):
            editor.label(row, text, MUTED, SMALL).pack(side="left", padx=(0, 3))
            editor._entry(row, self.variables[key], 3).pack(side="left", padx=(0, 6), ipady=4)
        # Legacy style metadata remains loadable/savable for old projects. It
        # never changes make_draft pixels, so it is not a conversion control.
        editor._option(controls, self.variables["fit"], ["完整放入 · 留透明边", "填满画布 · 居中裁切"]).pack(fill="x", pady=4)
        editor._section(controls, "裁切原图", "也可在原图上拖选")
        row = tk.Frame(controls, bg=PANEL)
        row.pack(fill="x")
        for text, variable in zip(("X", "Y", "宽", "高"), self.crop_vars):
            cell = tk.Frame(row, bg=PANEL)
            cell.pack(side="left", padx=(0, 4))
            editor.label(cell, text, MUTED, SMALL).pack(anchor="w")
            editor._entry(cell, variable, 4).pack(ipady=3)
        editor.button(controls, "使用完整原图", self.reset_crop, font=SMALL, pady=4).pack(fill="x", pady=7)
        editor._section(controls, "自动底稿调整")
        for key, title in [("brightness", "亮度"), ("contrast", "对比度"), ("saturation", "饱和度")]:
            editor.label(controls, title, MUTED, SMALL).pack(anchor="w", pady=(6, 0))
            tk.Scale(controls, from_=0.1, to=3, resolution=0.05, orient="horizontal", variable=self.variables[key],
                     bg=PANEL, fg=MUTED, troughcolor=FIELD, activebackground=ACCENT, highlightthickness=0,
                     bd=0, length=200, sliderlength=18, font=SMALL).pack(fill="x")
        row = tk.Frame(controls, bg=PANEL)
        row.pack(fill="x", pady=9)
        editor.label(row, "透明阈值", MUTED, SMALL).pack(side="left")
        editor._entry(row, self.variables["alpha_threshold"], 5).pack(side="right", ipady=3)
        editor.label(controls, "默认仅采样、限色生成底稿。\n保留原图比例、轮廓和五官。\n需要透明背景时，先点击顶部“去背景”。", MUTED, SMALL,
                     justify="left", wraplength=220).pack(anchor="w", pady=8)
        self.right = tk.Frame(body, bg=BG)
        self.right.pack(fill="both", expand=True)
        info = tk.Frame(self.right, bg=BG)
        info.pack(fill="x", pady=(0, 9))
        self.info = editor.label(info, "", MUTED, SMALL)
        self.info.pack(side="left")
        editor.button(info, "刷新", self.refresh, font=SMALL, pady=3).pack(side="right")
        comparisons = tk.Frame(self.right, bg=BG)
        comparisons.pack(fill="both", expand=True)
        comparisons.rowconfigure(0, weight=1)
        self.canvases, self.titles = {}, {}
        for index, (key, title) in enumerate([("subject", "① 普通原图 · 拖动裁切"), ("draft", "② 自动像素底稿"), ("art", "③ 当前工程")]):
            comparisons.columnconfigure(index, weight=1, uniform="tile")
            tile = tk.Frame(comparisons, bg=PANEL, padx=6, pady=8)
            tile.grid(row=0, column=index, sticky="nsew", padx=(0, 7 if index < 2 else 0))
            self.titles[key] = editor.label(tile, title, FG, SMALL)
            self.titles[key].pack(anchor="w", pady=(0, 8))
            canvas = tk.Canvas(tile, bg="#0c1018", highlightthickness=0, cursor="crosshair" if key == "subject" else "arrow")
            canvas.pack(fill="both", expand=True)
            canvas.bind("<Configure>", lambda e: self.draw_images())
            self.canvases[key] = canvas
        source = self.canvases["subject"]
        source.bind("<Button-1>", self.crop_start)
        source.bind("<B1-Motion>", self.crop_move)
        source.bind("<ButtonRelease-1>", self.crop_end)
        style_row = tk.Frame(self.right, bg=PANEL, padx=12, pady=8)
        style_row.pack(fill="x", pady=9)
        style_row.columnconfigure(0, weight=1)
        self.style_label = editor.label(style_row, "", MUTED, SMALL, wraplength=320, justify="left", anchor="w")
        self.style_label.grid(row=0, column=0, sticky="w")
        style_actions = tk.Frame(style_row, bg=PANEL)
        style_actions.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.style_import_button = editor.button(style_actions, "导入风格图", lambda: self.load("style"), font=SMALL, pady=3)
        self.style_import_button.pack(side="left", padx=3)
        self.style_view_button = editor.button(style_actions, "查看", self.show_style, font=SMALL, pady=3)
        self.style_view_button.pack(side="left", padx=3)
        self.style_clear_button = editor.button(style_actions, "清除", self.clear_style, font=SMALL, pady=3)
        self.style_clear_button.pack(side="left", padx=3)
        editor.label(self.right, "风格图由你自行提供，可不选。默认生成底稿时不套用画风；更换普通原图会清空上次风格。",
                     MUTED, SMALL, wraplength=520, justify="left").pack(anchor="w", pady=(0, 3))
        editor.label(self.right, "后续修改要求（可选，发送给 AI 时说明）", MUTED, SMALL).pack(anchor="w", pady=(3, 6))
        entry = editor._entry(self.right, self.variables["brief"])
        entry.pack(fill="x", ipady=7)
        editor.label(self.right, "先像素化保留原图，再按需要拆层、修改或制作动画；生成后也可手动编辑、保存和导出。",
                     MUTED, SMALL, wraplength=770, justify="left").pack(anchor="w", pady=10)
        for var in [*self.variables.values(), *self.crop_vars]:
            var.trace_add("write", self.schedule)
        d.bind("<Destroy>", self.cleanup, add="+")
        self.refresh()
        self.poll_job = d.after(900, self.poll)

    def tokens(self):
        service = self.editor.service
        return service.doc.id, service.doc.revision, service.references.revision

    def payload(self, **fields):
        return {"expected_document_id": self.observed[0], "expected_revision": self.observed[1],
                "expected_reference_revision": self.observed[2], "include_images": False, "source": "手动", **fields}

    def refresh(self):
        if self.job:
            self.dialog.after_cancel(self.job)
            self.job = None
        context = self.editor.service.references.context
        self.quiet = True
        settings = context["settings"]
        for key, var in self.variables.items():
            value = settings[key]
            if key == "style":
                value = {"chibi": "小比例角色", "scene": "像素场景", "item": "图标与道具"}[value]
            if key == "fit":
                value = "完整放入 · 留透明边" if value == "contain" else "填满画布 · 居中裁切"
            var.set(value)
        for var, value in zip(self.crop_vars, settings["crop"] or [""]*4):
            var.set(value)
        self.quiet, self.pending = False, False
        self.observed = self.tokens()
        asset = context["subject"]
        self.info.config(text=f"原图 {asset['original_size'][0]}×{asset['original_size'][1]} → 存储参考 {asset['size'][0]}×{asset['size'][1]}" if asset else "先导入普通图片，再调整目标尺寸和风格。")
        summary = self.editor.service.references.summary(self.editor.doc)
        style = context["style"]
        source = "工程内的导入图片" if summary["style_reference_source"] == "project_embedded" else "工作区导入的图片"
        self.style_label.config(text=(f"风格参考（可选）· {source}\n{style['name']}" if style else "风格参考（可选）\n未设置 · 应用不自带风格图"))
        self.style_import_button.config(text="替换风格图" if style else "导入风格图")
        for button in (self.style_view_button, self.style_clear_button):
            button.config(state="normal" if style else "disabled")
        if self.style_window is not None:
            if not self.style_window.winfo_exists() or not style or self.style_window.asset_id != style["id"]:
                if self.style_window.winfo_exists():
                    self.style_window.destroy()
                self.style_window = None
        self.create_button.config(state="normal" if asset else "disabled")
        self.cutout_button.config(state="normal" if asset else "disabled")
        self.status.config(text="参数已同步。点击生成像素底稿，保留原图设计。" if asset else "PNG / JPEG / WebP / BMP / GIF\n图片与像素工程保存在本地。", fg=MUTED)
        self.draw_images()

    def schedule(self, *_):
        if self.quiet:
            return
        self.pending = True
        if self.job:
            self.dialog.after_cancel(self.job)
        self.job = self.dialog.after(300, self.flush)

    def settings(self):
        settings = {key: var.get() for key, var in self.variables.items()}
        for key in ("width", "height", "colors", "alpha_threshold"):
            settings[key] = int(settings[key])
        for key in ("brightness", "contrast", "saturation"):
            settings[key] = float(settings[key])
        settings["style"] = {"小比例角色": "chibi", "像素场景": "scene", "图标与道具": "item"}[settings["style"]]
        settings["fit"] = "contain" if settings["fit"] == "完整放入 · 留透明边" else "cover"
        values = [var.get().strip() for var in self.crop_vars]
        settings["crop"] = None if not any(values) else [int(v) for v in values]
        return settings

    def send(self, path, payload):
        try:
            result = self.editor.dispatch("POST", path, {}, payload)[0]
            self.refresh()
            return result
        except (OSError, ValueError, KeyError) as exc:
            self.status.config(text=user_error(exc), fg="#f19493")
            return None

    def flush(self):
        if self.job:
            self.dialog.after_cancel(self.job)
            self.job = None
        if not self.pending:
            return True
        try:
            result = self.send("/reference/setup", self.payload(action="configure", settings=self.settings()))
            return result is not None
        except (ValueError, tk.TclError, KeyError):
            self.status.config(text="请检查宽高、色数、裁切范围和明暗参数。", fg="#f19493")
            return False

    def load(self, role):
        if not self.flush():
            return
        path = filedialog.askopenfilename(parent=self.dialog, title="导入普通原图" if role == "subject" else "导入像素风格参考", filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp *.gif")])
        if path:
            self.send("/reference/setup", self.payload(action="load", role=role, path=path))

    def cutout(self):
        if not self.flush() or not self.editor.service.references.context["subject"]:
            return None
        from .cutout_ui import CutoutDialog
        existing = getattr(self, "cutout_window", None)
        if existing and existing.dialog.winfo_exists():
            existing.dialog.lift()
            return existing
        self.cutout_window = CutoutDialog(self.editor, self.dialog)
        return self.cutout_window

    def clear_style(self):
        if not self.flush():
            return False
        result = self.send("/reference/setup", self.payload(action="clear", role="style"))
        if result:
            self.status.config(text="已清除风格参考。原图和画布像素保持不变；可随时导入其他风格图。", fg=GREEN)
        return result is not None

    def begin(self):
        if not self.flush() or not self.editor.can_replace():
            return False
        asset = self.editor.service.references.context["subject"]
        if not asset:
            return False
        # can_replace only leaves a dirty document when the human chose not to save.
        result = self.send("/redraw/begin", self.payload(name=asset["name"].rsplit(".", 1)[0]+" · 自动像素底稿",
                           mode="draft", discard_changes=bool(self.editor.dirty)))
        if result:
            self.status.config(text="自动像素底稿已生成，可直接编辑、保存和导出。", fg=GREEN)
        return result is not None

    def copy_prompt(self):
        if not self.flush():
            return
        s = self.editor.service.references.context["settings"]
        text = (f"请使用 Pixel Loom 的 MCP，将我导入的图片转换为自动像素底稿。先调用 pixel_onboard 和 pixel_reference 查看原图与参数。"
                f"目标 {s['width']}×{s['height']} 像素，约 {s['colors']} 种颜色；要求：{s['brief']}。"
                "已有对应底稿就保留；否则先保存当前作品，再用 pixel_redraw_begin(mode='draft') 生成可编辑底稿。"
                "按 pixel_help(topic='image_workflow') 干净拆分可见物件，逐层和合成检查，保留底稿像素、色板与原造型。"
                "后续修改和动画按我在对话中的要求进行，不默认重绘、补齐遮挡或新增动作。"
                "每次使用实际读到的工程版本和参考版本；最后保存 .pixloom 和透明 PNG。")
        self.editor.root.clipboard_clear()
        self.editor.root.clipboard_append(text)
        self.status.config(text="已复制。请在已连接 MCP 的 AI 对话中发送这段指令。", fg=GREEN)

    def draw_tile(self, key, image, nearest=False):
        canvas = self.canvases[key]
        canvas.delete("all")
        if image is None:
            canvas.create_text(max(1, canvas.winfo_width())//2, max(1, canvas.winfo_height())//2,
                               text="等待导入" if key != "art" else "等待生成", fill=MUTED, font=FONT)
            return None
        width, height = max(1, canvas.winfo_width()-12), max(1, canvas.winfo_height()-12)
        ratio = min(width/image.width, height/image.height, 12 if nearest else 2)
        size = max(1, int(image.width*ratio)), max(1, int(image.height*ratio))
        shown = checker(image).resize(size, Image.Resampling.NEAREST if nearest else Image.Resampling.LANCZOS)
        self.photos[key] = ImageTk.PhotoImage(shown)
        x, y = (canvas.winfo_width()-size[0])//2, (canvas.winfo_height()-size[1])//2
        canvas.create_image(x, y, image=self.photos[key], anchor="nw")
        return x, y, size[0]/image.width, size[1]/image.height

    def draw_images(self):
        context = self.editor.service.references.context
        asset = context["subject"]
        self.source_transform = self.draw_tile("subject", decoded_asset(asset["png"]) if asset else None)
        try:
            draft = make_draft(context)[0] if asset else None
            self.draw_tile("draft", draft, True)
        except ValueError:
            self.draw_tile("draft", None)
        summary = self.editor.service.references.summary(self.editor.doc)
        self.titles["art"].config(text="③ 当前像素工程" if summary["current_project_has_same_subject"] else "③ 当前工程 · 尚未关联")
        self.draw_tile("art", self.editor.doc.composite(), True)
        if asset and context["settings"]["crop"] and self.source_transform:
            x, y, sx, sy = self.source_transform
            cx, cy, w, h = context["settings"]["crop"]
            self.canvases["subject"].create_rectangle(x+cx*sx, y+cy*sy, x+(cx+w)*sx, y+(cy+h)*sy, outline=ACCENT, width=2)

    def source_point(self, event):
        asset = self.editor.service.references.context["subject"]
        if not asset or not self.source_transform:
            return None
        x, y, sx, sy = self.source_transform
        return max(0, min(asset["size"][0]-1, int((event.x-x)/sx))), max(0, min(asset["size"][1]-1, int((event.y-y)/sy)))

    def crop_start(self, event):
        self.crop_drag = self.source_point(event)

    def crop_move(self, event):
        if self.crop_drag is None:
            return
        last = self.source_point(event)
        x, y, sx, sy = self.source_transform
        self.canvases["subject"].delete("crop-drag")
        self.canvases["subject"].create_rectangle(x+self.crop_drag[0]*sx, y+self.crop_drag[1]*sy, x+last[0]*sx, y+last[1]*sy,
                                                 outline=ACCENT, width=2, tags="crop-drag")

    def crop_end(self, event):
        if self.crop_drag is None:
            return
        last, first = self.source_point(event), self.crop_drag
        self.crop_drag = None
        rect = [min(first[0], last[0]), min(first[1], last[1]), abs(last[0]-first[0])+1, abs(last[1]-first[1])+1]
        self.quiet = True
        for variable, value in zip(self.crop_vars, rect):
            variable.set(value)
        self.quiet = False
        self.schedule()

    def reset_crop(self):
        self.quiet = True
        for var in self.crop_vars:
            var.set("")
        self.quiet = False
        self.schedule()

    def show_style(self):
        asset = self.editor.service.references.context["style"]
        if not asset:
            self.status.config(text="可自行导入风格图，也可不选。应用不自带风格图。", fg=MUTED)
            return
        if self.style_window is not None and self.style_window.winfo_exists():
            self.style_window.lift()
            return
        dialog = tk.Toplevel(self.dialog)
        self.style_window = dialog
        dialog.asset_id = asset["id"]
        dialog.title("风格参考 · " + asset["name"])
        dialog.configure(bg=BG)
        image = decoded_asset(asset["png"])
        image = checker(image)
        image.thumbnail((700, 600), Image.Resampling.LANCZOS)
        dialog.photo = ImageTk.PhotoImage(image)
        tk.Label(dialog, image=dialog.photo, bg=BG).pack(padx=12, pady=12)
        place_dialog(dialog, self.editor.root, image.width+24, image.height+24)

    def poll(self):
        self.poll_job = None
        if self.tokens() != self.observed:
            if not self.pending and self.crop_drag is None:
                self.refresh()
            else:
                self.status.config(text="工程或参考已更新。保留当前输入；点击刷新后重新调整。", fg=ACCENT)
        self.poll_job = self.dialog.after(900, self.poll)

    def cleanup(self, event):
        if event.widget == self.dialog:
            for job in (self.job, self.poll_job):
                if job:
                    self.dialog.after_cancel(job)
            self.job = self.poll_job = None
