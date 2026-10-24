"""Real Tk lighting controls, painting, playback and shared undo; isolated data."""
import base64
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace


def main(artifacts=None):
    with tempfile.TemporaryDirectory(prefix='pixel-loom-material-ui-') as folder:
        root_path=Path(folder)
        os.environ['PIXEL_LOOM_HOME']=str(root_path/'data')
        os.environ['PIXEL_LOOM_WORKSPACE']=str(root_path/'work')
        import tkinter as tk
        from PIL import Image
        from pixel_workbench.app import Editor
        from pixel_workbench.materials import decode
        from pixel_workbench.model import PixelError
        root=tk.Tk();editor=Editor(root);errors=[]
        root.report_callback_exception=lambda *args:errors.append(str(args[1]))
        if editor.welcome_job:root.after_cancel(editor.welcome_job);editor.welcome_job=None
        if editor.updates:editor.updates.close()
        editor.doc.apply([{'op':'rect','x':8,'y':8,'width':16,'height':20,'color':7},
                          {'op':'frame_set','frame':0,'duration_ms':40},{'op':'frame_add','duration_ms':50},
                          {'op':'tag_set','name':'once','start':0,'end':1},
                          {'op':'quality_policy','data':{'loop':False}}])
        editor.refresh();editor.sync_service()
        before=editor.doc.composite().tobytes();palette=editor.doc.palette.copy();undo=len(editor.doc.undo_stack)
        window=editor.material_dialog();root.update();window.redraw()
        assert editor.material_dialog() is window
        first=window.pending
        root.iconify();root.update()
        shown,_=editor.dispatch('POST','/material/present',{},dict(preview_id=first))
        root.update()
        assert shown['presented'] is True
        assert root.state()!='iconic'
        assert editor.doc.composite().tobytes()==before and len(editor.doc.undo_stack)==undo
        window.preview(normal_source={'kind':'silhouette','bevel':2,'strength':4})
        assert window.pending and editor.doc.material is None
        pending=window.pending
        not_shown,_=editor.dispatch('POST','/material/present',{},dict(preview_id=pending))
        assert not not_shown['presented'] and window.pending==pending
        window.view.set('法线笔刷');window.preview();root.update();window.redraw()
        x,y,ratio=window.transforms[0]
        event=SimpleNamespace(x=round(x+16*ratio),y=round(y+16*ratio))
        window.direction.set('向左');window.pointer_down(event,0);window.pointer_up(event,0)
        try:editor.dispatch('POST','/new',{},dict(width=12,height=12,expected_document_id=editor.doc.id,expected_revision=editor.doc.revision))
        except PixelError as error:assert error.code=='MATERIAL_DRAFT_PENDING'
        else:raise AssertionError('Pending normal painting must not be discarded by project replacement')
        try:editor.dispatch('POST','/shutdown',{},dict(expected_document_id=editor.doc.id,expected_revision=editor.doc.revision))
        except PixelError as error:assert error.code=='MATERIAL_DRAFT_PENDING'
        else:raise AssertionError('Pending normal painting must not be discarded by shutdown')
        ticket=editor.service.materials.ticket(editor.doc,window.pending)
        maps=ticket['material']['normal']
        painted=decode(maps[0 if len(maps)==1 else window.frame.get()],(48,48))
        assert painted.getpixel((16,16))[0]<100
        assert window.apply()
        assert editor.doc.material is not None and editor.doc.composite().tobytes()==before
        window.history('undo');assert editor.doc.material is None
        window.history('redo');assert editor.doc.material is not None
        assert editor.doc.palette==palette
        window.view.set('光照对照');window.preview();root.update();window.redraw()
        x,y,ratio=window.transforms[1]
        event=SimpleNamespace(x=round(x+32*ratio),y=round(y+12*ratio))
        window.pointer_down(event,1);window.pointer_up(event,1);window.preview()
        assert window.values['light_x'].get()>.6
        assert editor.doc.composite().tobytes()==before
        path=root_path/'lighting.png'
        assert window.export_to(path)
        assert Image.open(path).size==(48,48)
        window.reset_preview();window.tag.set('once');window.toggle_play()
        root.after(450,root.quit);root.mainloop()
        assert not window.playing and window.frame.get()==1
        if artifacts:
            target=Path(artifacts);target.mkdir(parents=True,exist_ok=True)
            editor.doc.save(target/'gui-material.pixloom')
            window.export_to(target/'gui-lighting.png')
        window.dialog.destroy();root.update()
        assert not errors,errors
        editor.dirty=False;editor.saved_fingerprint=editor.doc.fingerprint();editor.close()
        print(json.dumps({'ok':True,'checks':['optional single window','read-only preview','normal direction brush','apply/undo/redo',
             'unchanged source pixels/palette','drag light','render export','one-shot playback stops','clean close']}))


if __name__=='__main__':main()
