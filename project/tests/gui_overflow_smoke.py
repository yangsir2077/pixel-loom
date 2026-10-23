"""Native overflow regressions; all artwork and history use a temporary workspace."""
import json
import os
from pathlib import Path
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix="pixel-loom-overflow-") as folder:
        base = Path(folder)
        os.environ["PIXEL_LOOM_HOME"] = str(base / "data")
        os.environ["PIXEL_LOOM_WORKSPACE"] = str(base / "work")
        import tkinter as tk
        from pixel_workbench.app import Editor
        from pixel_workbench.model import Document

        root = tk.Tk()
        root.withdraw()
        editor = Editor(root)
        root.after_cancel(editor.welcome_job)
        editor.welcome_job = None
        editor.updates.preferences["check_on_startup"] = False
        errors = []
        root.report_callback_exception = lambda *args: errors.append(str(args[1]))

        def wait(ms):
            root.after(ms, root.quit)
            root.mainloop()
            root.update()

        def fresh():
            editor.replace_document(Document(16, 16, "Overflow fixture"))
            editor.set_workspace_mode("manual")
            editor.control_notebook.select(editor.manual_tab)
            root.update()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        try:
            fresh()
            root.deiconify()
            root.geometry("1160x800+20+20")
            for colors in ([f"#{i:02x}1020ff" for i in range(256)],
                           [f"#1020{i:02x}ff" for i in range(256)]):
                editor.apply([{"op": "palette_set", "colors": colors}], "large palette")
                editor.control_notebook.select(editor.palette_page)
                root.update()
                dock = editor.palette_frame.master.master
                dock.yview_moveto(0)
                before, zoom, revision = dock.yview(), editor.zoom, editor.doc.revision
                editor.palette_buttons[0].event_generate("<MouseWheel>", delta=-120)
                root.update()
                assert dock.yview()[0] > before[0], "Wheel over a new color swatch was swallowed"
                assert editor.zoom == zoom and editor.doc.revision == revision

            fresh()
            editor.apply([{"op": "layer_set", "name": "A very long editable layer name " * 3}], "long layer")
            root.update()
            listing = editor.layers_widget
            assert listing.xview()[1] < 1 and listing.horizontal_scrollbar.winfo_ismapped()
            listing.event_generate("<Shift-MouseWheel>", delta=-120)
            root.update()
            horizontal = listing.xview()[0]
            assert horizontal > 0
            editor.apply([{"op": "pixel", "x": 0, "y": 0, "color": 7}], "retain layer name scroll")
            root.update()
            assert listing.xview()[0] == horizontal

            fresh()
            editor.apply([{"op": "frame_add", "blank": True} for _ in range(63)] +
                         [{"op": "select", "frame": 0}], "long timeline")
            root.update()
            editor.frame_canvas.xview_moveto(.65)
            previous = editor.frame_canvas.xview()[0]
            editor.apply([{"op": "pixel", "x": 0, "y": 0, "color": 7}], "edit while browsing frames")
            root.update()
            assert abs(editor.frame_canvas.xview()[0] - previous) < .001
            before = editor.frame_canvas.xview()[0]
            editor.frame_buttons[42].event_generate("<MouseWheel>", delta=120)
            root.update()
            assert editor.frame_canvas.xview()[0] < before
            editor.apply([{"op": "select", "frame": 63}], "select final frame")
            root.update()

            def final_visible():
                button = editor.frame_buttons[-1]
                canvas = editor.frame_canvas
                return (canvas.canvasx(0) - 1 <= button.winfo_x() and
                        button.winfo_x() + button.winfo_width() <= canvas.canvasx(canvas.winfo_width()) + 1)

            assert final_visible(), (editor.frame_buttons[-1].winfo_x(), editor.frame_buttons[-1].winfo_width(),
                editor.frame_canvas.canvasx(0), editor.frame_canvas.winfo_width(), editor.frame_canvas.xview(),
                editor.frames_widget.winfo_reqwidth())
            minimum = root.minsize()
            root.minsize(900, 700)
            root.geometry(f"{max(900, root.winfo_width()-120)}x800+20+20")
            wait(160)
            assert final_visible(), "Resizing clipped the active final frame"
            root.minsize(*minimum)

            fresh()
            editor.apply([{"op": "region_define", "name": f"part-{i:02d}", "rect": [0, 0, 4, 4]}
                          for i in range(16)], "many named regions")
            quality = editor.quality_dialog()
            quality.toggle_settings()
            root.update()
            regions = quality.regions
            dock = regions.master.master.master
            regions.yview_moveto(0)
            outer, zoom, revision = dock.yview(), editor.zoom, editor.doc.revision
            regions.event_generate("<MouseWheel>", delta=-120)
            root.update()
            assert regions.yview()[0] > 0 and dock.yview() == outer
            assert editor.zoom == zoom and editor.doc.revision == revision
            quality.criteria.insert("end", "\n".join("criterion " + str(i) for i in range(30)))
            quality.criteria.yview_moveto(0)
            quality.criteria.event_generate("<MouseWheel>", delta=-120)
            root.update()
            assert quality.criteria.yview()[0] > 0 and dock.yview() == outer
            quality.dialog.destroy()
            character = editor.character_dialog()
            root.update()
            character.parts.yview_moveto(1)
            assert character.parts.vertical_scrollbar.winfo_ismapped()
            assert character.parts.bbox(character.parts.size()-1) is not None
            character.close()

            before = editor.doc.to_dict()
            editor.dispatch("POST", "/task", {}, dict(action="plan", task="text_static",
                brief="\n".join("progress line " + str(i) for i in range(30)), expected_task_revision=0,
                expected_document_id=editor.doc.id, expected_revision=editor.doc.revision))
            progress = editor.workflow_dialog()
            root.update()
            summary = progress.workflow_summary
            summary.yview_moveto(.5)
            first = summary.index("@0,0")
            summary.tag_add("sel", "15.0", "15.5")
            wait(1350)
            assert summary.index("@0,0") == first and summary.tag_ranges("sel")
            editor.dispatch("POST", "/task", {}, dict(action="update", next_action="new progress",
                expected_task_revision=1, expected_document_id=editor.doc.id, expected_revision=editor.doc.revision))
            wait(1350)
            assert summary.index("@0,0") == first and "new progress" in summary.get("1.0", "end")
            assert editor.doc.to_dict() == before
            progress.destroy()

            fresh()
            path = base / "active.pixloom"
            editor.dispatch("POST", "/save", {}, dict(path=str(path), expected_document_id=editor.doc.id,
                expected_revision=editor.doc.revision))
            for i in range(12):
                editor.apply([{"op": "pixel", "x": i, "y": 0, "color": 7}], "version " + str(i))
                editor.service.checkpoint_current()
            history = editor.project_history_dialog()
            root.update()
            # Native transient mapping can arrive after Tk's idle layout pass on Windows.
            for _ in range(20):
                if history.dialog.winfo_viewable():break
                wait(25)
            assert history.listing.size() > 5 and history.listing.vertical_scrollbar.winfo_ismapped(), {
                'versions':history.listing.size(),'scrollbar_mapped':history.listing.vertical_scrollbar.winfo_ismapped(),
                'list_height':history.listing.winfo_height(),'window_viewable':history.dialog.winfo_viewable(),
                'parent_state':root.state(),'parent_viewable':root.winfo_viewable()}
            history.listing.yview_moveto(1)
            assert history.listing.bbox(history.listing.size()-1) is not None
            history.dialog.destroy()

            for i in range(28):
                path = base / f"project-{i}.pixloom"
                doc = Document(16, 16, f"Fixture {i}")
                doc.save(path)
                editor.service.projects.register(path, doc)
            manager = editor.manage_projects_dialog()
            root.update()
            tree = manager.trees['open']
            tree.yview_moveto(.5)
            before = tree.yview()[0]
            changed = Document.open(base / "project-0.pixloom")
            changed.apply([{"op": "rename", "name": "Renamed fixture"}])
            changed.save(base / "project-0.pixloom")
            editor.service.projects.register(base / "project-0.pixloom", changed)
            manager.refresh()
            root.update()
            assert abs(tree.yview()[0]-before) < .02
            manager.dialog.destroy()

            editor.command_palette()
            root.update()
            command = next(w for w in root.winfo_children() if isinstance(w, tk.Toplevel) and
                           w.title().startswith("命令中心"))
            listing = next(w for w in descendants(command) if isinstance(w, tk.Listbox))
            listing.yview_moveto(1)
            assert listing.vertical_scrollbar.winfo_ismapped() and listing.bbox(listing.size()-1) is not None
            command.destroy()
            assert not errors, errors
            print(json.dumps({"ok": True, "checks": ["256 color swatches including rebuilt widgets",
                "long layer names and retained horizontal scroll", "64 frame browsing preserved during edits",
                "wheel over frame buttons", "final frame revealed after selection and resize",
                "nested quality regions and criteria scroll independently", "character parts reachable",
                "progress poll preserves scroll/selection without rewriting unchanged text",
                "updated progress retains reading position without artwork changes",
                "history scrollbar reaches older versions", "project manager refresh preserves browsing",
                "command list reaches final command", "no callback errors"]}))
        finally:
            editor.saved_fingerprint = editor.doc.fingerprint()
            editor.dirty = False
            editor.close()


if __name__ == "__main__":
    main()
