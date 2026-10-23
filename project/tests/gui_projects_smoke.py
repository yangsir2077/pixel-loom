"""Project switching, per-project versions and read-only dual animation playback."""
import json
import os
from pathlib import Path
import tempfile
from unittest.mock import patch


def main():
    with tempfile.TemporaryDirectory(prefix='pixel-loom-project-gui-') as folder:
        os.environ['PIXEL_LOOM_HOME']=str(Path(folder)/'data')
        os.environ['PIXEL_LOOM_WORKSPACE']=str(Path(folder)/'work')
        import tkinter as tk
        from pixel_workbench.app import Editor
        from pixel_workbench.model import Document
        root=tk.Tk()
        root.withdraw()
        editor=Editor(root)
        assert editor.path is None and all(not cel.getbbox() for layer in editor.doc.layers for cel in layer.cels)
        errors=[]
        root.report_callback_exception=lambda *args:errors.append(str(args[1]))
        try:
            editor.replace_document(Document(24,32,'Idle'))
            editor.apply([{'op':'pixel','x':4,'y':4,'color':7},{'op':'frame_add'}],'idle fixture')
            first=editor.project_action('fork',name='Walk')['projects'][0]
            second=editor.service.projects.by_path(editor.path)
            editor.apply([{'op':'pixel','x':5,'y':4,'color':8}],'walk fixture')
            assert editor.project_action('switch',project_id=first['id'])
            assert editor.doc.name=='Idle' and not editor.dirty
            assert editor.project_action('switch',project_id=second['id'])
            assert editor.doc.name=='Walk' and editor.doc.composite().getpixel((5,4))[3]
            before=editor.doc.to_dict()
            compare=editor.compare_projects_dialog([first['id'],second['id']])
            root.update()
            assert len(compare.documents)==2
            compare.toggle()
            root.update()
            assert compare.playing and compare.job
            compare.seek(150)
            assert not compare.playing and compare.elapsed==150
            compare.reload()
            assert editor.doc.to_dict()==before
            compare.dialog.destroy()
            editor.apply([{'op':'pixel','x':6,'y':4,'color':9}],'new saved version')
            history=editor.project_history_dialog()
            root.update()
            assert history.versions
            history.listing.selection_clear(0,'end')
            history.listing.selection_set(len(history.versions)-1)
            history.show()
            history.toggle()
            root.update()
            assert history.playing and history.job
            history.step(1)
            assert not history.playing
            source=editor.path
            active_id=editor.doc.id
            selected=history.use()
            assert editor.path==source and editor.doc.id==active_id
            assert len(editor.service.projects.entries)==2
            assert selected and selected.versions
            selected.dialog.destroy()
            history=editor.project_history_dialog()
            history.listing.selection_clear(0,'end')
            history.listing.selection_set(0)
            source=editor.path
            history.restore()
            assert editor.path!=source and source.exists()
            assert len(editor.service.projects.entries)==3
            manager=editor.manage_projects_dialog()
            root.update()
            assert len(manager.trees['open'].get_children())==3
            external=Path(folder)/'external.pixloom'
            Document(16,16,'Added project').save(external)
            active_id=editor.doc.id
            with patch('pixel_workbench.ui.filedialog.askopenfilenames',return_value=(str(external),)):
                assert editor.add_existing_projects()==1
            assert editor.doc.id==active_id
            added=editor.service.projects.by_path(external)
            manager.trees['open'].selection_set([first['id'],added['id']])
            root.update()
            with patch('pixel_workbench.ui.messagebox.askyesno',return_value=False):
                assert manager.remove_selected() is None
            assert len(editor.service.projects.listing())==4
            with patch('pixel_workbench.ui.messagebox.askyesno',return_value=True):
                assert manager.remove_selected()
            assert len(editor.service.projects.listing())==2 and external.exists()
            assert len(manager.trees['deleted'].get_children())==2
            manager.select_tab('deleted')
            manager.trees['deleted'].selection_set([first['id'],added['id']])
            assert manager.restore_selected()
            assert len(editor.service.projects.listing())==4
            manager.select_tab('open')
            root.update()
            tab=editor.project_tab_buttons[first['id']]
            assert tab.close_label.cget('text')=='✕'
            assert tab.name_label.bind('<Button-1>') and tab.close_label.bind('<Button-1>')
            closed_file=Path(first['path']).read_bytes()
            assert editor.close_projects([first['id']])
            root.update()
            assert len(editor.service.projects.listing())==3
            assert Path(first['path']).read_bytes()==closed_file
            assert [entry['id'] for entry in editor.service.projects.listing(closed=True)]==[first['id']]
            assert first['id'] not in editor.project_tab_buttons
            manager.refresh()
            manager.select_tab('closed')
            root.update()
            assert len(manager.trees['closed'].get_children())==1
            manager.trees['closed'].selection_set([first['id']])
            assert manager.reopen_selected()
            root.update()
            assert len(editor.service.projects.listing())==4
            assert first['id'] in editor.project_tab_buttons
            assert not editor.service.projects.listing(closed=True)
            missing=Path(added['path'])
            moved=missing.with_suffix('.moved')
            missing.rename(moved)
            editor.refresh_projects()
            root.update()
            unavailable=editor.project_tab_buttons[added['id']]
            assert not unavailable.name_label.bind('<Button-1>')
            assert unavailable.close_label.bind('<Button-1>')
            assert editor.close_projects([added['id']])
            assert added['id'] not in editor.project_tab_buttons and moved.is_file()
            moved.rename(missing)
            assert editor.project_action('reopen',project_id=added['id'])
            manager.refresh()
            manager.select_tab('open')
            manager.trees['open'].selection_set(manager.trees['open'].get_children())
            with patch('pixel_workbench.ui.messagebox.askyesno',return_value=True):
                assert manager.remove_selected()
            assert editor.path is None and not editor.service.projects.listing()
            with patch('pixel_workbench.ui.messagebox.showinfo') as empty_history:
                assert editor.project_history_dialog() is None
                empty_history.assert_called_once()
            manager.dialog.destroy()
            editor.close()
            root=tk.Tk()
            root.withdraw()
            root.report_callback_exception=lambda *args:errors.append(str(args[1]))
            editor=Editor(root)
            root.update()
            assert editor.path is None and not editor.service.projects.listing()
            manager=editor.manage_projects_dialog(deleted=True)
            root.update()
            assert manager.is_deleted() and len(manager.trees['deleted'].get_children())==4
            manager.dialog.destroy()
            assert not errors,errors
            print(json.dumps({'ok':True,'checks':['numbered project shelf','auto-save outgoing project',
                'switch between intact animations','independent timed comparison playback','read-only snapshots',
                'pre-save versions','restore as new project','manager adds existing files without switching',
                'cancel/remove multiple projects','restore same project identities','remove all and restart stays empty',
                'no callback errors']}))
        finally:
            editor.saved_fingerprint=editor.doc.fingerprint()
            editor.dirty=False
            editor.close()


if __name__=='__main__':main()
