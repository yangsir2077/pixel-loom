from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog

from PIL import Image, ImageDraw, ImageTk

from .bridge import Bridge
from .paths import WORKSPACE as ROOT, RUNTIME, prepare
from .service import DocumentService
from .model import Document, PixelError, hexcolor, integer, rgba, pixels, atomic_json


from .ui import DesktopUI, TOOL_INFO, place_dialog, bind_scroll_wheel, dark_titlebar, BG, PANEL, FIELD, EDGE, FG, MUTED, ACCENT, GREEN, FONT, SMALL
from .workflows import symmetric_ops
from .messages import user_error


class Editor(DesktopUI):
    def __init__(self, root, project=None):
        prepare()
        self.root = root
        self.root.title("Pixel Loom · 像素织机")
        self.root.configure(bg=BG)
        screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(1460, screen_w - 100)}x{min(980, screen_h - 100)}+45+35")
        root.minsize(min(1160, screen_w - 70), min(760, screen_h - 90))
        root.option_add("*Font", FONT)
        root.option_add("*Dialog.msg.font", FONT)
        self.doc = Document()
        self.path = None
        self.dirty = False
        self.saved_revision = 0
        self.saved_fingerprint = self.doc.fingerprint()
        self.zoom = 12
        self.pan = [0, 0]
        self.origin = (0, 0)
        self.tool = "pen"
        self.color_index = 22
        self.stroke_size = tk.IntVar(value=1)
        self.show_grid = tk.BooleanVar(value=False)
        self.onion = tk.BooleanVar(value=False)
        self.show_regions = tk.BooleanVar(value=False)
        self.show_reference = tk.BooleanVar(value=False)
        self.filled = tk.BooleanVar(value=True)
        self.playing = False
        self.playback_job = None
        self.playback_rate = 1.0
        self.playback_speed = tk.StringVar(value="1×")
        self.gesture = None
        self.override = None
        self.hover = None
        self.path_points = []
        self.selection_preview = None
        self.workspace_mode = "preview"
        self.feedback_draft = None
        self.feedback_focus = None
        self._building = True
        self.clipboard_image = None
        self.tag_var = tk.StringVar(value="全部帧")
        self.thumb_images = []
        self.palette_buttons = []
        self.layer_ids = []
        self.error = None
        self.autosave_job = None
        self.welcome_window = None
        self.welcome_job = None
        self.updates = None
        try:
            self.layout_preferences = json.loads((RUNTIME / "ui-layout.json").read_text(encoding="utf-8"))
            if not isinstance(self.layout_preferences, dict):
                self.layout_preferences = {}
        except (OSError, ValueError):
            self.layout_preferences = {}
        self._build()
        self._building = False
        if project:
            self.doc = Document.open(project)
            self.path = Path(project)
        elif (RUNTIME / "last-project.json").exists():
            try:
                candidate = json.loads((RUNTIME / "last-project.json").read_text(encoding="utf-8"))["path"]
                if candidate:
                    self.doc = Document.open(candidate)
                    self.path = Path(candidate)
            except (OSError, ValueError, KeyError):
                pass
        self.saved_revision = self.doc.revision
        self.saved_fingerprint = self.doc.fingerprint()
        self.service = DocumentService(self.doc, mode="desktop")
        self.sync_service()
        self.service.remember_path()
        self.bridge = Bridge()
        self.refresh()
        self.set_workspace_mode("preview")
        self.fit_job=root.after(150, self.fit)
        self.pump_job=root.after(40, self.pump)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._shortcuts()
        root.after_idle(lambda: dark_titlebar(root))
        self.welcome_job = root.after(300, self.show_startup_guide)
        from .update_ui import UpdateController
        self.updates = UpdateController(self)

    def show_updates(self):
        if self.updates is not None:
            return self.updates.show_dialog()

    def show_startup_guide(self):
        self.welcome_job = None
        if self.root.winfo_viewable():
            self.show_welcome()

    def show_welcome(self):
        if self.welcome_job:
            self.root.after_cancel(self.welcome_job)
            self.welcome_job = None
        if self.welcome_window and self.welcome_window.dialog.winfo_exists():
            self.welcome_window.dialog.lift()
            return self.welcome_window
        from .welcome import WelcomeDialog
        self.welcome_window = WelcomeDialog(self)
        return self.welcome_window

    def label(self, parent, text, fg=FG, font=FONT, **kw):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=fg, font=font, **kw)

    def button(self, parent, text, command, accent=False, **kw):
        options = dict(bg=ACCENT if accent else FIELD, fg=BG if accent else FG,
                       activebackground="#3b4e6d", activeforeground=FG, disabledforeground="#65748a",
                       relief="flat", bd=0, padx=10, pady=6, cursor="hand2")
        options.update(kw)
        return tk.Button(parent, text=text, command=command, **options)

    def _shortcuts(self):
        self.root.bind("<Control-k>", lambda e: self.command_palette())
        self.root.bind("<Control-s>", lambda e: self.save())
        self.root.bind("<Control-Shift-S>", lambda e: self.save_as())
        self.root.bind("<Control-o>", lambda e: self.open_dialog())
        self.root.bind("<Control-n>", lambda e: self.new_dialog())
        self.root.bind("<Control-z>", lambda e: None if self.editing_text() else self.undo())
        self.root.bind("<Control-y>", lambda e: None if self.editing_text() else self.redo())
        self.root.bind("<Control-Shift-Z>", lambda e: None if self.editing_text() else self.redo())
        self.root.bind("<Control-c>", lambda e: self.copy_selection())
        self.root.bind("<Control-x>", lambda e: self.cut_selection())
        self.root.bind("<Control-v>", lambda e: self.paste_selection())
        self.root.bind("<Control-a>", lambda e: None if self.editing_text() else self.apply([{"op": "selection_set", "rect": [0, 0, self.doc.width, self.doc.height]}], "全选"))
        self.root.bind("<KeyPress>", self.keypress)

    def keypress(self, event):
        if isinstance(event.widget, (tk.Entry, tk.Text, tk.Spinbox)) or event.state & 0x4:
            return
        mapping = {"b": "pen", "e": "eraser", "g": "fill", "i": "picker", "l": "line",
                   "r": "rect", "o": "ellipse", "m": "move", "s": "select", "p": "polygon", "q": "bezier", "a":"feedback_lasso"}
        if event.keysym.lower() in mapping:
            self.choose_tool(mapping[event.keysym.lower()])
        elif event.keysym.lower() == "f":
            self.fit()
        elif event.keysym == "space":
            self.toggle_play()
        elif event.keysym == "Escape":
            self.gesture = self.override = None
            self.path_points = []
            self.selection_preview = None
            self.feedback_draft = self.feedback_focus = None
            self.apply([{"op": "selection_set"}], "取消选区")
            self.render()
        elif event.keysym == "Return" and self.path_points:
            self.finish_path()
        elif event.keysym == "Delete" and self.doc.selection and self.workspace_mode=="manual":
            self.apply([{"op": "clear", "clip": self.doc.selection}], "清除选区")
        elif event.keysym in ("plus", "equal", "minus"):
            self.change_zoom(-1 if event.keysym == "minus" else 1)
        elif event.keysym in ("Left", "Right"):
            self.select_frame((self.doc.active_frame + (1 if event.keysym == "Right" else -1)) % len(self.doc.durations))

    def choose_tool(self, tool):
        if not self._building:
            desired="feedback" if tool.startswith("feedback_") else "manual"
            if self.workspace_mode!=desired:
                self.set_workspace_mode(desired,choose_default=False)
        self.tool = tool
        self.path_points = []
        self.selection_preview = None
        self.override = None
        for name, button in self.tool_buttons.items():
            button.config(bg="#293a53" if name == tool else PANEL, fg=FG,
                          highlightthickness=0)
        if hasattr(self, "tool_name_label"):
            name, key, hint = TOOL_INFO[tool]
            self.tool_name_label.config(text=name)
            self.tool_hint.config(text=f"{name}"+(f" [{key}]" if key else "")+f"  ·  {hint}")

    def set_workspace_mode(self, mode, choose_default=True):
        if mode not in ("preview","feedback","manual"):
            return
        if self.workspace_mode=="manual" and mode!="manual":
            self._last_manual_tab=self.control_notebook.select()
        playing_frame=self.play_frame if self.playing else None
        self.stop_play()
        if playing_frame is not None and playing_frame!=self.doc.active_frame:
            self.select_frame(playing_frame)
        self.gesture=self.override=None
        self.path_points=[]
        self.selection_preview=None
        self.workspace_mode=mode
        for name,button in self.mode_buttons.items():
            button.config(bg=FIELD if name==mode else BG,fg=ACCENT if name==mode else MUTED)
        for button in self.tool_buttons.values():
            button.grid_remove()
        if mode=="preview":
            self.tool_rail.pack_forget()
        else:
            self.tool_rail.pack(side="left",fill="y",before=self.editor_panes,padx=(0,6))
            tools=(["feedback_lasso","feedback_rect","feedback_ellipse"] if mode=="feedback" else
                   ["pen","eraser","fill","picker","select","move"])
            for row,name in enumerate(tools):
                self.tool_buttons[name].grid(row=row,column=0,padx=1,pady=2)
            self.rail_title.config(text="标记" if mode=="feedback" else "工具")
            if choose_default and ((mode=="feedback")!=self.tool.startswith("feedback_")):
                self.choose_tool("feedback_lasso" if mode=="feedback" else "pen")
        if mode=="manual":
            if not self.editor_dock.winfo_manager():
                width = self.layout_size("dock_width", 310, 260, 520)
                self.editor_panes.add(self.editor_dock, minsize=260, width=width, stretch="never")
            if not self.canvas_settings.winfo_manager():
                self.canvas_settings.pack(fill="x",before=self.canvas)
            self.edit_controls.pack(side="left")
            self.tool_more.pack(fill="x",pady=6)
            self.control_notebook.select(getattr(self,"_last_manual_tab",self.manual_tab))
        else:
            if self.editor_dock.winfo_manager():
                self.layout_preferences["dock_width"] = self.editor_dock.winfo_width()
                self.editor_panes.forget(self.editor_dock)
            self.edit_controls.pack_forget()
            self.canvas_settings.pack_forget()
            self.tool_more.pack_forget()
        self.feedback_panel.show_mode(mode)
        self.canvas.config(cursor="arrow" if mode=="preview" else "crosshair")
        if mode=="preview":
            self.tool_hint.config(text="Space 播放 / 暂停    ← → 逐帧    A 截图反馈    F 适应画布")
        self.render()

    def layout_size(self, key, default, minimum, maximum):
        try:
            return max(minimum, min(maximum, int(self.layout_preferences.get(key, default))))
        except (ValueError, TypeError):
            return default

    def save_ui_layout(self, event=None):
        if self.editor_dock.winfo_manager() and self.editor_dock.winfo_width() > 1:
            self.layout_preferences["dock_width"] = self.editor_dock.winfo_width()
        if self.timeline.winfo_height() > 1:
            self.layout_preferences["timeline_height"] = self.timeline.winfo_height()
        try:
            atomic_json(RUNTIME / "ui-layout.json", self.layout_preferences)
        except OSError:
            pass  # Layout preferences must never prevent editing or saving artwork.

    def apply(self, ops, label, source="手动"):
        self.stop_play()
        try:
            size = (self.doc.width, self.doc.height)
            self.doc.apply(ops, label=label, source=source)
            if all(op["op"] in ("select", "selection_set") for op in ops):
                self.sync_service()
                self.status_label.config(text=label, fg=MUTED)
                self.refresh_view()
            else:
                self.changed(label)
            if size != (self.doc.width, self.doc.height):
                self.fit()
            return True
        except (PixelError, ValueError, KeyError) as exc:
            self.status_label.config(text=user_error(exc), fg="#f19493")
            return False

    def changed(self, label="已更新"):
        self.dirty = self.doc.fingerprint() != self.saved_fingerprint
        self.sync_service()
        self.status_label.config(text=label, fg=MUTED)
        self.refresh()
        if self.autosave_job:
            self.root.after_cancel(self.autosave_job)
        self.autosave_job = self.root.after(500, self.autosave)

    def autosave(self):
        self.autosave_job = None
        try:
            self.sync_service()
            self.service.autosave()
        except OSError as exc:
            self.status_label.config(text=f"自动恢复文件写入失败：{exc}", fg="#f19493")

    def sync_service(self):
        if hasattr(self, "service"):
            self.service.doc = self.doc
            self.service.path = self.path
            self.service.saved_fingerprint = self.saved_fingerprint
            self.service.view = {"playing": self.playing, "playback_rate": self.playback_rate,
                                 "gesture_active": bool(self.gesture or self.path_points or
                                     getattr(getattr(self,'material_window',None),'brush',None))}

    def refresh(self):
        self.color_index = min(self.color_index, len(self.doc.palette) - 1)
        star = " *" if self.dirty else ""
        self.project_label.config(text=self.doc.name + star)
        self.tab_label.config(text=f"{self.doc.width} × {self.doc.height} px  ·  {len(self.doc.layers)} 图层")
        self.duration_var.set(self.doc.durations[self.doc.active_frame])
        self.opacity_var.set(self.doc.layer().opacity)
        duration = self.doc.durations[self.doc.active_frame]
        self.timing_hint.config(text=f"{sum(self.doc.durations)/1000:.2f}s · {1000/duration:.1f} FPS")
        self.root.title(f"{self.doc.name}{star} — Pixel Loom · 像素织机")
        self.undo_button.config(state="normal" if self.doc.undo_stack else "disabled")
        self.redo_button.config(state="normal" if self.doc.redo_stack else "disabled")
        self.render()
        self.refresh_palette()
        self.refresh_layers()
        self.refresh_frames()
        self.refresh_events()
        self.refresh_tags()
        self.refresh_projects()
        if hasattr(self,"feedback_panel"):
            self.feedback_panel.refresh()
        if hasattr(self,"service") and hasattr(self,"quality_label"):
            review=self.service.quality.summary(self.doc)
            labels={"pending":"待检查与 AI 看图复核","stale":"作品已修改，待复查","passed":"AI 自检通过", "needs_changes":"需修改后复查","uncertain":"尚未确认合格","partial":"部分动作已通过，图集待复核"}
            scope=review.get("scope",{})
            prefix=(scope["tag"]+" · ") if scope.get("tag") else ""
            self.quality_label.config(text="自检："+prefix+labels[review["status"]],fg=GREEN if review["status"]=="passed" else ACCENT)

    def refresh_view(self):
        self.duration_var.set(self.doc.durations[self.doc.active_frame])
        self.opacity_var.set(self.doc.layer().opacity)
        duration = self.doc.durations[self.doc.active_frame]
        self.timing_hint.config(text=f"{sum(self.doc.durations)/1000:.2f}s · {1000/duration:.1f} FPS")
        self.render()
        self.refresh_layers()
        self.refresh_playhead(self.doc.active_frame)
        self.frame_info.config(text=f"{self.doc.active_frame+1:02d} / {len(self.doc.durations):02d} 帧")
        self.undo_button.config(state="normal" if self.doc.undo_stack else "disabled")
        self.redo_button.config(state="normal" if self.doc.redo_stack else "disabled")

    def refresh_palette(self):
        self.palette_constraint.set(self.doc.strict_palette)
        signature = tuple(self.doc.palette)
        if self._palette_signature != signature:
            for child in self.palette_frame.winfo_children():
                child.destroy()
            self.palette_buttons = []
            for i, color in enumerate(self.doc.palette):
                c = rgba(color)
                button = tk.Button(self.palette_frame, text="×" if c[3] == 0 else "", bg=color[:7] if c[3] else FIELD,
                                   fg=MUTED, width=2, height=1, relief="flat", bd=0, padx=0, pady=0,
                                   font=("Segoe UI", 8), highlightthickness=2, activebackground=color[:7], cursor="hand2",
                                   command=lambda index=i: self.select_color(index))
                button.grid(row=i // 8, column=i % 8, padx=1, pady=1, sticky="nsew")
                self.bind_panel_scroll(button)
                self.palette_buttons.append(button)
            for i in range(8):
                self.palette_frame.columnconfigure(i, weight=1)
            self._palette_signature = signature
        for i, button in enumerate(self.palette_buttons):
            button.config(highlightbackground=ACCENT if i == self.color_index else PANEL,
                          highlightcolor=ACCENT if i == self.color_index else PANEL)
        self.color_label.config(text=f"#{self.color_index:02d}  {self.doc.palette[self.color_index].upper()}  {'● 约束开' if self.doc.strict_palette else '约束关'}")

    def select_color(self, index):
        self.color_index = index
        self.refresh_palette()

    def add_color(self):
        _, color = colorchooser.askcolor(initialcolor=self.doc.palette[self.color_index][:7], parent=self.root, title="添加调色板颜色")
        if color and self.apply([{"op": "palette_add", "colors": [color]}], "添加颜色"):
            self.select_color(self.doc.palette.index(hexcolor(rgba(color))))

    def refresh_layers(self):
        self.layer_count_label.config(text=f"{len(self.doc.layers)} 个图层")
        previous_ids = self.layer_ids
        top_id = previous_ids[self.layers_widget.nearest(0)] if previous_ids else None
        horizontal = self.layers_widget.xview()[0]
        reveal_active = (getattr(self, "_layers_document_id", None) != self.doc.id or
                         getattr(self, "_layers_active_id", None) != self.doc.active_layer)
        self.layers_widget.delete(0, "end")
        self.layer_ids = []
        for layer in reversed(self.doc.layers):
            self.layer_ids.append(layer.id)
            self.layers_widget.insert("end", f"{'●' if layer.visible else '○'}  {'▣' if layer.locked else '  '}  {layer.name}")
            if layer.id == self.doc.active_layer:
                self.layers_widget.selection_set(len(self.layer_ids) - 1)
                self.layers_widget.activate(len(self.layer_ids) - 1)
        if top_id in self.layer_ids:
            self.layers_widget.yview(self.layer_ids.index(top_id))
        self.layers_widget.xview_moveto(horizontal)
        if reveal_active:
            self.layers_widget.see(self.layer_ids.index(self.doc.active_layer))
        self._layers_document_id = self.doc.id
        self._layers_active_id = self.doc.active_layer

    def layer_selected(self, event=None):
        selected = self.layers_widget.curselection()
        if selected and selected[0] < len(self.layer_ids):
            layer_id = self.layer_ids[selected[0]]
            if layer_id != self.doc.active_layer:
                self.apply([{"op": "select", "layer": layer_id}], "选择图层")

    def add_layer(self):
        name = simpledialog.askstring("新图层", "给图层起一个清晰的名字（如：身体、眼睛、阴影）：", parent=self.root)
        if name:
            self.apply([{"op": "layer_add", "name": name}], f"添加图层 · {name}")

    def rename_layer(self, event=None):
        name = simpledialog.askstring("重命名图层", "图层名称：", initialvalue=self.doc.layer().name, parent=self.root)
        if name:
            self.apply([{"op": "layer_set", "name": name}], "重命名图层")

    def toggle_layer(self):
        self.apply([{"op": "layer_set", "visible": not self.doc.layer().visible}], "切换图层可见性")

    def lock_layer(self):
        self.apply([{"op": "layer_set", "locked": not self.doc.layer().locked}], "切换图层锁定")

    def reorder_layer(self, direction):
        index = self.doc.layers.index(self.doc.layer()) + direction
        if 0 <= index < len(self.doc.layers):
            self.apply([{"op": "layer_move", "index": index}], "调整图层顺序")

    def delete_layer(self):
        self.apply([{"op": "layer_delete"}], "删除图层")

    def layer_menu(self, event):
        index = self.layers_widget.nearest(event.y)
        if 0 <= index < len(self.layer_ids) and self.layer_ids[index] != self.doc.active_layer:
            self.apply([{"op": "select", "layer": self.layer_ids[index]}], "选择图层")
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="复制当前图层", command=lambda: self.apply([{"op": "layer_duplicate"}], "复制图层"))
        menu.add_command(label="向下合并", command=lambda: self.apply([{"op": "layer_merge_down"}], "向下合并"))
        menu.add_command(label="设置不透明度", command=self.opacity_dialog)
        menu.add_separator()
        menu.add_command(label="重命名", command=self.rename_layer)
        menu.add_separator()
        menu.add_command(label="删除当前图层", command=self.delete_layer)
        menu.tk_popup(event.x_root, event.y_root)

    def opacity_dialog(self):
        value = simpledialog.askinteger("图层不透明度", "0 为透明，255 为不透明：", initialvalue=self.doc.layer().opacity,
                                        minvalue=0, maxvalue=255, parent=self.root)
        if value is not None:
            self.apply([{"op": "layer_set", "opacity": value}], "修改不透明度")

    def editing_text(self):
        widget = self.root.focus_get()
        return widget is not None and widget.winfo_class() in ("Entry", "Text", "Spinbox", "TEntry", "TCombobox")

    def copy_selection(self):
        if self.editing_text():
            return
        if not self.doc.selection:
            self.status_label.config(text="先用 S 拖出矩形选区，再复制", fg=MUTED)
            return
        x, y, w, h = self.doc.selection
        self.clipboard_image = self.doc.layer().cels[self.doc.active_frame].crop((x, y, x + w, y + h))
        self.clipboard_origin = (x, y)
        self.status_label.config(text=f"已复制当前图层的 {w} × {h} 像素", fg=GREEN)

    def cut_selection(self):
        if self.workspace_mode!="manual" and not self.editing_text():
            self.status_label.config(text="切换到“手动修改”后可剪切图像。",fg=MUTED)
            return
        if self.editing_text():
            return
        self.copy_selection()
        if self.doc.selection:
            self.apply([{"op": "clear", "clip": self.doc.selection}], "剪切选区")

    def paste_selection(self):
        if self.workspace_mode!="manual" and not self.editing_text():
            self.status_label.config(text="切换到“手动修改”后可粘贴图像。",fg=MUTED)
            return
        if self.editing_text() or self.clipboard_image is None:
            return
        image = self.clipboard_image
        colors = sorted({color for color in pixels(image) if color[3]})
        mapping = {color: chr(0x100 + index) for index, color in enumerate(colors)}
        x, y = self.doc.selection[:2] if self.doc.selection else self.clipboard_origin
        extra = [hexcolor(color) for color in colors if hexcolor(color) not in self.doc.palette]
        if self.doc.strict_palette and len(self.doc.palette) + len(extra) > 256:
            self.status_label.config(text="粘贴区域超出 256 色，请先关闭颜色约束，或减少图片颜色。", fg="#f19493")
            return False
        ops = [{"op": "palette_add", "colors": extra}] if extra and self.doc.strict_palette else []
        if colors:
            ops.append({"op": "stamp", "x": x, "y": y,
                        "rows": ["".join(mapping.get(image.getpixel((px, py)), ".") for px in range(image.width)) for py in range(image.height)],
                        "colors": {symbol: hexcolor(color) for color, symbol in mapping.items()}})
            self.apply(ops, "粘贴像素选区")

    def flip_selection(self):
        op = {"op": "region_transform", "kind": "flip_horizontal"} if self.doc.selection else {"op": "flip", "axis": "horizontal"}
        self.apply([op], "水平翻转")

    def rotate_selection(self):
        if self.doc.selection:
            self.apply([{"op": "region_transform", "kind": "rotate_cw"}], "选区顺时针旋转")
        else:
            self.status_label.config(text="先用 S 选中要旋转的部分", fg=MUTED)

    def finish_path(self):
        minimum = 3
        points = []
        for point in self.path_points:
            if not points or point != points[-1]:
                points.append(point)
        if len(points) < minimum:
            self.status_label.config(text="至少放置三个点；Enter / 右键完成，Esc 取消", fg=MUTED)
            return
        try:
            size = integer(self.stroke_size.get(), "size", 1, 16)
        except (ValueError, tk.TclError):
            self.status_label.config(text="笔刷大小请输入 1–16 的整数", fg="#f19493")
            return
        op = {"op": self.tool, "points": [list(p) for p in points], "color": self.color_index, "size": size}
        if self.tool == "polygon":
            op["filled"] = self.filled.get()
        self.path_points = []
        self.apply(symmetric_ops(op, self.doc.width, self.doc.height, self.symmetry_mode()), "绘制多边形" if self.tool == "polygon" else "绘制贝塞尔曲线")

    def refresh_tags(self):
        if not hasattr(self, "tag_menu"):
            return
        choices = ["全部帧", *self.doc.tags]
        if self.tag_var.get() not in choices:
            self.tag_var.set("全部帧")
        menu = self.tag_menu["menu"]
        menu.delete(0, "end")
        for name in choices:
            menu.add_command(label=name, command=lambda item=name: self.choose_tag(item))

    def choose_tag(self, name):
        self.stop_play()
        self.tag_var.set(name)
        if name in self.doc.tags:
            self.select_frame(self.doc.tags[name]["start"])

    def tags_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("动画动作分组")
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        frame = tk.Frame(dialog, bg=PANEL, padx=20, pady=18)
        frame.pack(fill="both", expand=True)
        self.label(frame, "动作名和帧范围（界面从 1 开始；MCP 从 0 开始）", MUTED, SMALL).grid(row=0, columnspan=2, pady=(0, 12))
        name = tk.StringVar(value=self.tag_var.get() if self.tag_var.get() in self.doc.tags else "idle")
        existing = self.doc.tags.get(name.get(), {})
        first = tk.IntVar(value=existing.get("start", 0) + 1)
        last = tk.IntVar(value=existing.get("end", len(self.doc.durations) - 1) + 1)
        direction = tk.StringVar(value=existing.get("direction", "forward"))
        for row, (text, variable) in enumerate([("动作名称", name), ("起始帧", first), ("结束帧", last)], 1):
            self.label(frame, text).grid(row=row, column=0, sticky="w", pady=5)
            tk.Entry(frame, textvariable=variable, bg=FIELD, fg=FG, insertbackground=FG, relief="flat").grid(row=row, column=1, pady=5)
        self.label(frame, "播放方向").grid(row=4, column=0, sticky="w")
        tk.OptionMenu(frame, direction, "forward", "reverse", "pingpong").grid(row=4, column=1)
        def save_tag():
            try:
                success = self.apply([{"op": "tag_set", "name": name.get(), "start": first.get() - 1,
                                      "end": last.get() - 1, "direction": direction.get()}], "定义动画动作")
                if success:
                    self.tag_var.set(name.get())
                    dialog.destroy()
            except tk.TclError:
                messagebox.showerror("帧范围无效", "请输入整数帧号", parent=dialog)
        self.button(frame, "保存动作", save_tag, True).grid(row=5, column=1, pady=12, sticky="e")
        if existing:
            self.button(frame, "删除分组", lambda: (self.apply([{"op": "tag_delete", "name": name.get()}], "删除动作分组"), dialog.destroy())).grid(row=5, column=0)
        place_dialog(dialog, self.root, 530, 380)

    def workflow_dialog(self):
        from .workflow_ui import show
        return show(self)

    def help_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Pixel Loom · 使用指南与恢复")
        dialog.configure(bg=PANEL)
        place_dialog(dialog, self.root, 720, 510)
        dialog.transient(self.root)
        text = tk.Text(dialog, bg=PANEL, fg=FG, wrap="word", relief="flat", padx=20, pady=18)
        text.pack(fill="both", expand=True)
        text.insert("end", "可视化工作台\n右侧分为“图层”“调色”“操作”；图层独立滚动，颜色单独查看。“操作”提供起伏、往返、批量时长、范围复制和描边，可先预览再应用。\nCtrl+K 搜索命令；F 适应画布；对称开关提供左右、上下和四向绘画。\n\n手动绘画\nB 铅笔 / E 橡皮 / G 填充 / S 选区 / M 移动\nP 多边形：逐点单击，Enter 或右键完成\nQ 曲线：放置 3 或 4 个控制点，Enter 完成\nCtrl+C/X/V 复制、剪切、粘贴选区；Esc 取消。\n\n动画\n复制帧后修改局部；动作分组可定义待机、走路、攻击和循环方向。\n右键图层列表可复制、向下合并和调整不透明度。\n\nAI / MCP\n连接后先调用 pixel_onboard。工具自带参数结构，pixel_help 提供示例。\n用 pixel_validate 预看修改，用 pixel_contact_sheet 对照多帧。\n\n文件\n工程为 .pixloom；透明 PNG / 精灵表+JSON / GIF 可以导出。\n" +
                    f"\n默认工作间：{ROOT}\n恢复目录：{RUNTIME / 'recovery'}\n\n可用下方按钮选择恢复副本；打开前会提示保存当前修改。")
        text.config(state="disabled")
        row = tk.Frame(dialog, bg=PANEL, padx=14, pady=10)
        row.pack(fill="x")
        def recover():
            path = filedialog.askopenfilename(parent=dialog, initialdir=RUNTIME / "recovery", filetypes=[("恢复工程", "*.pixloom")])
            if path and self.can_replace():
                try:
                    self.replace_document(Document.open(path))
                    self.path = None
                    dialog.destroy()
                except (OSError, ValueError) as exc:
                    messagebox.showerror("恢复失败", str(exc), parent=dialog)
        self.button(row, "打开恢复副本", recover).pack(side="left")
        self.button(row, "MCP 接入", lambda: (dialog.destroy(), self.connection_dialog())).pack(side="right")

    def refresh_frames(self):
        count = len(self.doc.durations)
        prior = getattr(self, "_thumbnail_state", None) if getattr(self, "_thumbnail_document", None) is self.doc else None
        current = (self.doc.id, self.doc.content_serial, count)
        if prior == current:
            invalid = set()
        elif prior and prior[0] == current[0] and prior[1] + 1 == current[1] and prior[2] == count and self.doc.last_change is not None:
            invalid = {item["frame"] for item in self.doc.last_change["frames"]}
        else:
            invalid = set(range(count))
        if len(self.frame_buttons) != count:
            for child in self.frames_widget.winfo_children():
                child.destroy()
            self.frame_buttons, self.thumb_images, self._thumb_keys = [], [None]*count, [None]*count
            for i in range(count):
                button = tk.Button(self.frames_widget, compound="top", width=76, height=73, fg=FG,
                                   relief="flat", bd=0, highlightthickness=1, font=("Segoe UI", 8), cursor="hand2",
                                   command=lambda f=i: self.select_frame(f))
                button.pack(side="left", padx=(0, 5))
                button.bind("<Button-3>", lambda event, frame=i: self.frame_menu(event, frame))
                bind_scroll_wheel(button, self.frame_canvas.xview_scroll, units=83)
                self.frame_buttons.append(button)
        for i, duration in enumerate(self.doc.durations):
            if i in invalid or self.thumb_images[i] is None:
                image = self.doc.preview(i, scale=1)
                ratio = min(52/image.width, 46/image.height)
                image = image.resize((max(1, int(image.width*ratio)), max(1, int(image.height*ratio))), Image.Resampling.NEAREST)
                self.thumb_images[i] = ImageTk.PhotoImage(image)
                self.frame_buttons[i].config(image=self.thumb_images[i])
            self.frame_buttons[i].config(text=f"{i+1:02d}   {duration}ms")
        self._thumbnail_state = current
        self._thumbnail_document = self.doc
        self.frames_widget.update_idletasks()
        self.frame_canvas.config(scrollregion=self.frame_canvas.bbox("all"))
        self.refresh_playhead(self.doc.active_frame)
        self.frame_info.config(text=f"{self.doc.active_frame+1:02d} / {count:02d} 帧")

    def refresh_playhead(self, frame, reveal=False):
        for i, button in enumerate(self.frame_buttons):
            button.config(bg="#354b70" if i == frame else FIELD,
                          highlightbackground=ACCENT if i == frame else FIELD)
        identity = self.doc.id, frame
        if not reveal and getattr(self, "_timeline_revealed", None) == identity:
            return
        self._timeline_revealed = identity
        total = max(1, self.frames_widget.winfo_reqwidth())
        left, right = self.frame_canvas.xview()
        button = self.frame_buttons[frame]
        start = button.winfo_x()
        end = start + button.winfo_width()
        visible = max(1, self.frame_canvas.winfo_width())
        if start < left*total:
            self.frame_canvas.xview_moveto(start/total)
        elif end > right*total:
            self.frame_canvas.xview_moveto(max(0, end+5-visible)/total)

    def refresh_events(self):
        if not hasattr(self,"events_widget") or not self.events_widget.winfo_exists():
            return
        self.events_widget.config(state="normal")
        self.events_widget.delete("1.0", "end")
        for event in reversed(self.doc.events[-7:]):
            source = "AI" if event["source"] == "AI" else "手动" if event["source"] == "手动" else "历史"
            self.events_widget.insert("end", f"r{event['revision']}  {source} · {event['label']}\n")
        if not self.doc.events:
            self.events_widget.insert("end", "连接 MCP 后，AI 的修改会同步显示在这里。\n\n可命名图层和部位，方便精确修改。")
        self.events_widget.config(state="disabled")

    def frame_menu(self, event, frame):
        self.select_frame(frame)
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="向前移动", state="normal" if frame else "disabled",
                         command=lambda: self.apply([{"op": "frame_move", "frame": frame, "index": frame - 1}], "前移帧"))
        menu.add_command(label="向后移动", state="normal" if frame < len(self.doc.durations) - 1 else "disabled",
                         command=lambda: self.apply([{"op": "frame_move", "frame": frame, "index": frame + 1}], "后移帧"))
        menu.add_command(label="复制帧", command=lambda: self.apply([{"op": "frame_add", "after": frame, "copy_from": frame}], "复制动画帧"))
        menu.add_command(label="插入空白帧", command=lambda: self.apply([{"op":"frame_add","after":frame,"blank":True}],"添加空白帧"))
        menu.add_command(label="设置时长", command=self.set_duration)
        menu.add_separator()
        menu.add_command(label="删除当前帧", command=lambda: self.apply([{"op": "frame_delete", "frame": frame}], "删除动画帧"))
        menu.tk_popup(event.x_root, event.y_root)

    def fit(self):
        self.root.update_idletasks()
        if self.canvas.winfo_width() < 2 or self.canvas.winfo_height() < 2:
            return
        ratio = min(max(1, self.canvas.winfo_width() - 32) / self.doc.width,
                    max(1, self.canvas.winfo_height() - 32) / self.doc.height)
        self.zoom = min(24, int(ratio)) if ratio >= 1 else max(1/64, ratio)
        self.pan = [0, 0]
        self.render()

    def render(self):
        if not hasattr(self, "canvas") or self.canvas.winfo_width() < 2:
            return
        doc = self.doc
        current_frame = self.play_frame if self.playing else doc.active_frame
        override = self.override
        if len(self.path_points) >= 3 and self.tool in ("polygon", "bezier"):
            try:
                op = {"op": self.tool, "points": self.path_points, "color": self.color_index, "size": self.stroke_size.get()}
                if self.tool == "polygon":
                    op["filled"] = self.filled.get()
                patch = doc.layer().cels[current_frame].copy()
                for mirrored in symmetric_ops(op, doc.width, doc.height, self.symmetry_mode()):
                    doc.draw_on(patch, mirrored)
                if doc.selection:
                    x, y, w, h = doc.selection
                    clipped = doc.layer().cels[current_frame].copy()
                    clipped.paste(patch.crop((x, y, x+w, y+h)), (x, y))
                    patch = clipped
                override = (doc.active_layer, patch)
            except (ValueError, tk.TclError):
                pass
        image = doc.composite(current_frame, override=override)
        checker = Image.new("RGBA", image.size, "#292f3a")
        draw = ImageDraw.Draw(checker)
        for y in range(0, doc.height, 4):
            for x in range(0, doc.width, 4):
                if (x // 4 + y // 4) % 2:
                    draw.rectangle((x, y, x + 3, y + 3), fill="#343c49")
        if self.onion.get() and current_frame > 0:
            ghost = doc.composite(current_frame - 1)
            tinted = Image.new("RGBA", image.size, "#db86a2")
            tinted.putalpha(ghost.getchannel("A").point(lambda a: a // 4))
            checker = Image.alpha_composite(checker, tinted)
        if self.show_reference.get() and doc.reference and doc.reference.get("subject"):
            from .reference import adjusted_subject, fit_image
            reference = fit_image(adjusted_subject(doc.reference), (doc.width, doc.height), doc.reference["settings"]["fit"])
            reference.putalpha(reference.getchannel("A").point(lambda value: value//3))
            checker = Image.alpha_composite(checker, reference)
        display = Image.alpha_composite(checker, image)
        display = display.resize((max(1, round(doc.width * self.zoom)), max(1, round(doc.height * self.zoom))), Image.Resampling.NEAREST)
        self.photo = ImageTk.PhotoImage(display)
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        ox = (width - display.width) // 2 + self.pan[0]
        oy = (height - display.height) // 2 + self.pan[1]
        self.origin = (ox, oy)
        self.canvas.delete("all")
        self.canvas.create_rectangle(ox - 1, oy - 1, ox + display.width, oy + display.height, outline="#5a6578")
        self.canvas.create_image(ox, oy, image=self.photo, anchor="nw")
        if self.show_grid.get() and self.zoom >= 8:
            for x in range(1, doc.width):
                self.canvas.create_line(ox + x * self.zoom, oy, ox + x * self.zoom, oy + display.height, fill="#222832")
            for y in range(1, doc.height):
                self.canvas.create_line(ox, oy + y * self.zoom, ox + display.width, oy + y * self.zoom, fill="#222832")
        mode = self.symmetry_mode()
        if "x" in mode:
            self.canvas.create_line(ox + doc.width*self.zoom/2, oy, ox + doc.width*self.zoom/2, oy + display.height, fill="#7b9bd0", dash=(5, 5))
        if "y" in mode:
            self.canvas.create_line(ox, oy + doc.height*self.zoom/2, ox + display.width, oy + doc.height*self.zoom/2, fill="#7b9bd0", dash=(5, 5))
        if self.show_regions.get():
            for name, (x, y, w, h) in doc.regions.items():
                self.canvas.create_rectangle(ox + x * self.zoom, oy + y * self.zoom,
                                             ox + (x + w) * self.zoom, oy + (y + h) * self.zoom,
                                             outline=ACCENT, dash=(4, 3))
                self.canvas.create_text(ox + x * self.zoom + 4, oy + y * self.zoom + 3, text=name,
                                        fill=ACCENT, anchor="nw", font=SMALL)
        selection = self.selection_preview or doc.selection
        if selection:
            x, y, w, h = selection
            self.canvas.create_rectangle(ox + x * self.zoom, oy + y * self.zoom,
                                         ox + (x + w) * self.zoom, oy + (y + h) * self.zoom,
                                         outline="#ffffff", dash=(4, 3), width=2)
        if self.path_points:
            for a, b in zip(self.path_points, self.path_points[1:]):
                self.canvas.create_line(ox + (a[0] + .5) * self.zoom, oy + (a[1] + .5) * self.zoom,
                                        ox + (b[0] + .5) * self.zoom, oy + (b[1] + .5) * self.zoom, fill=ACCENT)
            for x, y in self.path_points:
                self.canvas.create_rectangle(ox + x * self.zoom, oy + y * self.zoom,
                                             ox + (x + 1) * self.zoom, oy + (y + 1) * self.zoom, outline=ACCENT)
        preview_scale = max(1, min(2, 72 // max(doc.width, doc.height)))
        preview = doc.preview(current_frame, scale=preview_scale)
        if preview.width > 200 or preview.height > 64:
            preview.thumbnail((200, 64), Image.Resampling.NEAREST)
        self.small_photo = ImageTk.PhotoImage(preview)
        self.preview_widget.config(image=self.small_photo)
        self.preview_info.config(text=f"{doc.width} × {doc.height}  ·  {len(doc.palette)} 色")
        self.zoom_label.config(text=f"{self.zoom * 100:.0f}%")
        self.coordinates_label.config(text=f"{self.zoom * 100:.0f}%  ·  帧 {current_frame + 1}  ·  r{doc.revision}")
        from .feedback_ui import draw_annotations
        draw_annotations(self)

    def pixel_at(self, event, clamp=False):
        x = int((event.x - self.origin[0]) // self.zoom)
        y = int((event.y - self.origin[1]) // self.zoom)
        if clamp:
            return max(0, min(self.doc.width - 1, x)), max(0, min(self.doc.height - 1, y))
        return (x, y) if 0 <= x < self.doc.width and 0 <= y < self.doc.height else None

    def pointer_hover(self, event):
        point = self.pixel_at(event)
        self.canvas.delete("cursor")
        if point:
            x, y = point
            ox, oy = self.origin
            self.canvas.create_rectangle(ox + x * self.zoom, oy + y * self.zoom,
                                         ox + (x + 1) * self.zoom, oy + (y + 1) * self.zoom,
                                         outline="#ffffff", tags="cursor")
            self.coordinates_label.config(text=f"X {x:03d}  Y {y:03d}   ·   {self.zoom * 100:.0f}%   ·   r{self.doc.revision}")

    def pointer_down(self, event):
        self.canvas.focus_set()
        playing_frame=self.play_frame if self.playing else None
        self.stop_play()
        if playing_frame is not None and playing_frame!=self.doc.active_frame:
            self.select_frame(playing_frame)
        if self.workspace_mode=="preview":
            return
        point = self.pixel_at(event)
        if point is None:
            return
        if self.workspace_mode=="feedback":
            self.feedback_focus=None
            self.gesture={"points":[point],"tool":self.tool,"annotation":True,
                          "document_id":self.doc.id,"revision":self.doc.revision}
            self.render()
            return
        if self.tool == "picker":
            return self.pick(event)
        if self.doc.layer().locked and self.tool != "select":
            self.status_label.config(text="当前图层已锁定", fg="#f19493")
            return
        if self.tool in ("polygon", "bezier"):
            self.path_points.append(point)
            self.status_label.config(text=f"已放置 {len(self.path_points)} 个点 · Enter / 右键完成，Esc 取消", fg=MUTED)
            if self.tool == "bezier" and len(self.path_points) == 4:
                self.finish_path()
            else:
                self.render()
            return
        if self.tool == "fill":
            self.apply([{"op": "fill", "x": point[0], "y": point[1], "color": self.color_index}], "油漆桶填充")
            return
        self.gesture = {"points": [point], "tool": self.tool, "revision": self.doc.revision,
                        "layer": self.doc.active_layer, "frame": self.doc.active_frame}
        self.update_gesture()

    def gesture_op(self):
        gesture = self.gesture
        first, last = gesture["points"][0], gesture["points"][-1]
        tool = gesture["tool"]
        base = {"layer": gesture["layer"], "frame": gesture["frame"]}
        if self.doc.selection and tool in ("pen", "eraser", "line", "rect", "ellipse"):
            base["clip"] = self.doc.selection
        color = "#00000000" if tool == "eraser" else self.color_index
        size = integer(self.stroke_size.get(), "size", 1, 16)
        if tool == "select":
            return {"op": "selection_set", "rect": [min(first[0], last[0]), min(first[1], last[1]),
                                                     abs(first[0] - last[0]) + 1, abs(first[1] - last[1]) + 1]}
        if tool in ("pen", "eraser"):
            return dict(base, op="stroke", points=[list(p) for p in gesture["points"]], color=color, size=size)
        if tool == "line":
            return dict(base, op="line", x1=first[0], y1=first[1], x2=last[0], y2=last[1], color=color, size=size)
        if tool in ("rect", "ellipse"):
            return dict(base, op=tool, x=min(first[0], last[0]), y=min(first[1], last[1]),
                        width=abs(first[0] - last[0]) + 1, height=abs(first[1] - last[1]) + 1,
                        color=color, filled=self.filled.get(), size=size)
        if self.doc.selection:
            return dict(base, op="region_transform", rect=self.doc.selection, kind="translate",
                        dx=last[0] - first[0], dy=last[1] - first[1])
        return dict(base, op="translate", dx=last[0] - first[0], dy=last[1] - first[1])

    def update_gesture(self):
        if self.gesture and self.gesture.get("annotation"):
            self.render()
            return
        try:
            op = self.gesture_op()
            if op["op"] == "selection_set":
                self.selection_preview = op["rect"]
                self.render()
                return
            image = self.doc.layer(self.gesture["layer"]).cels[self.gesture["frame"]].copy()
            if op["op"] == "region_transform":
                temporary = Document.from_dict(self.doc.to_dict())
                temporary.execute(op)
                image = temporary.layer(self.gesture["layer"]).cels[self.gesture["frame"]]
                self.selection_preview = temporary.selection
            else:
                for mirrored in symmetric_ops(op, self.doc.width, self.doc.height, self.symmetry_mode()):
                    self.doc.draw_on(image, mirrored)
                if "clip" in op:
                    x, y, w, h = op["clip"]
                    clipped = self.doc.layer(self.gesture["layer"]).cels[self.gesture["frame"]].copy()
                    clipped.paste(image.crop((x, y, x + w, y + h)), (x, y))
                    image = clipped
            self.override = (self.gesture["layer"], image)
            self.render()
        except (PixelError, ValueError, tk.TclError) as exc:
            self.status_label.config(text=str(exc), fg="#f19493")

    def pointer_drag(self, event):
        if self.gesture:
            point = self.pixel_at(event, clamp=True)
            if point != self.gesture["points"][-1]:
                self.gesture["points"].append(point)
                self.update_gesture()

    def pointer_up(self, event):
        if not self.gesture:
            return
        self.pointer_drag(event)
        if self.gesture.get("annotation"):
            gesture,self.gesture=self.gesture,None
            if gesture["document_id"]!=self.doc.id or gesture["revision"]!=self.doc.revision:
                self.status_label.config(text="画面已更新，请在当前画面重新圈选。",fg="#ffb887")
                self.render()
                return
            from .feedback_ui import annotation_shape
            self.feedback_draft=annotation_shape(gesture["tool"],gesture["points"])
            self.feedback_draft_frame=self.doc.active_frame
            self.feedback_panel.update_mark()
            self.render()
            self.status_label.config(text="已标记位置 · 点击“截图并复制”，再粘贴到 AI 对话框。",fg=GREEN)
            return
        try:
            op = self.gesture_op()
            revision = self.gesture["revision"]
            self.gesture = self.override = None
            self.selection_preview = None
            self.doc.apply(symmetric_ops(op, self.doc.width, self.doc.height, self.symmetry_mode()),
                           label="手绘 · " + self.tool, expected_revision=revision, source="手动")
            self.changed("手绘修改已记录，可撤销")
        except (PixelError, ValueError, tk.TclError) as exc:
            self.gesture = self.override = None
            self.render()
            self.status_label.config(text=str(exc), fg="#f19493")

    def pick(self, event):
        point = self.pixel_at(event)
        if point:
            color = hexcolor(self.doc.composite().getpixel(point))
            if color not in self.doc.palette:
                self.apply([{"op": "palette_add", "colors": [color]}], "取色加入调色板")
            if color in self.doc.palette:
                self.select_color(self.doc.palette.index(color))

    def change_zoom(self, direction, event=None):
        steps = [.125, .25, .5, .75, 1, 2, 3, 4, 6, 8, 10, 12, 16, 20, 24, 32]
        old = self.zoom
        if direction > 0:
            self.zoom = next((step for step in steps if step > old + 1e-8), steps[-1])
        else:
            self.zoom = next((step for step in reversed(steps) if step < old - 1e-8), min(old, steps[0]))
        if event:
            width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
            px = (event.x - self.origin[0]) / old
            py = (event.y - self.origin[1]) / old
            self.pan = [int(event.x - px * self.zoom - (width - self.doc.width * self.zoom) / 2),
                        int(event.y - py * self.zoom - (height - self.doc.height * self.zoom) / 2)]
        self.render()

    def wheel(self, event):
        self.change_zoom(1 if event.delta > 0 else -1, event)

    def pan_start(self, event):
        self.pan_anchor = (event.x, event.y, self.pan.copy())

    def pan_move(self, event):
        if hasattr(self, "pan_anchor"):
            x, y, initial = self.pan_anchor
            self.pan = [initial[0] + event.x - x, initial[1] + event.y - y]
            self.render()

    def select_frame(self, frame):
        self.stop_play()
        if frame != self.doc.active_frame:
            cleared=False
            if self.feedback_draft and self.feedback_panel.scope.get()=="当前帧" and frame!=getattr(self,"feedback_draft_frame",self.doc.active_frame):
                self.feedback_draft=None
                self.feedback_panel.update_mark()
                cleared=True
            self.apply([{"op": "select", "frame": frame}], "选择动画帧")
            if cleared:
                self.feedback_panel.notice.config(text="已切换帧，请在这一帧重新标记位置。",fg="#ffb887")

    def set_duration(self):
        value = simpledialog.askinteger("帧时长", "当前帧时长（毫秒，16–60000）：", parent=self.root,
                                        initialvalue=self.doc.durations[self.doc.active_frame], minvalue=16, maxvalue=60_000)
        if value:
            self.apply([{"op": "frame_set", "duration_ms": value}], "修改帧时长")

    def playback_delay(self, duration):
        return max(1, round(duration / self.playback_rate))

    def set_playback_speed(self, choice):
        rates = {f"{rate:g}×": rate for rate in (.25, .5, .75, 1, 1.25, 1.5, 2, 3, 4)}
        if choice not in rates:
            self.playback_speed.set(f"{self.playback_rate:g}×")
            return
        self.playback_rate = rates[choice]
        self.playback_speed.set(choice)
        if self.playback_job:
            self.root.after_cancel(self.playback_job)
            self.playback_job = None
        if self.playing:
            self.playback_job = self.root.after(self.playback_delay(self.doc.durations[self.play_frame]), self.play_tick)
        self.sync_service()
        self.status_label.config(text=f"预览速度 {choice} · 原始帧时长和导出速度保持不变", fg=MUTED)

    def toggle_play(self):
        if self.playing:
            self.pause_play()
        else:
            self.playing = True
            tag = self.tag_var.get() if self.tag_var.get() in self.doc.tags else None
            self.play_frames = self.doc.frame_indices(tag, playback=True)
            self.play_index = self.play_frames.index(self.doc.active_frame) if self.doc.active_frame in self.play_frames else 0
            self.play_frame = self.play_frames[self.play_index]
            self.play_button.config(text="Ⅱ 暂停")
            self.render()
            self.refresh_playhead(self.play_frame)
            self.playback_job = self.root.after(self.playback_delay(self.doc.durations[self.play_frame]), self.play_tick)

    def pause_play(self):
        frame = self.play_frame if self.playing else self.doc.active_frame
        self.stop_play()
        self.select_frame(frame)
        self.sync_service()

    def stop_animation(self):
        self.stop_play()
        tag = self.tag_var.get() if self.tag_var.get() in self.doc.tags else None
        self.select_frame(self.doc.frame_indices(tag, playback=True)[0])
        self.sync_service()

    def play_tick(self):
        if not self.playing:
            return
        self.play_index = (self.play_index + 1) % len(self.play_frames)
        self.play_frame = self.play_frames[self.play_index]
        self.render()
        self.frame_info.config(text=f"播放中 · {self.play_frame + 1} / {len(self.doc.durations)}")
        self.refresh_playhead(self.play_frame)
        self.playback_job = self.root.after(self.playback_delay(self.doc.durations[self.play_frame]), self.play_tick)

    def stop_play(self):
        if self.playback_job:
            self.root.after_cancel(self.playback_job)
            self.playback_job = None
        if self.playing:
            self.playing = False
            self.play_button.config(text="▶ 播放")
            self.render()
            self.refresh_frames()

    def undo(self):
        self.stop_play()
        if self.doc.undo():
            self.sync_service()
            self.service.restore_reference()
            self.changed("已撤销")

    def redo(self):
        self.stop_play()
        if self.doc.redo():
            self.sync_service()
            self.service.restore_reference()
            self.changed("已重做")

    def can_replace(self):
        material=getattr(self,'material_window',None)
        if material and material.dialog.winfo_exists() and material.draft_changed:
            messagebox.showinfo('材质预览尚未应用','请先在光照窗口应用当前调整，或点击“还原预览”，再切换工程。',parent=material.dialog)
            material.dialog.lift();return False
        if self.dirty:
            answer = messagebox.askyesnocancel("保存当前作品", "当前作品有未保存的修改，要先保存吗？", parent=self.root)
            if answer is None:
                return False
            if answer and not self.save():
                return False
        return True

    def replace_document(self, doc, path=None):
        self.stop_play()
        self.autosave()
        doc.revision = max(doc.revision, self.doc.revision + 1)
        self.doc = doc
        self.path = Path(path) if path else None
        self.saved_revision = doc.revision
        self.saved_fingerprint = doc.fingerprint()
        self.dirty = False
        self.gesture = self.override = None
        self.path_points = []
        self.selection_preview = None
        self.feedback_draft = self.feedback_focus = None
        self.sync_service()
        self.service.restore_reference()
        self.service.remember_path()
        self.refresh()
        self.fit()

    def open_dialog(self):
        if not self.can_replace():
            return
        path = filedialog.askopenfilename(parent=self.root, initialdir=ROOT / "projects",
                                          filetypes=[("像素工程 / PNG", "*.pixloom *.png"), ("所有文件", "*.*")])
        if path:
            try:
                if Path(path).suffix.lower() == ".png":
                    self.import_png(path)
                else:
                    self.replace_document(Document.open(path), path)
            except (OSError, ValueError, KeyError) as exc:
                messagebox.showerror("打开失败", user_error(exc), parent=self.root)

    def import_png(self, path):
        doc = self.service.import_png(path)
        self.replace_document(doc)

    def save(self):
        target = self.path
        if target is None:
            path = filedialog.asksaveasfilename(parent=self.root, initialdir=ROOT / "projects",
                                                initialfile=self.doc.name + ".pixloom", defaultextension=".pixloom",
                                                filetypes=[("Pixel Loom 工程", "*.pixloom")])
            if not path:
                return False
            target = Path(path)
        try:
            self.sync_service()
            self.service.save_project(target,overwrite=True)
            self.path = self.service.path
            self.saved_revision = self.doc.revision
            self.saved_fingerprint = self.doc.fingerprint()
            self.dirty = False
            self.sync_service()
            self.service.remember_path()
            self.refresh()
            self.status_label.config(text=f"已保存 · {self.path}", fg=GREEN)
            return True
        except (OSError,ValueError) as exc:
            messagebox.showerror("保存失败", user_error(exc), parent=self.root)
            return False

    def save_as(self):
        previous = self.path
        self.path = None
        if not self.save():
            self.path = previous
            self.sync_service()

    def connection_dialog(self):
        from .integration import configurations
        config = configurations()
        dialog = tk.Toplevel(self.root)
        dialog.title("MCP · Pixel Loom")
        dialog.configure(bg=PANEL)
        place_dialog(dialog, self.root, 820, 600)
        dialog.transient(self.root)
        frame = tk.Frame(dialog, bg=PANEL, padx=20, pady=18)
        frame.pack(fill="both", expand=True)
        self.label(frame, "本地 AI 服务已就绪", font=("Microsoft YaHei UI", 14, "bold")).pack(anchor="w")
        self.label(frame, "首次在客户端添加以下 MCP 配置；接入后 AI 读取 pixel_onboard 即可使用，无需在软件内开启。", MUTED,SMALL,wraplength=760).pack(anchor="w", pady=(6, 12))
        text = tk.Text(frame, bg=BG, fg=FG, wrap="word", relief="flat", padx=12, pady=12, font=("Consolas", 10))
        text.pack(fill="both", expand=True)
        lines = ["Codex config.toml", "", config["codex"], "Claude Desktop / other stdio hosts", "",
                 json.dumps(config["claude"], ensure_ascii=False, indent=2), "", "Start with pixel_onboard.",
                 "Read state -> validate -> edit -> inspect -> save -> export.", "", "Workspace: " + str(ROOT)]
        text.insert("end", "\n".join(lines))
        text.config(state="disabled")
        row = tk.Frame(frame, bg=PANEL)
        row.pack(fill="x", pady=(10, 0))
        def copy(value):
            self.root.clipboard_clear()
            self.root.clipboard_append(value)
            self.status_label.config(text="MCP 配置已复制", fg=GREEN)
        self.button(row, "复制 Codex 配置", lambda: copy(config["codex"])).pack(side="left")
        self.button(row, "复制 Claude 配置", lambda: copy(json.dumps(config["claude"], ensure_ascii=False, indent=2))).pack(side="left", padx=8)
        self.button(row, "关闭", dialog.destroy).pack(side="right")

    def activity_dialog(self):
        existing=getattr(self,"activity_window",None)
        if existing and existing.winfo_exists():
            existing.lift()
            return existing
        dialog=tk.Toplevel(self.root)
        self.activity_window=dialog
        dialog.title("协作记录 · Pixel Loom")
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        place_dialog(dialog,self.root,620,430)
        self.label(dialog,"AI 与手动修改共用同一份工程和撤销记录。",MUTED,SMALL).pack(anchor="w",padx=18,pady=16)
        self.events_widget=tk.Text(dialog,bg=BG,fg=FG,relief="flat",wrap="word",font=SMALL,padx=12,pady=12)
        self.events_widget.pack(fill="both",expand=True,padx=18,pady=(0,18))
        self.refresh_events()
        return dialog

    def _accept_service_document(self):
        self.doc = self.service.doc
        self.path = self.service.path
        self.saved_fingerprint = self.service.saved_fingerprint
        self.dirty = self.service.dirty

    def _reset_service_document_view(self, close_dialogs=False):
        self.gesture=self.override=None
        self.path_points=[]
        self.selection_preview=None
        self.feedback_draft=self.feedback_focus=None
        if close_dialogs:
            for name in ('quality_window','reference_window','material_window'):
                window=getattr(self,name,None)
                if window and window.dialog.winfo_exists():window.dialog.destroy()

    def dispatch(self, method, path, query, payload):
        self.sync_service()
        material=getattr(self,'material_window',None)
        replacing=method=='POST' and (path in ('/new','/open','/import','/redraw/begin') or
            path=='/generation' and payload.get('action')=='apply' or
            path=='/projects' and payload.get('action') in ('new','fork','switch','restore','use_version','remove','close'))
        if (replacing or method=='POST' and path=='/shutdown') and material and material.dialog.winfo_exists() and material.draft_changed:
            raise PixelError('Apply or restore the pending material preview before switching projects.',code='MATERIAL_DRAFT_PENDING')
        if method=='POST' and path=='/material' and payload.get('action') in ('apply','clear') and material and material.dialog.winfo_exists() and material.draft_changed and (
            payload.get('action')=='clear' or payload.get('preview_id')!=material.pending):
            raise PixelError('A different human material draft is pending; do not replace it.',code='MATERIAL_DRAFT_PENDING')
        if method=='POST' and path=='/material/present':
            self.service.materials.ticket(self.doc,payload.get('preview_id'))
            self.root.deiconify()
            self.root.lift()
            return self.material_dialog().present(payload['preview_id']), 'application/json; charset=utf-8'
        if method == "POST" and path == "/activate":
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            return {"ok": True, **self.service.state()}, "application/json; charset=utf-8"
        if method=="POST" and path=="/review/present":
            self.service.quality.ticket(payload["review_id"],self.doc)
            window=self.quality_dialog(payload["review_id"])
            self.root.deiconify()
            window.dialog.lift()
            return {"ok":True,"presented":True,"playing":window.playing,"review_id":payload["review_id"]},"application/json; charset=utf-8"
        read_only_preview = path in ("/task", "/art/board", "/validate", "/reference/preview", "/reference/cutout/preview", "/review/evidence", "/motion/check") or (
            path=='/material' and payload.get('action','status') in ('status','preview','export')) or (
            path=='/generation' and payload.get('action','request') in ('request','preview')) or (
            path == '/reference/cutout' and payload.get('action') == 'export') or (
            path == '/storage' and payload.get('action','status') in ('status','plan')) or (
            path == "/character" and payload.get("action", "status") in ("status", "save")) or (
            path=="/feedback" and payload.get("action") in ("list","inspect")) or (
            path=='/projects' and payload.get('action','list') in ('list','deleted','closed','versions','compare','version_preview'))
        view_only = path == "/command" and bool(payload.get("ops")) and all(
            op.get("op") in ("select", "selection_set") for op in payload["ops"])
        if method == "POST" and not read_only_preview:
            self.stop_play()
            self.sync_service()
        previous_identity=(self.doc.id,self.path)
        try:
            response = self.service.dispatch(method, path, query, payload)
        except (OSError, ValueError, RuntimeError):
            # A switch can succeed before persistence fails. Do not let the next
            # sync_service() silently restore the old GUI document over that work.
            if (self.service.doc.id,self.service.path)!=previous_identity:
                self._accept_service_document()
                self._reset_service_document_view(close_dialogs=True)
                self.refresh()
                self.fit()
                self.status_label.config(text='MCP · 文档已切换，后续操作失败；请检查并保存当前作品',fg=MUTED)
            raise
        self._accept_service_document()
        switched=method=='POST' and (path in ('/new','/open','/import','/redraw/begin') or
                 path=='/generation' and payload.get('action')=='apply' and (self.doc.id,self.path)!=previous_identity or
                 path == '/projects' and ((self.doc.id,self.path)!=previous_identity or payload.get('action')=='use_version'))
        if switched:
            self._reset_service_document_view(close_dialogs=path in ('/projects','/generation'))
        if method == "POST" and not read_only_preview:
            if view_only:
                self.refresh_view()
            else:
                self.refresh()
            self.status_label.config(text="MCP · " + payload.get("label", path.lstrip("/")), fg=GREEN)
            if switched or any(op.get("op") in ("canvas_resize", "sprite_scale") for op in payload.get("ops", [])):
                self.fit()
        if self.service.closing:
            self.root.after(100, self.close)
        return response

    def pump(self):
        self.pump_job=None
        self.bridge.pump(self.dispatch)
        self.pump_job=self.root.after(40, self.pump)

    def close(self):
        if not self.can_replace():
            return
        self.save_ui_layout()
        if self.updates is not None:
            self.updates.close()
        self.stop_play()
        for name in ('fit_job','pump_job','autosave_job','welcome_job','project_reveal_job','frame_reveal_job'):
            job=getattr(self,name,None)
            if job:
                try:self.root.after_cancel(job)
                except tk.TclError:pass
            setattr(self,name,None)
        self.autosave()
        self.bridge.close()
        self.root.destroy()


def run_window(project=None):
    import ctypes
    import sys
    import traceback

    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    try:
        editor = Editor(root, project)
        root.mainloop()
    except Exception:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        (RUNTIME / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        messagebox.showerror("Pixel Loom 启动失败", traceback.format_exc(), parent=root)
        raise


def main(project=None):
    import time
    from .lifecycle import live_client, startup_lock, StartupBusy, require_editor_version

    def activate(client):
        state = client.request("/state")
        require_editor_version(state.get("app_version"))
        if project and str(Path(project).resolve()) != state.get("project_path"):
            client.mutate("/open", {"path": str(Path(project).resolve())})
        client.request("/activate", {})

    try:
        existing = live_client()
        if existing:
            activate(existing)
            return
        try:
            # A second manual launch can race the first before its bridge binds.
            with startup_lock(timeout=.1, lock_name="editor.lock"):
                existing = live_client()
                if existing:
                    activate(existing)
                    return
                run_window(project)
                return
        except StartupBusy:
            for _ in range(30):
                existing = live_client()
                if existing:
                    activate(existing)
                    return
                time.sleep(.1)
            raise RuntimeError("The workbench is already starting. Please try again shortly.")
    except (RuntimeError, OSError, ValueError) as exc:
        messagebox.showerror("Pixel Loom", str(exc))


if __name__ == "__main__":
    main()
