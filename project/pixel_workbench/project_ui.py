"""On-demand project comparison and saved-version browsers."""
from __future__ import annotations

import time
from datetime import datetime
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from .model import Document
from .projects import frame_at
from .ui import BG, PANEL, FIELD, FG, MUTED, SMALL, place_dialog, scrollable_widget


class ProjectManagerDialog:
    scopes=(('open','项目'),('deleted','已删除'),('closed','已收起'))

    def __init__(self,editor,scope='open'):
        self.editor=editor
        self.dialog=d=tk.Toplevel(editor.root)
        d.title('项目管理 · 添加 / 删除 / 恢复')
        d.configure(bg=PANEL)
        d.transient(editor.root)
        place_dialog(d,editor.root,900,610)
        d.minsize(720,500)
        header=tk.Frame(d,bg=PANEL,padx=18,pady=16)
        header.pack(fill='x')
        editor.label(header,'我的项目',font=('Microsoft YaHei UI',15,'bold')).pack(side='left')
        editor.button(header,'添加已有项目…',editor.add_existing_projects,True,font=SMALL).pack(side='right')
        editor.label(d,'项目可自由添加或删除。删除后保留工程文件与历史版本，可在“已删除”中恢复；关闭标签页只是从项目栏收起，工程与版本记录完全不变。',MUTED,SMALL).pack(anchor='w',padx=18,pady=(0,12))
        footer=tk.Frame(d,bg=PANEL,padx=18,pady=12)
        footer.pack(side='bottom',fill='x')
        editor.button(footer,'关闭',d.destroy,font=SMALL).pack(side='right')
        self.open_button=editor.button(footer,'打开所选',self.open_selected,font=SMALL)
        self.open_button.pack(side='left')
        self.remove_button=editor.button(footer,'删除所选',self.remove_selected,font=SMALL)
        self.remove_button.pack(side='left',padx=8)
        self.restore_button=editor.button(footer,'恢复所选',self.restore_selected,True,font=SMALL)
        self.restore_button.pack(side='left')
        self.reopen_button=editor.button(footer,'重新打开所选',self.reopen_selected,True,font=SMALL)
        self.reopen_button.pack(side='left',padx=8)
        self.purge_button=editor.button(footer,'彻底清理所选',self.purge_selected,font=SMALL)
        self.purge_button.pack(side='left',padx=8)
        self.path_label=editor.label(d,'',MUTED,SMALL,wraplength=840,justify='left')
        self.path_label.pack(side='bottom',fill='x',padx=18,pady=(8,0))
        self.notebook=ttk.Notebook(d)
        self.notebook.pack(fill='both',expand=True,padx=18)
        style=ttk.Style(d)
        style.configure('Projects.Treeview',background=BG,fieldbackground=BG,foreground=FG,rowheight=30,font=SMALL,borderwidth=0)
        style.configure('Projects.Treeview.Heading',background=FIELD,foreground=FG,font=SMALL)
        style.map('Projects.Treeview',background=[('selected','#354b70')],foreground=[('selected',FG)])
        self.trees={}
        for name,title in self.scopes:
            page=tk.Frame(self.notebook,bg=PANEL)
            self.notebook.add(page,text=title)
            tree=ttk.Treeview(page,columns=('number','name','frames','status'),show='headings',selectmode='extended',style='Projects.Treeview')
            for key,text,width in [('number','编号',65),('name','项目名称',390),('frames','画布 / 帧数',150),('status','状态',125)]:
                tree.heading(key,text=text)
                tree.column(key,width=width,minwidth=50,stretch=key=='name')
            scroll=ttk.Scrollbar(page,command=tree.yview)
            scroll.pack(side='right',fill='y')
            tree.configure(yscrollcommand=scroll.set)
            tree.pack(fill='both',expand=True)
            tree.bind('<<TreeviewSelect>>',lambda event:self.update_selection())
            tree.bind('<Double-Button-1>',lambda event:self.open_selected())
            self.trees[name]=tree
        self.notebook.bind('<<NotebookTabChanged>>',lambda event:self.update_selection())
        self.select_tab(scope)
        self.refresh()
        self.poll_job=d.after(1000,self.poll)
        d.bind('<Destroy>',self.cleanup,add='+')

    def select_tab(self,scope):
        names=[name for name,_ in self.scopes]
        self.notebook.select(names.index(scope) if scope in names else 0)

    def current_scope(self):
        return [name for name,_ in self.scopes][self.notebook.index(self.notebook.select())]

    def is_deleted(self):
        return self.current_scope()=='deleted'

    def selected_ids(self):
        return list(self.trees[self.current_scope()].selection())

    def refresh(self):
        for name,tree in self.trees.items():
            selected=tree.selection()
            entries=self.editor.service.projects.listing(self.editor.path,deleted=name=='deleted',closed=name=='closed')
            signature=tuple((e['id'],e['name'],e['frames'],e['width'],e['height'],e['active'],e['available']) for e in entries)
            if getattr(tree,'project_signature',None)==signature:continue
            old_rows=tree.get_children()
            top_index=min(len(old_rows)-1,int(tree.yview()[0]*len(old_rows))) if old_rows else None
            top_id=old_rows[top_index] if top_index is not None else None
            tree.project_signature=signature
            tree.delete(*tree.get_children())
            for entry in entries:
                status=('文件已移动' if not entry['available'] else '可恢复' if name=='deleted'
                        else '已收起' if name=='closed' else '当前打开' if entry['active'] else '已保存')
                tree.insert('','end',iid=entry['id'],values=(entry['number'],entry['name'],f"{entry['width']}×{entry['height']} · {entry['frames']}帧",status))
            kept=[key for key in selected if tree.exists(key)]
            if kept:tree.selection_set(kept)
            if top_id and tree.exists(top_id):
                tree.yview_moveto(tree.index(top_id)/max(1,len(entries)))
        self.update_selection()

    def update_selection(self):
        scope=self.current_scope()
        selected=self.selected_ids()
        self.remove_button.config(state='normal' if selected and scope=='open' else 'disabled')
        self.restore_button.config(state='normal' if selected and scope=='deleted' else 'disabled')
        self.reopen_button.config(state='normal' if selected and scope=='closed' else 'disabled')
        self.purge_button.config(state='normal' if selected and scope=='deleted' else 'disabled')
        self.open_button.config(state='normal' if len(selected)==1 and scope=='open' else 'disabled')
        if selected:
            entry=self.editor.service.projects.get(selected[0],include_deleted=True)
            self.path_label.config(text=entry['path']+(f'\n已选择 {len(selected)} 个项目' if len(selected)>1 else ''))
        else:self.path_label.config(text='按 Ctrl / Shift 可多选项目。')

    def open_selected(self):
        selected=self.selected_ids()
        if len(selected)==1 and self.current_scope()=='open':self.editor.project_action('switch',project_id=selected[0])

    def remove_selected(self):
        if self.selected_ids() and self.current_scope()=='open':return self.editor.delete_projects(self.selected_ids())

    def restore_selected(self):
        if self.selected_ids() and self.current_scope()=='deleted':return self.editor.project_action('undelete',project_ids=self.selected_ids())

    def reopen_selected(self):
        if self.selected_ids() and self.current_scope()=='closed':return self.editor.project_action('reopen',project_ids=self.selected_ids())

    def purge_selected(self):
        if self.selected_ids() and self.current_scope()=='deleted':
            return self.editor.storage_dialog({'targets':['deleted_projects'],
                'deleted_project_ids':self.selected_ids(),'older_than_days':0})

    def poll(self):
        self.poll_job=None
        if self.dialog.winfo_exists():
            self.refresh()
            self.poll_job=self.dialog.after(1000,self.poll)

    def cleanup(self,event):
        if event.widget is self.dialog and self.poll_job:
            self.dialog.after_cancel(self.poll_job)
            self.poll_job=None


class ComparisonDialog:
    def __init__(self, editor, project_ids=None):
        self.editor=editor
        self.dialog=d=tk.Toplevel(editor.root)
        d.title('并排对照 · 独立项目 / 同时播放')
        d.configure(bg=BG)
        d.transient(editor.root)
        place_dialog(d,editor.root,1120,740)
        d.minsize(850,560)
        self.job=None
        self.playing=False
        self.elapsed=0
        self.started=0
        self.documents=[]
        self.photos=[None,None]
        self.render_keys=[None,None]
        self.choices={f"{entry['number']} · {entry['name']}":entry['id']
                      for entry in editor.service.projects.listing(editor.path) if entry['available']}
        header=tk.Frame(d,bg=PANEL,padx=16,pady=12)
        header.pack(fill='x')
        editor.label(header,'把作品放在一起看',font=('Microsoft YaHei UI',14,'bold')).pack(side='left')
        editor.button(header,'刷新快照',self.reload,font=SMALL).pack(side='right')
        body=tk.Frame(d,bg=BG,padx=12,pady=10)
        body.pack(fill='both',expand=True)
        self.variables,self.canvases,self.labels=[],[],[]
        current=editor.service.projects.by_path(editor.path) if editor.path else None
        ordered=list(self.choices.values())
        current_index=ordered.index(current['id']) if current and current['id'] in ordered else 1
        ids=project_ids or ordered[max(0,current_index-1):max(2,current_index+1)]
        keys=list(self.choices) or ['先保存或打开两个项目']
        for index in range(2):
            column=tk.Frame(body,bg=PANEL)
            column.pack(side='left',fill='both',expand=True,padx=5)
            selected=next((key for key,value in self.choices.items() if index<len(ids) and value==ids[index]),keys[min(index,len(keys)-1)])
            var=tk.StringVar(value=selected)
            self.variables.append(var)
            editor._option(column,var,keys,lambda value:self.reload()).pack(fill='x',padx=10,pady=10)
            canvas=tk.Canvas(column,bg='#0d1017',highlightthickness=0)
            canvas.pack(fill='both',expand=True,padx=10)
            canvas.bind('<Configure>',lambda event:self.draw())
            self.canvases.append(canvas)
            info=editor.label(column,'',MUTED,SMALL)
            info.pack(pady=10)
            self.labels.append(info)
        footer=tk.Frame(d,bg=PANEL,padx=16,pady=12)
        footer.pack(fill='x')
        self.play_button=editor.button(footer,'▶ 同时播放',self.toggle,True,font=SMALL)
        self.play_button.pack(side='left')
        editor.button(footer,'← 100ms',lambda:self.seek(max(0,self.current_time()-100)),font=SMALL).pack(side='left',padx=5)
        editor.button(footer,'100ms →',lambda:self.seek(self.current_time()+100),font=SMALL).pack(side='left')
        self.time_label=editor.label(footer,'',MUTED,SMALL)
        self.time_label.pack(side='right')
        self.scrub=tk.Scale(footer,from_=0,to=1000,orient='horizontal',showvalue=False,
                           bg=PANEL,fg=FG,troughcolor=FIELD,highlightthickness=0,bd=0)
        self.scrub.pack(fill='x',padx=12)
        self.scrub.bind('<ButtonPress-1>',lambda event:self.pause())
        for binding in ('<B1-Motion>','<ButtonRelease-1>','<KeyRelease>'):
            self.scrub.bind(binding,lambda event:self.seek(self.scrub.get()))
        self.notice=editor.label(d,'只读对照：使用打开时的快照，按各自真实帧时长播放；相同像素倍率。刷新可读取最新修改。',MUTED,SMALL)
        self.notice.pack(fill='x',padx=18,pady=(0,12))
        d.bind('<Destroy>',self.cleanup,add='+')
        self.reload()

    def reload(self):
        self.pause()
        ids=[self.choices.get(var.get()) for var in self.variables]
        try:
            self.editor.sync_service()
            self.documents=self.editor.service.comparison_documents(ids)
            self.elapsed=0
            self.render_keys=[None,None]
            self.scrub.config(to=max(sum(doc.durations) for _,doc in self.documents)-1)
            self.notice.config(text='只读对照：使用打开时的快照，按各自真实帧时长播放；相同像素倍率。刷新可读取最新修改。')
            self.draw()
            return True
        except (OSError,ValueError,KeyError) as exc:
            self.documents=[]
            for canvas in self.canvases:canvas.delete('all')
            self.notice.config(text='请选择两个不同的已保存项目。 '+str(exc))
            return False

    def current_time(self):
        return self.elapsed+int((time.monotonic()-self.started)*1000) if self.playing else self.elapsed

    def draw(self):
        if not self.documents or not self.dialog.winfo_exists():return
        elapsed=self.current_time()
        ratio=min(12,*[min(max(1,canvas.winfo_width()-24)/doc.width,
                               max(1,canvas.winfo_height()-24)/doc.height)
                            for canvas,(_,doc) in zip(self.canvases,self.documents)])
        zoom=int(ratio) if ratio>=1 else max(.01,ratio)
        for index,(canvas,(entry,doc)) in enumerate(zip(self.canvases,self.documents)):
            frame=frame_at(doc,elapsed)
            key=(frame,zoom,canvas.winfo_width(),canvas.winfo_height())
            if self.render_keys[index]!=key:
                image=doc.preview(frame,scale=1)
                image=image.resize((max(1,round(doc.width*zoom)),max(1,round(doc.height*zoom))),Image.Resampling.NEAREST)
                self.photos[index]=ImageTk.PhotoImage(image)
                canvas.delete('all')
                canvas.create_image(canvas.winfo_width()//2,max(image.height+12,canvas.winfo_height()-12),
                                    image=self.photos[index],anchor='s')
                self.render_keys[index]=key
            self.labels[index].config(text=f'{doc.width} × {doc.height} px · 第 {frame+1} / {len(doc.durations)} 帧 · {doc.durations[frame]}ms')
        cycle=max(sum(doc.durations) for _,doc in self.documents)
        self.scrub.set(elapsed%cycle)
        self.time_label.config(text=f'{elapsed/1000:.2f}s  ·  {zoom*100:.0f}%')

    def tick(self):
        self.job=None
        if not self.playing:return
        self.draw()
        self.job=self.dialog.after(25,self.tick)

    def toggle(self):
        if self.playing:self.pause()
        elif self.documents:
            self.started=time.monotonic()
            self.playing=True
            self.play_button.config(text='Ⅱ 同时暂停')
            self.tick()

    def pause(self):
        self.elapsed=self.current_time()
        self.playing=False
        if self.job:
            self.dialog.after_cancel(self.job)
            self.job=None
        self.play_button.config(text='▶ 同时播放')

    def seek(self,elapsed):
        self.pause()
        self.elapsed=int(elapsed)
        self.draw()

    def cleanup(self,event):
        if event.widget is self.dialog:
            self.playing=False
            if self.job:self.dialog.after_cancel(self.job)
            self.job=None


class HistoryDialog:
    """One project, automatic editable iterations, independent comparison playback."""
    def __init__(self, editor):
        self.editor = editor
        entry = editor.service.projects.by_path(editor.path)
        self.project_id = entry['id']
        self.current = Document.from_dict(editor.doc.to_dict())
        self.observed = (editor.doc.id, editor.doc.revision)
        self.page=0
        self.versions = []
        self.selected = None
        self.playing, self.job, self.elapsed = False, None, 0
        self.dialog = d = tk.Toplevel(editor.root)
        d.title('版本记录 · '+entry['name'])
        d.configure(bg=PANEL)
        d.transient(editor.root)
        place_dialog(d, editor.root, 940, 680)
        d.minsize(720, 540)
        editor.label(d, entry['name'], font=('Microsoft YaHei UI',13,'bold')).pack(anchor='w',padx=18,pady=(16,5))
        editor.label(d, 'AI 修改自动留档。选一版与当前效果比较，选用后继续编辑；其他版本仍保留。', MUTED, SMALL).pack(anchor='w',padx=18,pady=8)
        actions=tk.Frame(d,bg=PANEL)
        actions.pack(fill='x',padx=18,pady=5)
        editor.button(actions,'★ 保留 / 取消保留',self.pin_selected,font=SMALL).pack(side='left')
        editor.button(actions,'删除所选旧版本',self.delete_selected,font=SMALL).pack(side='left',padx=5)
        editor.button(actions,'上一页',lambda:self.turn(-1),font=SMALL).pack(side='right')
        editor.button(actions,'下一页',lambda:self.turn(1),font=SMALL).pack(side='right',padx=5)
        self.page_label=editor.label(actions,'',MUTED,SMALL)
        self.page_label.pack(side='right',padx=8)
        list_frame, self.listing = scrollable_widget(d,tk.Listbox,horizontal=True,bg=BG,fg=FG,
            selectbackground=FIELD,relief='flat',font=SMALL,height=5,exportselection=False,selectmode='extended')
        list_frame.pack(fill='x',padx=18)
        pictures = tk.Frame(d,bg=PANEL)
        pictures.pack(fill='both',expand=True,padx=18,pady=10)
        self.views, self.details = [], []
        for title in ('选中的版本', '当前效果'):
            column = tk.Frame(pictures,bg=BG)
            column.pack(side='left',fill='both',expand=True,padx=4)
            editor.label(column,title,MUTED,SMALL).pack(pady=6)
            picture = tk.Label(column,bg=BG,fg=MUTED,text='选择一个版本')
            picture.pack(fill='both',expand=True)
            detail = editor.label(column,'',MUTED,SMALL)
            detail.pack(pady=6)
            self.views.append(picture)
            self.details.append(detail)
        self.preview = self.views[0]
        controls = tk.Frame(d,bg=PANEL)
        controls.pack(fill='x',padx=18,pady=(0,16))
        self.play_button = editor.button(controls,'播放对比',self.toggle,font=SMALL)
        self.play_button.pack(side='left')
        editor.button(controls,'← 上一帧',lambda:self.step(-1),font=SMALL).pack(side='left',padx=5)
        editor.button(controls,'下一帧 →',lambda:self.step(1),font=SMALL).pack(side='left')
        self.use_button = editor.button(controls,'选用这版，继续修改',self.use,True,font=SMALL)
        self.use_button.pack(side='right')
        editor.button(controls,'刷新',self.reload,font=SMALL).pack(side='right',padx=6)
        self.listing.bind('<<ListboxSelect>>',self.show)
        d.bind('<Destroy>',self.cleanup,add='+')
        self.refresh_versions()

    def refresh_versions(self):
        self.stop()
        response=self.editor.service.projects_action({'action':'versions','project_id':self.project_id,'page':self.page})
        if self.page>=response['pages']:
            self.page=max(0,response['pages']-1)
            return self.refresh_versions()
        self.pages=response['pages']
        self.versions=response['versions']
        self.page_label.config(text=f"{self.page+1}/{self.pages} 页 · 共 {response['total']} 版")
        self.listing.delete(0,'end')
        for version in self.versions:
            try:stamp = datetime.fromisoformat(version['saved_at']).astimezone().strftime('%m-%d %H:%M:%S')
            except ValueError:stamp = version['saved_at'][:22]
            self.listing.insert('end', f"{'★ ' if version['pinned'] else ''}第 {version['number']} 版 · {stamp} · {version['source']} · {version['label'][:70]}")
        if self.versions:
            self.listing.selection_set(0)
            self.show()

    def turn(self,delta):
        self.page=max(0,min(self.pages-1,self.page+delta))
        self.refresh_versions()

    def pin_selected(self):
        selected=[self.versions[i] for i in self.listing.curselection()]
        if not selected:return
        pinned=not all(v['pinned'] for v in selected)
        for version in selected:
            if not self.editor.project_action('version_pin',project_id=self.project_id,version_id=version['id'],pinned=pinned):return
        self.refresh_versions()

    def delete_selected(self):
        ids=[self.versions[i]['id'] for i in self.listing.curselection()]
        if ids:return self.editor.storage_dialog({'targets':['versions'],'project_ids':[self.project_id],
            'version_ids':ids,'older_than_days':0},on_cleanup=self.refresh_versions)

    def stop(self):
        self.playing = False
        if self.job:self.dialog.after_cancel(self.job)
        self.job = None
        self.play_button.config(text='播放对比')

    def show(self,event=None):
        self.stop()
        selected = self.listing.curselection()
        if not selected:return
        try:
            self.selected = Document.open(self.versions[selected[0]]['path'])
            self.elapsed = 0
            self.use_button.config(state='disabled' if self.selected.fingerprint()==self.current.fingerprint() else 'normal')
            self.render()
        except (OSError,ValueError) as exc:
            self.selected = None
            self.preview.config(image='',text=str(exc))
            self.use_button.config(state='disabled')

    def render(self):
        if self.selected is None:return
        self.photos = []
        for index, doc in enumerate((self.selected,self.current)):
            frame = frame_at(doc,self.elapsed)
            image = doc.preview(frame=frame,scale=max(1,min(6,280//max(doc.width,doc.height))))
            if max(image.size)>280:
                ratio = 280/max(image.size)
                image = image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),Image.Resampling.NEAREST)
            photo = ImageTk.PhotoImage(image)
            self.photos.append(photo)
            self.views[index].config(image=photo,text='')
            self.details[index].config(text=f'{doc.width}×{doc.height} · 第 {frame+1}/{len(doc.durations)} 帧 · {doc.durations[frame]}ms')

    def toggle(self):
        if self.playing:self.stop();return
        if self.selected is None:return
        self.playing = True
        self.play_button.config(text='暂停对比')
        self.started = time.monotonic()-self.elapsed/1000
        self.tick()

    def tick(self):
        self.job = None
        if not self.playing:return
        self.elapsed = int((time.monotonic()-self.started)*1000)
        self.render()
        self.job = self.dialog.after(16,self.tick)

    def step(self,delta):
        self.stop()
        if self.selected is None:return
        target = (frame_at(self.selected,self.elapsed)+delta)%len(self.selected.durations)
        self.elapsed = sum(self.selected.durations[:target])
        self.render()

    def reload(self):
        self.dialog.destroy()
        return self.editor.project_history_dialog()

    def use(self):
        from tkinter import messagebox
        self.stop()
        selected = self.listing.curselection()
        if not selected:return
        if (self.editor.doc.id,self.editor.doc.revision)!=self.observed:
            messagebox.showinfo('工程已更新','当前作品在预览后有改动，请刷新版本记录，再选择。',parent=self.dialog)
            return
        version = self.versions[selected[0]]
        if self.editor.project_action('use_version',project_id=self.project_id,version_id=version['id']):
            self.dialog.destroy()
            return self.editor.project_history_dialog()

    def restore(self):
        selected = self.listing.curselection()
        if not selected:return
        version = self.versions[selected[0]]
        name = self.editor.service.projects.get(self.project_id,include_deleted=True)['name']+' · 恢复版本'
        if self.editor.project_action('restore',project_id=self.project_id,version_id=version['id'],name=name):
            self.dialog.destroy()

    def cleanup(self,event):
        if event.widget is self.dialog:
            self.playing = False
            if self.job:self.dialog.after_cancel(self.job)
            self.job = None
