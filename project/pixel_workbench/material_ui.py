"""One optional normal/lighting workbench, using the same service as MCP."""
from __future__ import annotations

import base64
import io
import math
import tkinter as tk
from tkinter import filedialog, ttk, messagebox

from PIL import Image, ImageTk

from .materials import DEFAULTS
from .quality import effective_policy
from .ui import BG, PANEL, FIELD, FG, MUTED, GREEN, SMALL, place_dialog, scrollable_widget
from .messages import user_error
from .paths import WORKSPACE


VIEWS={'光照对照':'comparison','原图对照':'source','法线笔刷':'normal'}
BACKGROUNDS={'棋盘格':'checker','深色':'dark','浅色':'light','透明':'transparent'}
DIRECTIONS={'正面':(0,0,1),'向左':(-.7,0,.714),'向右':(.7,0,.714),
            '向上':(0,.7,.714),'向下':(0,-.7,.714)}


class MaterialDialog:
    def __init__(self,editor):
        self.editor=editor;self.doc_id=editor.doc.id
        self.dialog=d=tk.Toplevel(editor.root);d.title('法线与光照预览 · 不改变原始像素')
        d.configure(bg=BG);d.transient(editor.root);place_dialog(d,editor.root,1220,820);d.minsize(980,680)
        self.pending=None;self.job=None;self.play_job=None;self.playing=False;self.photos=[];self.transforms={};self.brush=[]
        self.quiet=True;self.draft_changed=False
        saved=editor.service.materials.status(editor.doc);config=saved['settings']
        self.values={key:tk.DoubleVar(value=config[key]) for key in ('light_x','light_y','light_height','light_radius','intensity','ambient','normal_strength','specular','shininess','emission_strength')}
        self.light_color=tk.StringVar(value=config['light_color']);self.flip_y=tk.BooleanVar(value=config['flip_y'])
        self.background=tk.StringVar(value=next(k for k,v in BACKGROUNDS.items() if v==config['background']));self.view=tk.StringVar(value='光照对照')
        self.fast_preview=tk.BooleanVar(value=True)
        self.direction=tk.StringVar(value='正面');self.brush_size=tk.IntVar(value=3)
        self.per_frame=tk.BooleanVar(value=saved['normal_frames']>1)
        self.bevel=tk.DoubleVar(value=3.);self.estimate_strength=tk.DoubleVar(value=4.)
        self.frame=tk.IntVar(value=editor.doc.active_frame)
        self.tag=tk.StringVar(value=next(iter(editor.doc.tags),'全部帧'))
        self.emission_ids=[layer.id for layer in editor.doc.layers]
        head=tk.Frame(d,bg=PANEL,padx=16,pady=12);head.pack(fill='x')
        editor.label(head,'法线与光照预览',font=('Microsoft YaHei UI',15,'bold')).pack(side='left')
        editor.label(head,'按需使用 · 预览不改原画，应用后随工程保存',MUTED,SMALL).pack(side='left',padx=18)
        footer=tk.Frame(d,bg=PANEL,padx=14,pady=10);footer.pack(side='bottom',fill='x')
        editor.button(footer,'应用到工程',self.apply,True).pack(side='right',padx=4)
        editor.button(footer,'导出…',self.export_dialog).pack(side='right',padx=4)
        editor.button(footer,'重做应用',lambda:self.history('redo')).pack(side='right',padx=4)
        editor.button(footer,'撤销应用',lambda:self.history('undo')).pack(side='right',padx=4)
        editor.button(footer,'还原预览',self.reset_preview).pack(side='right',padx=4)
        self.status=editor.label(footer,'',MUTED,SMALL,wraplength=410,justify='left');self.status.pack(side='left')
        body=tk.Frame(d,bg=BG,padx=12,pady=12);body.pack(fill='both',expand=True)
        outer=tk.Frame(body,bg=PANEL,width=275);outer.pack(side='left',fill='y',padx=(0,12));outer.pack_propagate(False)
        controls=editor._scroll_panel(outer)
        editor._section(controls,'法线来源')
        for label,command in [('导入法线 PNG / 图集',self.import_normal),('新建平面法线',lambda:self.preview(normal_source={'kind':'flat','frames':len(editor.doc.durations) if self.per_frame.get() else 1})),
                              ('轮廓法线（估算）',lambda:self.preview(normal_source={'kind':'silhouette','bevel':self.bevel.get(),'strength':self.estimate_strength.get()})),
                              ('从高度图生成…',self.import_height)]:
            editor.button(controls,label,command,font=SMALL,pady=4).pack(fill='x',pady=2)
        estimate=tk.Frame(controls,bg=PANEL);estimate.pack(fill='x',pady=5)
        editor.label(estimate,'边缘宽度',MUTED,SMALL).pack(side='left')
        tk.Spinbox(estimate,from_=.1,to=64,increment=.5,textvariable=self.bevel,width=4).pack(side='left',padx=4)
        editor.label(estimate,'坡度',MUTED,SMALL).pack(side='left')
        tk.Spinbox(estimate,from_=.01,to=64,increment=.5,textvariable=self.estimate_strength,width=4).pack(side='left',padx=4)
        editor._check(controls,'逐帧法线（共享时影响全部帧）',self.per_frame,self.frame_mode).pack(anchor='w',pady=5)
        editor.label(controls,'估算不等于真实立体结构；\n原图已有的反光不会自动消除。',MUTED,SMALL,justify='left').pack(anchor='w',pady=5)
        editor._section(controls,'光源 · 也可直接在右图拖动')
        advanced=tk.Frame(controls,bg=PANEL)
        labels=[('intensity','光照强度',0,4),('ambient','环境亮度',0,1.5),('light_height','光源高度',.03,2),
                ('light_radius','照射范围',.1,3),('normal_strength','法线强度',0,3),('specular','反光强度',0,1),
                ('shininess','高光集中程度',1,128),('emission_strength','自发光强度',0,3)]
        for key,label,lo,hi in labels:
            target=controls if key in ('intensity','ambient','normal_strength') else advanced
            editor.label(target,label,MUTED,SMALL).pack(anchor='w',pady=(5,0))
            tk.Scale(target,from_=lo,to=hi,resolution=1 if key=='shininess' else .02,variable=self.values[key],orient='horizontal',
                     bg=PANEL,fg=MUTED,troughcolor=FIELD,highlightthickness=0,bd=0,length=230,sliderlength=16,font=SMALL).pack(fill='x')
        def toggle_advanced():
            if advanced.winfo_manager():advanced.pack_forget();advanced_button.config(text='高级光照参数 ▾')
            else:advanced.pack(fill='x',after=advanced_button);advanced_button.config(text='收起高级参数 ▴')
        advanced_button=editor.button(controls,'高级光照参数 ▾',toggle_advanced,font=SMALL,pady=4)
        advanced_button.pack(fill='x',pady=6)
        row=tk.Frame(controls,bg=PANEL);row.pack(fill='x',pady=7)
        editor.label(row,'灯光色',MUTED,SMALL).pack(side='left');editor._entry(row,self.light_color,10).pack(side='right')
        editor._check(advanced,'翻转绿色通道（Y）',self.flip_y,self.schedule).pack(anchor='w')
        editor._section(controls,'发光图层（保持原堆叠顺序）')
        frame,self.emit_list=scrollable_widget(controls,tk.Listbox,height=4,selectmode='multiple',exportselection=False,bg=FIELD,fg=FG,relief='flat')
        frame.pack(fill='x')
        for index,layer in enumerate(editor.doc.layers):
            self.emit_list.insert('end',layer.name+('（隐藏）' if not layer.visible else ''))
            if layer.id in config['emission_layers']:self.emit_list.selection_set(index)
        self.emit_list.bind('<<ListboxSelect>>',self.schedule)
        editor.button(controls,'导入反光遮罩（可选）',self.import_specular,font=SMALL,pady=4).pack(fill='x',pady=(7,2))
        editor.button(controls,'清除反光遮罩',lambda:self.preview(specular_path=''),font=SMALL,pady=4).pack(fill='x')
        right=tk.Frame(body,bg=BG);right.pack(fill='both',expand=True)
        row=tk.Frame(right,bg=PANEL,padx=8,pady=8);row.pack(fill='x')
        editor._option(row,self.view,list(VIEWS),lambda *_:self.schedule(modified=False)).pack(side='left')
        editor._option(row,self.background,list(BACKGROUNDS),self.schedule).pack(side='left',padx=8)
        editor._check(row,'大图快速预览',self.fast_preview,lambda:self.schedule(modified=False)).pack(side='left')
        editor.button(row,'刷新原画',lambda:self.preview(rebase=True),font=SMALL,pady=4).pack(side='right')
        frames=tk.Frame(right,bg=BG,pady=8);frames.pack(fill='x')
        editor.label(frames,'预览帧',MUTED,SMALL).pack(side='left')
        tk.Spinbox(frames,from_=0,to=len(editor.doc.durations)-1,textvariable=self.frame,width=5,command=self.schedule).pack(side='left',padx=8)
        editor._option(frames,self.tag,['全部帧',*editor.doc.tags],self.choose_tag).pack(side='left')
        self.play_button=editor.button(frames,'▶ 播放预览',self.toggle_play,font=SMALL,pady=4);self.play_button.pack(side='left',padx=8)
        brush=tk.Frame(right,bg=PANEL,padx=8,pady=6);brush.pack(fill='x')
        editor.label(brush,'法线笔刷：',MUTED,SMALL).pack(side='left')
        editor._option(brush,self.direction,list(DIRECTIONS)).pack(side='left')
        tk.Spinbox(brush,from_=1,to=32,textvariable=self.brush_size,width=4).pack(side='left',padx=8)
        editor.label(brush,'切到“法线笔刷”后在左图画；右图仍可拖光源。',MUTED,SMALL).pack(side='left')
        panes=tk.Frame(right,bg=BG);panes.pack(fill='both',expand=True,pady=8)
        self.canvases=[];self.captions=[]
        for index in range(2):
            pane=tk.Frame(panes,bg=PANEL);pane.pack(side='left',fill='both',expand=True,padx=(0,5) if index==0 else (5,0))
            caption=editor.label(pane,'',MUTED,SMALL,pady=8);caption.pack(fill='x');self.captions.append(caption)
            canvas=tk.Canvas(pane,bg='#0c111a',highlightthickness=0);canvas.pack(fill='both',expand=True);self.canvases.append(canvas)
            canvas.bind('<Configure>',self.redraw)
            canvas.bind('<Button-1>',lambda event,i=index:self.pointer_down(event,i))
            canvas.bind('<B1-Motion>',lambda event,i=index:self.pointer_move(event,i))
            canvas.bind('<ButtonRelease-1>',lambda event,i=index:self.pointer_up(event,i))
        editor.label(right,'还原预览：丢弃未应用调整。应用后与主画布共用撤销；原始像素与调色板保持不变。',MUTED,SMALL,wraplength=780,justify='left').pack(anchor='w')
        self.images=[]
        for variable in [*self.values.values(),self.light_color]:variable.trace_add('write',self.schedule)
        self.frame.trace_add('write',lambda *_:self.schedule(modified=False))
        self.quiet=False;d.protocol('WM_DELETE_WINDOW',self.close);d.bind('<Destroy>',self.destroyed,add='+')
        self.preview()

    def observed(self):return {'expected_document_id':self.editor.doc.id,'expected_revision':self.editor.doc.revision}

    def present(self,key):
        if self.draft_changed or self.brush:
            self.dialog.lift();return {'ok':True,'presented':False,'reason':'Human material draft pending; apply or restore it before replacing this view.'}
        ticket=self.editor.service.materials.ticket(self.editor.doc,key)
        self.stop_play();config=ticket['material']['settings'];self.quiet=True
        for name,var in self.values.items():var.set(config[name])
        self.frame.set(ticket['frame']);self.light_color.set(config['light_color']);self.flip_y.set(config['flip_y'])
        self.background.set(next(k for k,v in BACKGROUNDS.items() if v==config['background']))
        self.view.set(next((k for k,v in VIEWS.items() if v==ticket['view']),'光照对照'))
        self.emit_list.selection_clear(0,'end')
        for i,layer in enumerate(self.emission_ids):
            if layer in config['emission_layers']:self.emit_list.selection_set(i)
        self.editor.service.materials.release(self.pending);self.pending=key;self.editor.service.materials.retain(key)
        self.quiet=False;result=self.preview();self.draft_changed=False
        self.dialog.deiconify();self.dialog.lift()
        return {'ok':True,'presented':result is not None,'frame':ticket['frame'],'source_preview_id':key}

    def config(self):
        return {**{key:var.get() for key,var in self.values.items()},'light_color':self.light_color.get(),
                'flip_y':self.flip_y.get(),'background':BACKGROUNDS[self.background.get()],
                'emission_layers':[self.emission_ids[i] for i in self.emit_list.curselection()]}

    def send(self,payload):
        if self.editor.doc.id!=self.doc_id:raise ValueError('工程已切换，请重新打开光照预览。')
        return self.editor.dispatch('POST','/material',{},payload)[0]

    def preview(self,**extra):
        if self.job:self.dialog.after_cancel(self.job);self.job=None
        try:
            payload={'action':'preview','settings':self.config(),'frame':self.frame.get(),'view':VIEWS[self.view.get()],
                     'scale':1,'preview_limit':256 if self.fast_preview.get() else 512,**self.observed(),**extra}
            if self.pending:payload['source_preview_id']=self.pending
            result=self.send(payload)
            self.editor.service.materials.retain(result['preview_id'])
            self.editor.service.materials.release(self.pending)
            self.pending=result['preview_id'];self.last_result=result
            self.per_frame.set(result['normal_frames']>1)
            self.images=[Image.open(io.BytesIO(base64.b64decode(data))).convert('RGBA') for data in result['images_png']]
            self.redraw();self.status.config(text=('估算法线 · ' if result['approximate'] else '')+f"第 {result['frame']} 帧 · {result.get('render_ms',0):.0f}ms · 未应用调整不改原画",fg=MUTED)
            if result.get('alignment_warning'):self.status.config(text='原画已变化，请检查当前法线是否仍对齐，再应用。',fg='#f3bd68')
            if result.get('mask_warning'):self.status.config(text='新贴图预览已排除尺寸不匹配的旧反光遮罩；应用前原材质仍保留。',fg='#f3bd68')
            if result.get('preview_limited'):self.status.config(text='大图快速预览；细节检查请关闭此选项，导出仍保持原尺寸。',fg=MUTED)
            if extra.get('normal_source') or extra.get('normal_edits') or 'specular_path' in extra:self.draft_changed=True
            return result
        except (ValueError,OSError,KeyError,tk.TclError) as error:
            self.status.config(text=user_error(error),fg='#f19493');return None

    def schedule(self,*_,modified=True):
        if self.quiet:return
        if modified:self.draft_changed=True
        if self.job:self.dialog.after_cancel(self.job)
        self.job=self.dialog.after(85,self.preview)

    def redraw(self,*_):
        if not self.images:return
        self.photos=[];self.transforms={}
        titles={'comparison':['相同灯光 · 平面表面','相同灯光 · 法线效果'],
                'source':['原始颜色图','光照预览'], 'normal':['法线数据 · 左图可画方向','光照预览']}
        for i,(canvas,image) in enumerate(zip(self.canvases,self.images)):
            canvas.delete('all');self.captions[i].config(text=titles[VIEWS[self.view.get()]][i])
            ratio=min(max(canvas.winfo_width()-12,1)/image.width,max(canvas.winfo_height()-12,1)/image.height,8)
            resized=image.resize((max(1,round(image.width*ratio)),max(1,round(image.height*ratio))),Image.Resampling.NEAREST)
            photo=ImageTk.PhotoImage(resized);self.photos.append(photo)
            x=(canvas.winfo_width()-resized.width)/2;y=(canvas.winfo_height()-resized.height)/2
            canvas.create_image(x,y,image=photo,anchor='nw');self.transforms[i]=(x,y,ratio*image.width/self.editor.doc.width)
            if i==1:
                lx=x+self.values['light_x'].get()*max(image.width-1,1)*ratio;ly=y+self.values['light_y'].get()*max(image.height-1,1)*ratio
                canvas.create_line(lx-7,ly,lx+7,ly,fill='#ffd58a',width=2);canvas.create_line(lx,ly-7,lx,ly+7,fill='#ffd58a',width=2)

    def point(self,event,index):
        if index not in self.transforms:return None
        x,y,ratio=self.transforms[index]
        return round((event.x-x)/ratio),round((event.y-y)/ratio)

    def pointer_down(self,event,index):
        self.stop_play();self.brush=[];self.pointer_move(event,index)

    def pointer_move(self,event,index):
        point=self.point(event,index)
        if point is None:return
        if index==0 and self.view.get()=='法线笔刷':
            x,y=point
            if 0<=x<self.editor.doc.width and 0<=y<self.editor.doc.height:
                if not self.brush or self.brush[-1]!=[x,y]:
                    old=self.brush[-1] if self.brush else [x,y];self.brush.append([x,y])
                    ox,oy,ratio=self.transforms[index]
                    vector=DIRECTIONS[self.direction.get()];length=math.sqrt(sum(v*v for v in vector))
                    color='#'+''.join(f'{round((v/length+1)*127.5):02x}' for v in vector)
                    self.canvases[index].create_line(ox+old[0]*ratio,oy+old[1]*ratio,ox+x*ratio,oy+y*ratio,
                        fill=color,width=max(1,self.brush_size.get()*ratio),capstyle='round')
        else:
            self.quiet=True
            self.values['light_x'].set(max(-2,min(3,point[0]/max(1,self.editor.doc.width-1))))
            self.values['light_y'].set(max(-2,min(3,point[1]/max(1,self.editor.doc.height-1))))
            self.quiet=False;self.schedule()

    def pointer_up(self,event,index):
        if self.brush:
            self.draft_changed=True
            points=self.brush;self.brush=[]
            self.preview(normal_edits=[{'op':'stroke','points':points,'size':self.brush_size.get(),
                                       'normal':list(DIRECTIONS[self.direction.get()]),'frame':self.frame.get()}])
            self.brush=[]

    def frame_mode(self):
        self.draft_changed=True
        self.preview(normal_source={'kind':'current','frames':len(self.editor.doc.durations) if self.per_frame.get() else 1})

    def import_map(self,height=False):
        path=filedialog.askopenfilename(parent=self.dialog,filetypes=[('PNG map','*.png')])
        if not path:return
        self.draft_changed=True
        source={'kind':'height' if height else 'import','path':path}
        if height:source['strength']=self.estimate_strength.get()
        try:
            with Image.open(path) as image:
                columns=image.width//self.editor.doc.width
                count=len(self.editor.doc.durations)
                if count>1 and image.size!=(self.editor.doc.width,self.editor.doc.height) and 1<=columns<=count and image.size==(self.editor.doc.width*columns,self.editor.doc.height*math.ceil(count/columns)):
                    source.update(frames=count,columns=columns)
        except (OSError,ValueError) as error:
            self.status.config(text=user_error(error),fg='#f19493');return None
        self.preview(normal_source=source)

    def import_normal(self):return self.import_map()
    def import_height(self):return self.import_map(height=True)

    def import_specular(self):
        path=filedialog.askopenfilename(parent=self.dialog,filetypes=[('PNG mask','*.png')])
        if path:self.draft_changed=True;self.preview(specular_path=path)

    def reset_preview(self):
        self.stop_play();self.editor.service.materials.release(self.pending);self.pending=None
        saved=self.editor.service.materials.status(self.editor.doc)['settings'];self.quiet=True
        for key,var in self.values.items():var.set(saved[key])
        self.light_color.set(saved['light_color']);self.background.set(next(k for k,v in BACKGROUNDS.items() if v==saved['background']));self.flip_y.set(saved['flip_y'])
        self.emit_list.selection_clear(0,'end')
        for i,key in enumerate(self.emission_ids):
            if key in saved['emission_layers']:self.emit_list.selection_set(i)
        self.quiet=False;self.draft_changed=False;return self.preview()

    def apply(self):
        self.stop_play()
        if self.preview() is None:return False
        try:
            result=self.send({'action':'apply','preview_id':self.pending,**self.observed()})
            self.editor.service.materials.release(self.pending);self.pending=None;self.draft_changed=False;self.preview();self.status.config(text='材质已应用；原始像素未改变，可撤销并随工程保存。',fg=GREEN)
            if result.get('storage_warning'):self.status.config(text='已应用，但自动恢复文件写入失败；请手动保存工程。',fg='#f3bd68')
            return result
        except (ValueError,OSError) as error:self.status.config(text=user_error(error),fg='#f19493');return False

    def history(self,action):
        self.stop_play()
        if self.draft_changed:
            self.status.config(text='请先还原预览或应用当前调整，再撤销／重做工程中的步骤。',fg=MUTED);return
        try:
            self.editor.dispatch('POST','/'+action,{},self.observed());self.reset_preview()
        except (ValueError,OSError) as error:self.status.config(text=user_error(error),fg='#f19493')

    def choose_tag(self,*_):
        self.stop_play();order=self.order();self.frame.set(order[0]);self.schedule(modified=False)

    def order(self):
        tag=self.tag.get() if self.tag.get() in self.editor.doc.tags else None
        return self.editor.doc.frame_indices(tag,playback=True)

    def stop_play(self):
        if self.play_job:self.dialog.after_cancel(self.play_job);self.play_job=None
        self.playing=False
        if hasattr(self,'play_button') and self.play_button.winfo_exists():self.play_button.config(text='▶ 播放预览')

    def toggle_play(self):
        if self.playing:self.stop_play();return
        if self.tag.get()=='全部帧' and len(self.editor.doc.tags)>1:
            self.status.config(text='多个动作请先选择一个动作播放；全部帧仍可逐帧查看。',fg=MUTED);return
        self.playing=True;self.play_button.config(text='■ 停止预览');self.play_index=0;self.play_order=self.order();self.tick()

    def tick(self):
        if not self.playing or not self.dialog.winfo_exists():return
        self.quiet=True;self.frame.set(self.play_order[self.play_index]);self.quiet=False
        if self.preview() is None:self.stop_play();return
        duration=self.editor.doc.durations[self.frame.get()];self.play_index+=1
        if self.play_index>=len(self.play_order):
            tag=self.tag.get() if self.tag.get() in self.editor.doc.tags else None
            if not effective_policy(self.editor.doc,tag)['loop']:self.stop_play();return
            self.play_index=0
        self.play_job=self.dialog.after(duration,self.tick)

    def export_dialog(self):
        self.stop_play()
        dialog=tk.Toplevel(self.dialog);dialog.title('导出材质预览');dialog.configure(bg=PANEL);dialog.transient(self.dialog);place_dialog(dialog,self.dialog,480,240)
        body=tk.Frame(dialog,bg=PANEL,padx=20,pady=18);body.pack(fill='both',expand=True)
        choices={'当前帧光照 PNG':'render','法线 PNG':'normal','动画光照图集 ZIP':'sheet','引擎贴图包 ZIP':'bundle'}
        selected=tk.StringVar(value=next(iter(choices)));all_frames=tk.BooleanVar(value=True)
        self.editor.label(body,'选择输出内容',FG,SMALL).pack(anchor='w')
        self.editor._option(body,selected,list(choices)).pack(fill='x',pady=10)
        self.editor._check(body,'ZIP 包包含全部源动画帧（保留各帧时长）',all_frames).pack(anchor='w')
        self.editor.label(body,'导出为材质预览，不覆盖原始颜色图。',MUTED,SMALL).pack(anchor='w',pady=8)
        def save():
            kind=choices[selected.get()];suffix='.zip' if kind in ('sheet','bundle') else '.png'
            path=filedialog.asksaveasfilename(parent=dialog,initialdir=WORKSPACE/'exports',initialfile=self.editor.doc.name+'-材质预览'+suffix,defaultextension=suffix,filetypes=[('Material preview','*'+suffix)])
            if path and self.export_to(path,kind,all_frames=all_frames.get() and kind in ('sheet','bundle'),overwrite=True):dialog.destroy()
        self.editor.button(body,'保存到…',save,True).pack(side='right',pady=6)

    def export_to(self,path,kind='render',all_frames=False,overwrite=False):
        if self.preview() is None:return None
        try:
            result=self.send({'action':'export','preview_id':self.pending,'path':str(path),'kind':kind,
                              'all_frames':all_frames,'overwrite':overwrite,**self.observed()})
            self.status.config(text='已导出材质预览；原画验收不代表光照效果已验收。',fg=GREEN);return result
        except (ValueError,OSError) as error:self.status.config(text=user_error(error),fg='#f19493');return None

    def close(self):
        if self.draft_changed and not messagebox.askokcancel('未应用的材质调整','关闭会放弃本窗口未应用的调整；原画和已应用的材质仍保留。',parent=self.dialog):return
        self.dialog.destroy()

    def destroyed(self,event):
        if event.widget==self.dialog:
            self.editor.service.materials.release(self.pending)
            if self.job:self.dialog.after_cancel(self.job)
            self.stop_play()
