"""Shared document operations for the desktop, headless runner and MCP transport."""
from __future__ import annotations

import base64
from copy import deepcopy
from collections import OrderedDict
import hashlib
import io
import json
from pathlib import Path
import uuid

from PIL import Image

from . import __version__
from .model import Document, PixelError, atomic_json, hexcolor, integer
from .workflow import TaskStore, capabilities, compact_state, part_key
from .operations import full_schema, guide
from .paths import RUNTIME, WORKSPACE
from .reference import ReferenceWorkspace, decoded_asset, encode_png, load_asset, make_draft, new_redraw_document
from .quality import QualityManager, effective_policy, update_policy
from .sheet_export import check_sidecars,export_paths
from .feedback import FeedbackManager, summary as feedback_summary
from .projects import ProjectLibrary, path_key, frame_at

JSON_TYPE = "application/json; charset=utf-8"


def png_bytes(image):
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


class DocumentService:
    def __init__(self, doc=None, workspace=None, runtime=None, mode="headless"):
        self.doc = doc or Document()
        self.path = None
        self.workspace = Path(workspace or WORKSPACE).resolve()
        self.runtime = Path(runtime or RUNTIME).resolve()
        self.mode = mode
        self.saved_fingerprint = self.doc.fingerprint()
        self.requests = OrderedDict()
        self.tasks = TaskStore(self.runtime)
        from .generation import GenerationManager
        self.generation = GenerationManager()
        self.preview_cache = OrderedDict()
        self.part_receipts = OrderedDict()
        self.closing = False
        self.view = {"playing": False, "gesture_active": False}
        for path in (self.workspace / "projects", self.workspace / "exports", self.runtime / "recovery"):
            path.mkdir(parents=True, exist_ok=True)
        self.references = ReferenceWorkspace(self.runtime / "reference-workspace.json")
        from .cutout import CutoutManager
        self.cutouts = CutoutManager()
        self.quality = QualityManager(self.runtime)
        from .motion import MotionManager
        self.motion = MotionManager()
        from .materials import MaterialManager
        self.materials = MaterialManager()
        self.feedback = FeedbackManager()
        self.projects = ProjectLibrary(self.runtime, self.workspace)
        from .storage import StorageManager
        self.storage = StorageManager(self)
        self.restore_reference()

    def restore_reference(self):
        self.references.restore(self.doc.reference)

    @property
    def dirty(self):
        return self.doc.fingerprint() != self.saved_fingerprint

    def state(self):
        reference = self.references.summary(self.doc)
        reference["cutout"].update(self.cutouts.status(self.doc.id, self.references.context))
        try:context=self.tasks.status(self.doc,brief=True)
        except PixelError as error:context={'error':str(error),'code':error.code}
        return {**self.doc.state(), "capabilities":capabilities(),"workflow_context":context,
                "app_version": __version__, "project_path": str(self.path) if self.path else None,
                "unsaved_changes": self.dirty, "editor": {"mode": self.mode, **self.view},
                "workspace": str(self.workspace), "reference_workflow": reference,
                "material": self.materials.status(self.doc),
                "quality_review": self.quality.summary(self.doc), "feedback": feedback_summary(self.doc),
                "project_library": {"count":len(self.projects.scoped('open'))+len(self.projects.scoped('closed')),
                    "open_count":len(self.projects.scoped('open')),
                    "closed_count":len(self.projects.scoped('closed')),
                    "deleted_count":len(self.projects.scoped('deleted')),
                    "active":self.projects.by_path(self.path) if self.path else None,
                    "help":"pixel_projects: list/register, fork/new/switch, versions/version_preview/use_version/restore/compare, close/reopen, remove/deleted/undelete"}}

    def resolve(self, value):
        path = Path(value).expanduser()
        return (path if path.is_absolute() else self.workspace / path).resolve()

    def guard(self, payload):
        if payload.get("expected_document_id") != self.doc.id:
            raise PixelError("A different document is open. Read pixel_status before editing.", code="DOCUMENT_CONFLICT")
        if payload.get("expected_revision") != self.doc.revision:
            raise PixelError(f"Expected revision {payload.get('expected_revision')}; current revision is {self.doc.revision}.",
                             code="REVISION_CONFLICT", recovery="Read pixel_status and re-plan using the current document. Do not blindly replay stale edits.")
        if self.view.get("gesture_active"):
            raise PixelError("The human is drawing a stroke. Wait for the pointer to be released.", code="EDITOR_BUSY")

    def autosave(self):
        self.doc.save(self.runtime / "recovery" / f"{self.doc.id}.pixloom")
        self.doc.save(self.runtime / "autosave.pixloom")
        entry = self.projects.by_path(self.path) if self.path else None
        folder = self.projects.history_folder(entry) if entry else self.projects.draft_history(self.doc.id)
        if not any(folder.glob('*.pixloom')) and self.doc.undo_stack:
            self.projects.record_iteration(Document.from_dict(self.doc.undo_stack[0]), self.path,
                                           label='初始版本', source='保存')
        self.projects.record_iteration(self.doc, self.path)

    def remember_path(self):
        atomic_json(self.runtime / "last-project.json", {"path": str(self.path) if self.path else None})
        if self.path:
            if self.path.exists():
                self.projects.register(self.path,self.doc)

    def save_project(self, target=None, overwrite=False, parent_id=None):
        target=self.resolve(target) if target else self.path
        if target is None or target.suffix.lower()!='.pixloom':
            raise PixelError('Save editable projects with a .pixloom path')
        same=self.path is not None and path_key(target)==path_key(self.path)
        if target.exists() and not same and not overwrite:
            raise PixelError('Project already exists. Choose a new path or explicitly set overwrite=true.',code='FILE_EXISTS')
        if same:
            self.projects.check_external_change(target)
        if target.exists() and (not same or self.dirty):
            self.projects.backup(target)
        self.doc.save(target)
        self.path=target
        self.saved_fingerprint=self.doc.fingerprint()
        self.projects.register(target,self.doc,parent_id)
        self.projects.record_iteration(self.doc, target)
        self.remember_path()
        return target

    def checkpoint_current(self):
        """Project switching saves the outgoing document instead of replacing it."""
        if self.path is None and not self.dirty and self.doc.name=='未命名作品' and not self.doc.reference and all(
                not cel.getbbox() for layer in self.doc.layers for cel in layer.cels):
            return None  # A clean empty workspace is not another retained project.
        if self.path is None:
            self.save_project(self.projects.new_path(self.doc.name))
        elif self.dirty:
            self.save_project()
        else:
            self.projects.check_external_change(self.path)
            self.remember_path()
        return self.projects.by_path(self.path)

    def comparison_documents(self, project_ids):
        if not isinstance(project_ids,list) or not 2<=len(project_ids)<=4 or len(set(project_ids))!=len(project_ids):
            raise PixelError('Choose two to four distinct project ids')
        documents=[]
        for project_id in project_ids:
            entry=self.projects.get(project_id)
            current=self.path is not None and path_key(entry['path'])==path_key(self.path)
            doc=Document.from_dict(self.doc.to_dict()) if current else Document.open(entry['path'])
            documents.append((dict(entry),doc))
        return documents

    def project_listing(self):
        from .storage import paged
        total=len(self.projects.scoped('open'))
        listing=paged([None]*total)
        return {'projects':self.projects.listing(self.path,page=0,limit=20),
                'project_list_paging':{k:v for k,v in listing.items() if k!='items'}}

    def projects_action(self,payload):
        action=payload.get('action','list')
        if action in ('list','deleted','closed'):
            from .storage import paged
            total=len(self.projects.scoped('deleted' if action=='deleted' else 'closed' if action=='closed' else 'open'))
            listing=paged([None]*total,payload.get('page',0),payload.get('limit',20))
            return {'ok':True,**self.state(),**{k:v for k,v in listing.items() if k!='items'},
                    'projects':self.projects.listing(self.path,action=='deleted',listing['page'],listing['limit'],action=='closed')}
        if action=='versions':
            from .storage import paged
            from .model import integer
            page=integer(payload.get('page',0),'page',0)
            limit=integer(payload.get('limit',20),'limit',1,100)
            entry=self.projects.get(payload.get('project_id'))
            total=sum(1 for _ in self.projects.history_folder(entry).glob('*.pixloom'))
            listing=paged([None]*total,page,limit)
            return {'ok':True,'project_id':payload.get('project_id'),
                    **{k:v for k,v in listing.items() if k!='items'},
                    'versions':self.projects.versions(payload.get('project_id'),page,limit)}
        if action=='version_preview':
            entry = self.projects.get(payload.get('project_id'))
            doc = Document.open(self.projects.version_path(entry['id'], payload.get('version_id')))
            page, time_ms = payload.get('page', 0), payload.get('time_ms', 0)
            view = payload.get('view', 'contact')
            if type(page) is not int or page < 0 or type(time_ms) is not int or time_ms < 0 or view not in ('contact', 'time'):
                raise PixelError('Use a nonnegative page/time_ms and contact/time view')
            current = self.doc if self.path and path_key(entry['path']) == path_key(self.path) else Document.open(entry['path'])
            pages = max((len(item.durations)+7)//8 for item in (doc, current))
            if page >= pages:raise PixelError('Version page out of range')
            images, items = [], []
            for role, item in [('selected_version', doc), ('current', current)]:
                frames = list(range(page*8, min(len(item.durations), (page+1)*8))) if view == 'contact' else [frame_at(item, time_ms)]
                picture = item.contact_sheet(frames, columns=4, scale=max(1,min(4,192//max(item.width,item.height)))) if frames else Image.new('RGBA',(32,32))
                images.append(encode_png(picture))
                items.append({'role':role,'frames':frames,'frame_count':len(item.durations),'durations':item.durations})
            return {'ok':True,'read_only':True,'project_id':entry['id'],'version_id':payload['version_id'],
                    'page':page,'pages':pages,'view':view,'time_ms':time_ms,'items':items,'images_png':images}
        if action=='compare':
            documents=self.comparison_documents(payload.get('project_ids'))
            page=payload.get('page',0)
            time_ms=payload.get('time_ms',0)
            if type(page) is not int or page<0 or type(time_ms) is not int or time_ms<0:
                raise PixelError('page and time_ms must be nonnegative integers')
            view=payload.get('view','contact')
            if view not in ('contact','time'):
                raise PixelError('Comparison view must be contact or time')
            pages=max((len(doc.durations)+7)//8 for _,doc in documents)
            if page>=pages:raise PixelError('Comparison page is out of range')
            images,items=[],[]
            for entry,doc in documents:
                frames=list(range(page*8,min(len(doc.durations),(page+1)*8))) if view=='contact' else [frame_at(doc,time_ms)]
                image=doc.contact_sheet(frames,columns=4,scale=max(1,min(4,192//max(doc.width,doc.height)))) if frames else Image.new('RGBA',(32,32))
                images.append(encode_png(image))
                items.append({'project_id':entry['id'],'name':doc.name,'document_id':doc.id,
                              'frames':frames,'frame_count':len(doc.durations),'durations':doc.durations,
                              'width':doc.width,'height':doc.height,'current_unsaved':bool(self.path and path_key(entry['path'])==path_key(self.path) and self.dirty)})
            return {'ok':True,'read_only':True,'view':view,'page':page,'pages':pages,'time_ms':time_ms,
                    'projects':items,'images_png':images}
        self.guard(payload)
        if action=='version_pin':
            version=self.projects.pin_version(payload.get('project_id'),payload.get('version_id'),payload.get('pinned'))
            return {'ok':True,**self.state(),'version':version}
        if action=='use_version':
            entry = self.projects.get(payload.get('project_id'))
            if not self.path or path_key(self.path) != path_key(entry['path']):
                raise PixelError('Switch to this project before choosing a version',code='DOCUMENT_CONFLICT')
            restored = Document.open(self.projects.version_path(entry['id'],payload.get('version_id')))
            self.checkpoint_current()
            self.doc.use_version(restored, '选用历史版本 · '+payload['version_id'].split('-')[0],payload.get('source','AI'))
            self.restore_reference()
            self.autosave()
            self.save_project()
            return {'ok':True,**self.state(),**self.project_listing(),'history_preserved':True}
        if action in ('remove','undelete'):
            project_ids=payload.get('project_ids') or [payload.get('project_id')]
            if not isinstance(project_ids,list) or not 1<=len(project_ids)<=256 or any(not isinstance(key,str) for key in project_ids):
                raise PixelError('Choose 1–256 project ids')
            selected=[self.projects.get(key,include_deleted=action=='undelete') for key in dict.fromkeys(project_ids)]
            active=self.projects.by_path(self.path) if self.path else None
            if action=='remove' and active and active['id'] in project_ids:
                # Preserve dirty outgoing pixels. Validate a replacement before changing the current document.
                destination=None
                remaining=[entry for entry in self.projects.listing() if entry['id'] not in project_ids and entry['available']]
                remaining.sort(key=lambda entry:(abs(entry['number']-active['number']),entry['number']))
                for entry in remaining:
                    try:destination=(Document.open(entry['path']),entry['path']);break
                    except (OSError,ValueError,KeyError):continue
                self.checkpoint_current()
                self.replace(*(destination or (Document(),None)))
            changed=self.projects.set_deleted([entry['id'] for entry in selected],deleted=action=='remove')
            return {'ok':True,**self.state(),**self.project_listing(),
                    'changed_project_ids':[entry['id'] for entry in changed],
                    'files_preserved':True,'history_preserved':True}
        if action in ('close','reopen'):
            project_ids=payload.get('project_ids') or [payload.get('project_id')]
            if not isinstance(project_ids,list) or not 1<=len(project_ids)<=256 or any(not isinstance(key,str) for key in project_ids):
                raise PixelError('Choose 1–256 project ids')
            requested=set(dict.fromkeys(project_ids))
            for key in requested:self.projects.get(key)  # Validate every id before changing the shelf.
            if action=='reopen':
                changed=self.projects.set_closed([entry['id'] for entry in self.projects.scoped('closed')
                                                  if entry['id'] in requested],closed=False)
                return {'ok':True,**self.state(),**self.project_listing(),
                        'changed_project_ids':[entry['id'] for entry in changed],
                        'files_preserved':True,'history_preserved':True}
            open_entries=self.projects.listing(self.path)
            closing=[entry for entry in open_entries if entry['id'] in requested]
            if not closing:
                return {'ok':True,**self.state(),**self.project_listing(),'changed_project_ids':[]}
            closing_ids={entry['id'] for entry in closing}
            active=next((entry for entry in open_entries if entry['active']),None)
            if active is not None and active['id'] in closing_ids:
                # Closing the tab being edited: keep its pixels, then open a survivor the way
                # a browser activates the neighbouring tab. The caller may name one explicitly.
                keep_id=payload.get('keep_project_id')
                index=open_entries.index(active)
                survivors=[entry for entry in open_entries if entry['id'] not in closing_ids]
                right=[entry for entry in open_entries[index+1:] if entry['id'] not in closing_ids]
                left=[entry for entry in reversed(open_entries[:index]) if entry['id'] not in closing_ids]
                destination=None
                for entry in [*[e for e in survivors if e['id']==keep_id],*right,*left]:
                    if not entry['available']:continue
                    try:destination=(Document.open(entry['path']),entry['path']);break
                    except (OSError,ValueError,KeyError):continue
                self.checkpoint_current()
                self.replace(*(destination or (Document(),None)))
            changed=self.projects.set_closed([entry['id'] for entry in closing],closed=True)
            return {'ok':True,**self.state(),**self.project_listing(),
                    'changed_project_ids':[entry['id'] for entry in changed],
                    'files_preserved':True,'history_preserved':True}
        if action=='register':
            target=self.resolve(payload['path'])
            if self.path is not None and path_key(target)==path_key(self.path):
                self.projects.check_external_change(target)
            self.projects.register(target)
        elif action=='switch':
            entry=self.projects.get(payload.get('project_id'))
            if self.path is not None and path_key(entry['path'])==path_key(self.path):
                return {'ok':True,**self.state(),**self.project_listing()}
            doc=Document.open(entry['path'])  # Validate destination before saving or replacing anything.
            if entry.get('closed_at'):self.projects.set_closed([entry['id']],closed=False)  # Opening reopens the tab.
            self.checkpoint_current()
            self.replace(doc,entry['path'])
        elif action in ('fork','new','restore'):
            name=str(payload.get('name') or ('新项目' if action=='new' else self.doc.name+' · 副本')).strip()[:120]
            if action=='new':
                doc=Document(payload.get('width',48),payload.get('height',48),name)
            elif action=='restore':
                doc=Document.open(self.projects.version_path(payload.get('project_id'),payload.get('version_id')))
                doc.name=name
            else:
                doc=Document.from_dict(self.doc.to_dict())
                doc.name=name
            doc.id=uuid.uuid4().hex
            doc.quality_reviews=[]  # A separate project requires its own acceptance review.
            target=self.resolve(payload['path']) if payload.get('path') else self.projects.new_path(name)
            if target.exists() or target.suffix.lower()!='.pixloom':
                raise PixelError('A new project needs an unused .pixloom path; the original is never overwritten.',code='FILE_EXISTS')
            outgoing=self.checkpoint_current()
            parent_id=payload.get('project_id') if action=='restore' else outgoing['id'] if action=='fork' and outgoing else None
            self.replace(doc)
            self.saved_fingerprint=''
            self.save_project(target,parent_id=parent_id)
        else:
            raise PixelError('Unknown project library action')
        return {'ok':True,**self.state(),**self.project_listing()}

    def replace(self, doc, path=None, discard_changes=False):
        if self.dirty and not discard_changes:
            raise PixelError("Current artwork has unsaved changes. Save it before replacing the document, or explicitly set discard_changes=true.",
                             code="UNSAVED_CHANGES", recovery="Use pixel_project(action='save', path='projects/<name>.pixloom') first.")
        self.autosave()
        doc.revision = max(doc.revision, self.doc.revision + 1)
        self.doc = doc
        self.path = Path(path) if path else None
        self.saved_fingerprint = doc.fingerprint()
        self.requests.clear()
        self.restore_reference()
        self.remember_path()

    def reference_view(self, view="comparison", proposed=None):
        if view not in ("status", "subject", "style", "draft", "comparison"):
            raise PixelError("Unknown reference view")
        data = {"ok": True, **self.references.summary(self.doc), "document_id": self.doc.id,
                "revision": self.doc.revision, "image_roles": []}
        data["cutout"].update(self.cutouts.status(self.doc.id, self.references.context))
        images = []
        context = self.references.context
        def add(role, image):
            images.append(encode_png(image))
            data["image_roles"].append(role)
        if view in ("subject", "comparison") and context["subject"]:
            add("subject_reference", decoded_asset(context["subject"]["png"]))
            if context.get("cutout") is not None:
                from .cutout import cutout_subject
                add("applied_cutout_reference", cutout_subject(context["subject"], context["cutout"]))
        if view in ("draft", "comparison") and context["subject"]:
            draft, palette = make_draft(context)
            scale = max(1, min(8, 512//max(draft.size)))
            add("automatic_draft_NOT_AI_redraw", draft.resize((draft.width*scale, draft.height*scale), Image.Resampling.NEAREST))
            data["draft_palette"] = palette
        if view == "comparison":
            doc = proposed or self.doc
            add("proposed_redraw" if proposed else "current_artwork", doc.preview(scale=max(1, min(8, 512//max(doc.width, doc.height)))))
            if proposed:
                data["dry_run"] = True
                data["changes"] = proposed.last_change
        if view in ("style", "comparison") and context["style"]:
            add("style_reference", decoded_asset(context["style"]["png"]))
        if view in ("subject", "style", "draft") and not images:
            raise PixelError("No reference image loaded for this view", code="REFERENCE_REQUIRED")
        data["images_png"] = images
        return data

    def reference_setup(self, payload):
        self.guard(payload)
        self.references.guard(payload.get("expected_reference_revision"))
        action, role = payload["action"], payload.get("role", "subject")
        if action == "load" and not payload.get("path"):
            raise PixelError("A local image path is required")
        asset = load_asset(self.resolve(payload["path"])) if action == "load" else None
        if action == "use_project":
            if not self.doc.reference:
                raise PixelError("Current project has no embedded references", code="REFERENCE_REQUIRED")
            context = self.doc.reference
        else:
            context = self.references.proposed(action, role, asset, payload.get("settings"))
        bound = self.references.summary(self.doc)["current_project_has_same_subject"]
        # Loading a different subject prepares a NEW job; it never retargets existing artwork.
        update_project = bound and not (action in ("load", "clear") and role == "subject")
        self.references.commit(context)
        if update_project:
            self.doc.apply([{"op": "reference_context", "data": context}], "调整参考图重绘设置", source=payload.get("source", "AI"))
            self.autosave()
        return self.reference_view("comparison" if payload.get("include_images", True) else "status")

    def cutout_action(self, payload, preview=False):
        self.guard(payload)
        self.references.guard(payload.get("expected_reference_revision"))
        context = self.references.context
        asset = context["subject"]
        if not asset:
            raise PixelError("先导入普通图片，再去背景", code="REFERENCE_REQUIRED")
        self.cutouts.sync(self.doc.id, context)
        if preview:
            base_settings = context.get("cutout") or {}
            if payload.get("base_preview_id"):
                base_settings = self.cutouts.ticket(payload["base_preview_id"], self.doc.id, self.doc.revision,
                                                    self.references.revision, asset["id"])["settings"]
            changes = payload.get("settings")
            if changes is not None and not isinstance(changes, dict):
                raise PixelError("Cutout settings must be an object")
            settings = {**base_settings, **(changes or {})}
            ticket_id, ticket = self.cutouts.preview(self.doc.id, self.doc.revision, self.references.revision,
                                                    asset, settings)
            result = {"ok": True, "dry_run": True, "preview_id": ticket_id, "expires_in_seconds": 300,
                      "document_id": self.doc.id, "revision": self.doc.revision,
                      "reference_revision": self.references.revision, "size": asset["size"],
                      "settings": ticket["settings"], "statistics": ticket["stats"],
                      "image_roles": [], "images_png": []}
            if payload.get("include_images", True):
                from .reference_ui_images import checker
                result["image_roles"] = ["original_reference", "cutout_on_checker", "removed_alpha_mask"]
                result["images_png"] = [encode_png(checker(decoded_asset(asset["png"]))),
                                        encode_png(checker(ticket["output"])), encode_png(ticket["mask"].convert("RGBA"))]
            return result
        action = payload.get("action", "apply")
        if action == "export":
            if context.get("cutout") is None:
                raise PixelError("先应用抠图预览，再导出透明 PNG")
            from .cutout import cutout_subject
            if not payload.get("path"):
                raise PixelError("Cutout export needs a local PNG path")
            target = self.resolve(payload["path"])
            if target.suffix.lower() != ".png":
                raise PixelError("Cutout export needs a .png filename")
            target.parent.mkdir(parents=True, exist_ok=True)
            if not isinstance(payload.get("overwrite", False), bool):
                raise PixelError("overwrite must be boolean")
            # Exclusive creation avoids silently replacing an original or another export.
            try:
                with target.open("wb" if payload.get("overwrite", False) else "xb") as output:
                    cutout_subject(asset, context["cutout"]).save(output, "PNG")
            except FileExistsError as exc:
                raise PixelError("目标文件已存在，请换一个名称或明确允许覆盖", code="FILE_EXISTS") from exc
            return {"ok": True, "path": str(target), "size": asset["size"], "original_preserved": True,
                    "document_id": self.doc.id, "revision": self.doc.revision, "reference_revision": self.references.revision,
                    "delivery_status": "processed_reference_not_artwork_review"}
        before = deepcopy(context.get("cutout"))
        if action == "apply":
            ticket = self.cutouts.ticket(payload.get("preview_id"), self.doc.id, self.doc.revision,
                                         self.references.revision, asset["id"])
            after = deepcopy(ticket["settings"])
        elif action == "reset":
            after = None
        elif action == "undo":
            if not self.cutouts.undo:
                raise PixelError("没有可撤销的抠图调整")
            after = deepcopy(self.cutouts.undo[-1][0])
        elif action == "redo":
            if not self.cutouts.redo:
                raise PixelError("没有可重做的抠图调整")
            after = deepcopy(self.cutouts.redo[-1][1])
        else:
            raise PixelError("Unknown cutout action")
        if before != after:
            proposed = deepcopy(context)
            if after is None:
                proposed.pop("cutout", None)
            else:
                proposed["cutout"] = after
            bound = self.references.summary(self.doc)["current_project_has_same_subject"]
            self.references.commit(proposed)
            if bound:
                labels = {"apply": "应用参考图抠图", "reset": "恢复原图背景", "undo": "撤销抠图调整", "redo": "重做抠图调整"}
                self.doc.apply([{"op": "reference_context", "data": proposed}], labels[action], source=payload.get("source", "AI"))
                self.autosave()
            if action == "undo":
                self.cutouts.redo.append(self.cutouts.undo.pop())
            elif action == "redo":
                self.cutouts.undo.append(self.cutouts.redo.pop())
            else:
                self.cutouts.undo.append((before, after))
                self.cutouts.undo = self.cutouts.undo[-20:]
                self.cutouts.redo.clear()
        return self.reference_view("comparison" if payload.get("include_images", True) else "status")

    def workspace_info(self):
        projects = sorted((self.workspace / "projects").glob("*.pixloom"), key=lambda path: path.stat().st_mtime, reverse=True)
        recoveries = sorted((self.runtime / "recovery").glob("*.pixloom"), key=lambda path: path.stat().st_mtime, reverse=True)
        return {"workspace": str(self.workspace), "projects_directory": str(self.workspace / "projects"),
                "exports_directory": str(self.workspace / "exports"), "recovery_directory": str(self.runtime / "recovery"),
                "recent_projects": [{"name": path.name, "path": str(path)} for path in projects[:20]],
                "project_library":self.projects.listing(self.path,page=0,limit=20),
                "project_library_paging":{"limit":20,"total":len(self.projects.scoped('open')),
                    "has_more":len(self.projects.scoped('open'))>20,"tool":"pixel_projects(action='list', page=...)"},
                "recovery_files": [{"name": path.name, "path": str(path)} for path in recoveries[:20]],
                "path_rules": "Relative paths resolve inside workspace. Existing exports need overwrite=true. Save the current project before opening another."}

    def review_evidence(self, payload):
        if self.view.get("gesture_active"):
            raise PixelError("Finish the current stroke before capturing review evidence",code="EDITOR_BUSY")
        if payload.get("review_id"):
            ticket = self.quality.ticket(payload["review_id"],self.doc)
        else:
            ticket = self.quality.start(self.doc,payload.get("tag"),payload.get("layers"))
        data, images = self.quality.evidence(ticket,payload.get("page",0))
        data["images_png"] = [encode_png(image) for image in images]
        return data

    def import_png(self, path):
        with Image.open(path) as original:
            if not 1 <= original.width <= 512 or not 1 <= original.height <= 512:
                raise PixelError("PNG dimensions must be 1–512 pixels; images are not silently rescaled")
            image = original.convert("RGBA")
        doc = Document(image.width, image.height, Path(path).stem)
        doc.layers[0].name = "Imported image"
        doc.layers[0].cels[0] = image
        colors = image.getcolors(image.width * image.height)
        if len(colors) <= 255:
            doc.palette = list(dict.fromkeys(["#00000000"] + [hexcolor(color) for _, color in sorted(colors, reverse=True)]))
        else:
            doc.strict_palette = False
        return doc

    def feedback_action(self, payload):
        """Shared desktop/MCP feedback route; marks never modify artwork."""
        action = payload.get("action", "list")
        if action == "list":
            return {"ok": True, **self.state(), "issues": feedback_summary(self.doc)["issues"]}
        if action == "inspect":
            if self.view.get("gesture_active"):
                raise PixelError("Finish the current stroke before inspecting feedback", code="EDITOR_BUSY")
            return self.feedback.inspect(self.doc, payload.get("issue_id"), payload.get("inspection_id"), payload.get("page", 0))
        self.guard(payload)
        source = "手动" if payload.get("source") == "手动" else "AI"
        if action == "create":
            issue = self.feedback.create(self.doc, payload.get("shape"), payload.get("frames"),
                                         payload.get("description"), source)
        else:
            issue = self.feedback.update(self.doc, action, payload.get("issue_id"), source,
                                         payload.get("text"), payload.get("direct_user_quote"), payload.get("inspection_id"))
        self.autosave()
        return {"ok": True, **self.state(), "issue": issue}

    def dispatch(self, method, path, query=None, payload=None):
        query, payload = query or {}, payload or {}
        value = lambda name, default=None: query.get(name, [default])[0]
        if method == "GET":
            if path=='/projects':
                return self.projects_action({'action':'list'}),JSON_TYPE
            if path == "/feedback":
                return self.feedback_action({"action": "list"}), JSON_TYPE
            if path == "/state":
                if value('if_revision') is not None and value('document_id')==self.doc.id and int(value('if_revision'))==self.doc.revision:
                    return {'document_id':self.doc.id,'revision':self.doc.revision,'unchanged':True,'capabilities':capabilities(),
                            'workflow_context':self.tasks.status(self.doc,brief=True)},JSON_TYPE
                state=self.state()
                return (compact_state(state) if value('compact')=='1' else state), JSON_TYPE
            if path == '/task':return {'ok':True,**self.tasks.status(self.doc)},JSON_TYPE
            if path == "/schema":
                if value("format") == "json-schema":
                    return full_schema(), JSON_TYPE
                return guide(value("topic", "overview"), value("operation")), JSON_TYPE
            if path == "/workspace":
                return self.workspace_info(), JSON_TYPE
            if path == "/reference":
                return self.reference_view(value("view", "comparison")), JSON_TYPE
            if path == "/inspect":
                rect = [int(item) for item in value("rect").split(",")] if value("rect") else None
                frame = int(value("frame")) if value("frame") is not None else None
                return self.doc.inspect(rect, value("layer"), frame, value("region")), JSON_TYPE
            if path in ("/preview.png", "/snapshot"):
                rect = [int(item) for item in value("rect").split(",")] if value("rect") else None
                frame = int(value("frame")) if value("frame") is not None else None
                try:
                    layers = json.loads(value("layers")) if value("layers") is not None else None
                except (ValueError, TypeError) as exc:
                    raise PixelError("layers must be a JSON array of layer ids or names") from exc
                frame=self.doc.active_frame if frame is None else integer(frame,'frame',0,len(self.doc.durations)-1)
                scale=integer(int(value('scale',8)),'scale',1,32)
                if rect is not None:self.doc.validate_rect(rect)
                selected=self.doc.rendering_layers(layers)
                scope={'document_id':self.doc.id,'size':[self.doc.width,self.doc.height],'frame':frame,'scale':scale,
                       'rect':rect,'checker':value('checker','1')!='0','layers':[l.id for l in selected] if layers is not None else None}
                digest=hashlib.sha256(json.dumps(scope,sort_keys=True).encode())
                for layer in selected:digest.update(part_key(self.doc,layer.id,frame).encode())
                image_key=digest.hexdigest()
                unchanged=path=='/snapshot' and value('if_image_key')==image_key
                encoded=None
                if not unchanged:
                    encoded=self.preview_cache.get(image_key)
                    if encoded is None:
                        image=self.doc.preview(frame,scale,rect,scope['checker'],layers=layers)
                        encoded=png_bytes(image)
                        if len(encoded)<=8_000_000:self.preview_cache[image_key]=encoded
                    else:self.preview_cache.move_to_end(image_key)
                    while len(self.preview_cache)>16 or sum(map(len,self.preview_cache.values()))>16_000_000:self.preview_cache.popitem(last=False)
                if layers is not None and len(selected)==1:
                    layer=selected[0];bbox=layer.cels[frame].getchannel('A').getbbox()
                    complete=rect is None or bbox is None or (rect[0]<=bbox[0] and rect[1]<=bbox[1] and rect[0]+rect[2]>=bbox[2] and rect[1]+rect[3]>=bbox[3])
                    receipt=(self.doc.id,layer.id,frame)
                    if complete and (not unchanged or self.part_receipts.get(receipt)==part_key(self.doc,layer.id,frame)):
                        self.part_receipts[receipt]=part_key(self.doc,layer.id,frame)
                        self.part_receipts.move_to_end(receipt)
                        while len(self.part_receipts)>256:self.part_receipts.popitem(last=False)
                if path == "/snapshot":
                    return {"document_id": self.doc.id, "revision": self.doc.revision,
                            "frame":frame,"scale":scale,"image_key":image_key,"unchanged":unchanged,
                            "layers": [layer.id for layer in selected] if layers is not None else None,
                            "image_roles": ["isolated_layer" if layers is not None and len(selected) == 1 else
                                            "selected_layer_group" if layers is not None else "visible_composite"],
                            **({'preview_png':base64.b64encode(encoded).decode('ascii')} if encoded is not None else {})}, JSON_TYPE
                return encoded, "image/png"
            if path in ("/contact-sheet.png", "/contact-snapshot"):
                frames = [int(item) for item in value("frames").split(",")] if value("frames") else None
                image = self.doc.contact_sheet(frames, value("tag"), int(value("columns", 6)),
                                               int(value("scale", 3)), value("labels", "1") != "0")
                if path == "/contact-snapshot":
                    return {"document_id": self.doc.id, "revision": self.doc.revision, "tag": value("tag"),
                            "preview_png": base64.b64encode(png_bytes(image)).decode("ascii")}, JSON_TYPE
                return png_bytes(image), "image/png"
            raise PixelError(f"Unknown read endpoint: {path}", code="NOT_FOUND")

        if path == '/storage':
            action=payload.get('action','status')
            if action=='status':return self.storage.status(),JSON_TYPE
            if action=='plan':return self.storage.plan(payload.get('settings'),payload.get('plan_id'),payload.get('page',0),payload.get('limit',20)),JSON_TYPE
            if action=='apply':return self.storage.apply(payload),JSON_TYPE
            raise PixelError('Unknown storage action')
        if path == '/material':
            return self.materials.action(self,payload),JSON_TYPE
        if path == '/material/present':
            self.materials.ticket(self.doc,payload.get('preview_id'))
            return {'ok':True,'presented':False,'reason':'Headless backend: inspect the returned material images.'},JSON_TYPE
        if path == "/character":
            from .character import action
            return action(self, payload), JSON_TYPE
        if path == "/motion/check":
            if self.view.get("gesture_active"):
                raise PixelError("Finish the active canvas gesture first", "GESTURE_ACTIVE")
            return self.motion.check(self.doc, payload), JSON_TYPE
        if path=='/task':
            if payload.get('action','status')=='status':return {'ok':True,**self.tasks.status(self.doc)},JSON_TYPE
            self.guard(payload)
            result=self.tasks.update(self.doc,payload,self.part_receipts,self.quality)
            return {'ok':True,'document_id':self.doc.id,'revision':self.doc.revision,**result},JSON_TYPE
        if path=='/art/board':
            from .art_direction import board
            return board(self,payload),JSON_TYPE
        if path=='/generation':
            return self.generation.action(self,payload),JSON_TYPE
        if path=='/projects':
            return self.projects_action(payload),JSON_TYPE
        if path == "/feedback":
            return self.feedback_action(payload), JSON_TYPE
        if path == "/review/evidence":
            return self.review_evidence(payload),JSON_TYPE
        if path == "/review/present":
            self.quality.ticket(payload["review_id"],self.doc)
            return {"ok":True,"presented":False,"reason":"Headless backend: inspect the returned image evidence and playback asset."},JSON_TYPE
        if path == "/review/settings":
            self.guard(payload)
            mode=payload.get("mode","merge");tag=payload.get('tag')
            policy = update_policy(self.doc,payload['settings'],mode,tag)
            self.doc.apply([{"op":"quality_policy","data":policy}],"设置成品自检要求",source=payload.get("source","AI"))
            self.autosave()
            return {"ok":True,**self.state(),"settings_mode":mode,"updated_fields":sorted(payload["settings"]),
                    "settings_scope":{"tag":tag},"effective_policy":effective_policy(self.doc,tag)},JSON_TYPE
        if path == "/review/submit":
            self.guard(payload)
            record = self.quality.submit(self.doc,payload["review_id"],payload["visual_checks"],payload.get("warning_resolutions",[]),
                                         payload["method"],payload["summary"])
            self.autosave()
            return {"ok":True,**self.state(),"review":record},JSON_TYPE
        if path == "/reference/setup":
            return self.reference_setup(payload), JSON_TYPE
        if path == "/reference/cutout/preview":
            return self.cutout_action(payload, preview=True), JSON_TYPE
        if path == "/reference/cutout":
            return self.cutout_action(payload), JSON_TYPE
        if path == "/reference/preview":
            self.guard(payload)
            self.references.guard(payload.get("expected_reference_revision"))
            proposed = Document.from_dict(self.doc.to_dict())
            proposed.apply(payload["ops"], "参考图重绘预览", source="AI")
            return self.reference_view("comparison", proposed), JSON_TYPE
        request_id = payload.get("request_id") if path == "/command" else None
        signature = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if request_id:
            if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
                raise PixelError("request_id must contain 1–128 characters")
            cached = self.requests.get(request_id)
            if cached:
                if cached["signature"] != signature:
                    raise PixelError("This request_id was already used for a different request", code="REQUEST_ID_REUSED")
                result = {"ok": True, **self.state(), "replayed": True, "original_revision": cached["revision"]}
                if payload.get("include_preview"):
                    result["preview_png"] = self.encoded_preview()
                return result, JSON_TYPE
        self.guard(payload)
        if path == "/validate":
            proposed = Document.from_dict(self.doc.to_dict())
            proposed.apply(payload["ops"], payload.get("label", "Dry run"), source="AI")
            result = {"ok": True, "dry_run": True, "base_revision": self.doc.revision,
                      "document_id": self.doc.id, "proposed_state": proposed.state(), "changes": proposed.last_change}
            if payload.get("include_preview", True):
                scale = min(8, max(1, 768 // max(proposed.width, proposed.height)))
                result["preview_png"] = base64.b64encode(png_bytes(proposed.preview(scale=scale))).decode("ascii")
            return result, JSON_TYPE
        if path == "/command":
            self.doc.apply(payload["ops"], payload.get("label", "AI drawing"), payload["expected_revision"],
                           payload["expected_document_id"], source="AI")
            if any(op.get("op") == "reference_context" for op in payload["ops"]):
                self.restore_reference()
            if request_id:
                self.requests[request_id] = {"signature": signature, "revision": self.doc.revision}
                while len(self.requests) > 256:
                    self.requests.popitem(last=False)
        elif path in ("/undo", "/redo"):
            changed = getattr(self.doc, path[1:])()
            if not changed:
                return {"ok": True, **self.state(), "changed": False}, JSON_TYPE
            self.restore_reference()
        elif path == "/redraw/begin":
            self.references.guard(payload.get("expected_reference_revision"))
            doc = new_redraw_document(self.references.context, payload.get("name", "像素底稿"),
                                      payload.get("seed", False), payload.get("mode", "draft"))
            self.replace(doc, discard_changes=payload.get("discard_changes", False))
            # Even a blank redraw contains imported references and must be saved before replacement.
            self.saved_fingerprint = ""
        elif path == "/new":
            self.replace(Document(payload.get("width", 48), payload.get("height", 48), payload.get("name", "Untitled")),
                         discard_changes=payload.get("discard_changes", False))
        elif path in ("/open", "/import"):
            target = self.resolve(payload["path"])
            doc = self.import_png(target) if path == "/import" else Document.open(target)
            self.replace(doc, None if path == "/import" else target, payload.get("discard_changes", False))
        elif path == "/save":
            self.save_project(payload.get('path'),payload.get('overwrite',False))
        elif path == "/export":
            target = self.resolve(payload["path"])
            kind = payload.get("kind", "png")
            suffix = ".gif" if kind == "gif" else ".png"
            if target.suffix.lower() != suffix:
                raise PixelError(f"{kind} export needs a {suffix} filename")
            sheet_format=payload.get('sheet_format','native')
            outputs = export_paths(target,kind,sheet_format)
            check_sidecars(target,kind,sheet_format)
            if any(output.exists() for output in outputs) and not payload.get("overwrite", False):
                raise PixelError("Export already exists. Choose a new name or explicitly set overwrite=true.", code="FILE_EXISTS")
            draft = payload.get("draft",False)
            if not isinstance(draft,bool):
                raise PixelError("draft must be boolean")
            if not draft:self.tasks.check_delivery(self.doc)
            record = None if draft else self.quality.require_pass(self.doc,payload.get("tag"),payload.get("layers"),
                                                                 self.doc.active_frame if kind=="png" else None,continuous=kind=='gif')
            doc = self.doc
            if payload.get("layers") is not None:
                doc = Document.from_dict(self.doc.to_dict())
                included = {doc.layer(target_layer).id for target_layer in payload["layers"]}
                for layer in doc.layers:
                    layer.visible = layer.id in included
            result = doc.export(target, kind, payload.get("scale", 1), payload.get("columns"), payload.get("tag"),
                                loop=effective_policy(self.doc,payload.get('tag'))['loop'],sheet_format=sheet_format)
            return {"ok": True, **result, "revision": self.doc.revision, "tag": payload.get("tag"),
                    "draft_export":draft,"delivery_status":"unreviewed_draft" if draft else "reviewed_final",
                    "review_id":record["review_id"] if record else None,
                    'review_ids':record['review_ids'] if record else [],
                    'review_coverage':record['coverage'] if record else []}, JSON_TYPE
        elif path == "/shutdown":
            if self.dirty and not payload.get("discard_changes", False):
                raise PixelError("Save the current project before closing", code="UNSAVED_CHANGES")
            self.closing = True
        else:
            raise PixelError(f"Unknown write endpoint: {path}", code="NOT_FOUND")
        view_only = path == "/command" and all(op["op"] in ("select", "selection_set") for op in payload["ops"])
        if not view_only:
            self.autosave()
        result = {"ok": True, **self.state()}
        if path == "/redraw/begin" or path == "/command" and payload.get("include_preview"):
            result["preview_png"] = self.encoded_preview()
        return result, JSON_TYPE

    def encoded_preview(self):
        scale = min(8, max(1, 768 // max(self.doc.width, self.doc.height)))
        return base64.b64encode(png_bytes(self.doc.preview(scale=scale))).decode("ascii")
