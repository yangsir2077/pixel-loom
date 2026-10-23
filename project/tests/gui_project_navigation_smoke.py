"""Many real project tabs remain reachable after switch, wheel and resize."""
import json
import os
from pathlib import Path
import tempfile


def main():
    with tempfile.TemporaryDirectory(prefix='pixel-loom-tab-navigation-') as folder:
        os.environ['PIXEL_LOOM_HOME']=str(Path(folder)/'data')
        os.environ['PIXEL_LOOM_WORKSPACE']=str(Path(folder)/'work')
        import tkinter as tk
        from pixel_workbench.app import Editor
        from pixel_workbench.model import Document
        root=tk.Tk()
        root.withdraw()
        editor=Editor(root)
        root.after_cancel(editor.welcome_job)
        editor.welcome_job=None
        errors=[]
        root.report_callback_exception=lambda *args:errors.append(str(args[1]))
        try:
            entries=[]
            for i in range(28):
                path=Path(folder)/f'project-{i}.pixloom'
                doc=Document(16,16,f'Project {i+1:02d} - a longer animation name')
                doc.save(path)
                entries.append(editor.service.projects.register(path,doc))
            editor.refresh_projects()
            root.deiconify()
            root.geometry('1160x800+30+30')
            root.update()
            assert editor.project_scrollbar.winfo_manager()
            assert editor.project_tabs_canvas.xview()[1]<1
            editor.project_scroll_right.invoke()
            root.update()
            assert editor.project_tabs_canvas.xview()[0]>0
            assert editor.project_action('switch',project_id=entries[-1]['id'])
            root.update()
            canvas=editor.project_tabs_canvas
            def active_visible():
                button=editor.project_tab_buttons[editor.project_active_id]
                return (canvas.canvasx(0)-1<=button.winfo_x() and
                        button.winfo_x()+button.winfo_width()<=canvas.canvasx(canvas.winfo_width())+1)
            assert active_visible(),'Last project clipped after switch'
            assert editor.project_scroll_right.cget('state')=='disabled'
            doc_before=editor.doc.to_dict()
            last=editor.project_tab_buttons[entries[-1]['id']]
            before=canvas.xview()[0]
            last.event_generate('<MouseWheel>',delta=120)
            root.update()
            assert canvas.xview()[0]<before,'Wheel over child tab was ignored'
            editor.project_scroll_left.invoke()
            root.update()
            assert canvas.xview()[0]<before
            # CI desktops can clamp 1160 and 1320 to the SAME monitor width,
            # producing no Configure event. Exercise real viewport changes
            # inside the measured window bounds rather than assuming its size.
            actual_width=min(root.winfo_width(),root.maxsize()[0])
            minimum=root.minsize()
            root.minsize(min(minimum[0],actual_width-200),minimum[1])
            for width in (actual_width-120,actual_width-40,actual_width-160,actual_width):
                previous_viewport=canvas.winfo_width()
                root.geometry(f'{width}x800+30+30')
                # Native window-manager resize messages need a real event turn;
                # one update() can return before those messages arrive on Windows.
                root.after(120,root.quit)
                root.mainloop()
                root.update()
                assert canvas.winfo_width()!=previous_viewport,('Viewport did not resize',width,canvas.winfo_width())
                button=editor.project_tab_buttons[editor.project_active_id]
                assert active_visible(),('Active project clipped after resize',width,canvas.winfo_width(),
                    canvas.xview(),button.winfo_x(),button.winfo_width())
            editor.project_all_button.invoke()
            root.update()
            manager=editor.project_manager
            tree=manager.trees['open']
            assert len(tree.get_children())==28
            tree.selection_set(entries[0]['id'])
            manager.open_selected()
            root.update()
            assert editor.doc.name.startswith('Project 01')
            assert active_visible() and canvas.xview()[0]==0
            assert editor.project_scroll_left.cget('state')=='disabled'
            assert doc_before['name'].startswith('Project 28')
            assert not errors,errors
            print(json.dumps({'ok':True,'projects':28,'checks':[
                'visible overflow scrollbar and arrows','wheel over actual child tabs',
                'last active tab fully visible','resize reveals current tab',
                'complete scrollable project list opens first and last projects',
                'edge arrow states','no callback errors']}))
        finally:
            editor.saved_fingerprint=editor.doc.fingerprint()
            editor.dirty=False
            editor.close()


if __name__=='__main__':main()
