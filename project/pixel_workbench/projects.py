"""Persistent project shelf and non-destructive saved-version history."""
from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import uuid

from .model import Document, PixelError, atomic_json


def path_key(path):
    return os.path.normcase(str(Path(path).resolve()))


def file_digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(path, root):
    """Reject redirects and paths outside the exact managed cleanup directory."""
    path, root = Path(path).absolute(), Path(root).resolve()
    if not path.is_relative_to(root):raise PixelError('Cleanup path is outside its managed directory')
    for item in (path, *path.parents):
        if item.exists() or item.is_symlink():
            attributes = item.lstat()
            if stat.S_ISLNK(attributes.st_mode) or getattr(attributes,'st_file_attributes',0) & 1024:
                raise PixelError('Cleanup skips symbolic links and directory redirects')
        if item == root:break
    if not path.resolve().is_relative_to(root):raise PixelError('Cleanup path escaped its directory')
    return path


def frame_at(doc, time_ms):
    phase = max(0, int(time_ms)) % sum(doc.durations)
    for frame, duration in enumerate(doc.durations):
        if phase < duration:
            return frame
        phase -= duration
    return 0


class ProjectLibrary:
    def __init__(self, runtime, workspace):
        self.runtime, self.workspace = Path(runtime), Path(workspace)
        self.catalog = self.runtime / 'project-library.json'
        self.entries = []
        self.next_number = 1
        if self.catalog.exists():
            data = json.loads(self.catalog.read_text(encoding='utf-8'))
            if data.get('format') != 'pixel-loom/projects/v1' or not isinstance(data.get('projects'), list):
                raise PixelError('Invalid project library; keep its file for recovery')
            self.entries = data['projects']
            if any(not isinstance(entry,dict) or not re.fullmatch(r'[0-9a-f]{32}',str(entry.get('id','')))
                   or not isinstance(entry.get('path'),str) for entry in self.entries):
                raise PixelError('Invalid project library entry; keep its file for recovery')
            self.next_number=max(data.get('next_number',1),max((e.get('number',0) for e in self.entries),default=0)+1)

    def persist(self):
        atomic_json(self.catalog, {'format': 'pixel-loom/projects/v1', 'projects': self.entries,'next_number':self.next_number})

    def by_path(self, path):
        return next((entry for entry in self.entries if path_key(entry['path']) == path_key(path)), None)

    def get(self, project_id, include_deleted=False):
        if project_id is None:
            raise PixelError('An observed project_id is required; it is not the document_id.',code='PROJECT_NOT_FOUND',
                recovery='Read pixel_status(compact=True).project_library.active.id for the current saved project, or pixel_projects(action="list"); pass that project_id. Save/register an unsaved project before reading its retained versions.')
        entry = next((entry for entry in self.entries if entry['id'] == project_id), None)
        if entry is None:
            raise PixelError('Project not found. Read pixel_projects list.', code='PROJECT_NOT_FOUND')
        if entry.get('deleted_at') and not include_deleted:
            raise PixelError('Project is deleted from the shelf. Use pixel_projects undelete to restore it.',code='PROJECT_DELETED')
        return entry

    def register(self, path, doc=None, parent_id=None):
        path = Path(path).resolve()
        doc = doc or Document.open(path)
        entry = self.by_path(path)
        if entry is None:
            entry = {'id': uuid.uuid4().hex, 'number': self.next_number, 'path': str(path),
                     'parent_id': parent_id, 'created_at': datetime.now(timezone.utc).isoformat()}
            self.entries.append(entry)
            self.next_number+=1
        entry.update(name=doc.name, document_id=doc.id, width=doc.width, height=doc.height,
                     frames=len(doc.durations), duration_ms=sum(doc.durations), disk_sha256=file_digest(path))
        entry.pop('deleted_at',None)  # Explicitly opening/adding its file restores the same project identity.
        entry.pop('closed_at',None)   # Re-adding a file reopens its tab as well.
        self.persist()
        # Edits made before the first Save belong to this project too.
        pending = self.draft_history(doc.id)
        if pending.exists():
            destination = self.history_folder(entry)
            destination.mkdir(parents=True, exist_ok=True)
            for item in pending.iterdir():
                target = destination / item.name
                if not target.exists():
                    shutil.copy2(item, target)
            for item in pending.iterdir():
                item.unlink()
            pending.rmdir()
        return entry

    def scoped(self, scope='open'):
        """Shelf membership: open tabs, closed tabs and removed projects are disjoint."""
        if scope == 'deleted':
            return [e for e in self.entries if e.get('deleted_at')]
        if scope == 'closed':
            return [e for e in self.entries if e.get('closed_at') and not e.get('deleted_at')]
        return [e for e in self.entries if not e.get('deleted_at') and not e.get('closed_at')]

    def listing(self, active_path=None, deleted=False, page=None, limit=20, closed=False):
        active = path_key(active_path) if active_path else None
        entries=self.scoped('deleted' if deleted else 'closed' if closed else 'open')
        if page is not None:entries=entries[page*limit:(page+1)*limit]
        return [{**entry, 'active': path_key(entry['path']) == active,
                 'closed': bool(entry.get('closed_at')),
                 'available': Path(entry['path']).is_file()} for entry in entries]

    def set_deleted(self, project_ids, deleted=True):
        if not isinstance(project_ids,list) or not 1<=len(project_ids)<=256 or any(not isinstance(key,str) for key in project_ids):
            raise PixelError('Choose 1–256 project ids')
        selected=[self.get(key,include_deleted=not deleted) for key in dict.fromkeys(project_ids)]
        previous=deepcopy(self.entries)
        stamp=datetime.now(timezone.utc).isoformat()
        try:
            for entry in selected:
                if deleted:
                    entry['deleted_at']=stamp
                    entry.pop('closed_at',None)  # A removed project is not also a closed tab.
                else:entry.pop('deleted_at',None)
            self.persist()
        except (OSError,ValueError):
            self.entries=previous
            raise
        return selected

    def set_closed(self, project_ids, closed=True):
        """Hide shelf tabs; the project file, its versions and its id are untouched."""
        if not isinstance(project_ids,list) or not 1<=len(project_ids)<=256 or any(not isinstance(key,str) for key in project_ids):
            raise PixelError('Choose 1–256 project ids')
        selected=[self.get(key) for key in dict.fromkeys(project_ids)]
        previous=deepcopy(self.entries)
        stamp=datetime.now(timezone.utc).isoformat()
        try:
            for entry in selected:
                if closed:entry['closed_at']=stamp
                else:entry.pop('closed_at',None)
            self.persist()
        except (OSError,ValueError):
            self.entries=previous
            raise
        return selected

    def new_path(self, name):
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', str(name)).strip(' .')[:70] or 'project'
        if stem.upper().split('.')[0] in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
            stem = 'project-' + stem
        folder = self.workspace / 'projects'
        folder.mkdir(parents=True, exist_ok=True)
        while True:
            path = folder / f'{stem}-{uuid.uuid4().hex[:10]}.pixloom'
            if not path.exists():
                return path

    def history_folder(self, entry):
        return self.runtime / 'project-history' / entry['id']

    def draft_history(self, document_id):
        key = hashlib.sha256(str(document_id).encode()).hexdigest()
        return self.runtime / 'iteration-drafts' / key

    def record_iteration(self, doc, path=None, label=None, source=None):
        """Persist complete editable batches, independently of the 40-step undo stack."""
        entry = self.by_path(path) if path else None
        folder = self.history_folder(entry) if entry else self.draft_history(doc.id)
        folder.mkdir(parents=True, exist_ok=True)
        previous = sorted(folder.glob('*.pixloom'), reverse=True)
        if previous:
            try:
                info = json.loads(previous[0].with_suffix('.json').read_text(encoding='utf-8'))
                previous_fingerprint = info['fingerprint']
            except (OSError, ValueError, KeyError, TypeError):
                previous_fingerprint = Document.open(previous[0]).fingerprint()
            if previous_fingerprint == doc.fingerprint():
                return None  # Reads, view changes, repeated saves and retries are not new iterations.
        number = len(previous)+1
        if previous:
            try:number = max(number,int(info.get('number',0))+1)
            except (TypeError,ValueError,UnboundLocalError):pass
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = folder / f'{stamp}-{uuid.uuid4().hex}.pixloom'
        doc.save(target)
        event = doc.events[-1] if doc.events else {}
        atomic_json(target.with_suffix('.json'), {
            'number': number, 'pinned': False,
            'label': str(label or event.get('label') or '初始版本')[:200],
            'source': str(source or event.get('source') or '保存')[:80],
            'saved_at': datetime.now(timezone.utc).isoformat(), 'revision': doc.revision,
            'width': doc.width, 'height': doc.height, 'frames': len(doc.durations),
            'duration_ms': sum(doc.durations), 'fingerprint': doc.fingerprint(), 'sha256': file_digest(target)})
        return target

    def versions(self, project_id, page=None, limit=20, include_deleted=False):
        entry = self.get(project_id,include_deleted=include_deleted)
        folder = self.history_folder(entry)
        result = []
        paths = sorted(folder.glob('*.pixloom'))
        numbered = list(enumerate(paths,1))[::-1]
        if page is not None:numbered = numbered[page*limit:(page+1)*limit]
        for number, path in numbered:
            try:
                info = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
            except (OSError, ValueError):
                info = {}
            if not isinstance(info,dict):info = {}
            stable_number = info.get('number',number)
            if type(stable_number) is not int or stable_number<1:stable_number=number
            result.append({**info, 'id': path.stem, 'path': str(path), 'number': stable_number,
                           'pinned': info.get('pinned') is True,
                           'saved_at': info.get('saved_at', path.stem.split('-')[0]),
                           'label': info.get('label', '旧版保存备份'), 'source': info.get('source', '保存'),
                           'bytes': path.stat().st_size})
        return result

    def freeze_version_numbers(self, project_id, exclude=()):
        for version in self.versions(project_id,include_deleted=True):
            if version['id'] in exclude:continue
            path=checked_path(version['path'],self.history_folder(self.get(project_id,include_deleted=True)))
            metadata=path.with_suffix('.json')
            checked_path(metadata,self.history_folder(self.get(project_id,include_deleted=True)))
            try:info=json.loads(metadata.read_text(encoding='utf-8'))
            except (OSError,ValueError):info={}
            if not isinstance(info,dict):info={}
            if info.get('number')!=version['number']:
                atomic_json(metadata,{**info,'number':version['number']})

    def pin_version(self, project_id, version_id, pinned):
        if type(pinned) is not bool:raise PixelError('pinned must be boolean')
        path=checked_path(self.version_path(project_id,version_id),self.history_folder(self.get(project_id)))
        self.freeze_version_numbers(project_id)
        metadata=checked_path(path.with_suffix('.json'),self.history_folder(self.get(project_id)))
        info=json.loads(metadata.read_text(encoding='utf-8'))
        atomic_json(metadata,{**info,'pinned':pinned})
        return {'id':version_id,'pinned':pinned}

    def version_path(self, project_id, version_id):
        if not isinstance(version_id,str) or not re.fullmatch(r'[0-9]{8}T[0-9]{12}Z-[0-9a-f]{32}(?:[0-9a-f]{32})?',version_id):
            raise PixelError('Saved version not found', code='VERSION_NOT_FOUND')
        path=self.history_folder(self.get(project_id))/f'{version_id}.pixloom'
        if not path.is_file():raise PixelError('Saved version not found',code='VERSION_NOT_FOUND')
        return checked_path(path,self.history_folder(self.get(project_id)))

    def backup(self, path, project_id=None):
        """Capture the existing file before any overwrite, deduplicated by its bytes."""
        path = Path(path)
        if not path.exists():
            return None
        entry = self.get(project_id) if project_id else self.by_path(path) or self.register(path)
        digest = file_digest(path)
        folder = self.history_folder(entry)
        folder.mkdir(parents=True, exist_ok=True)
        fingerprint = Document.open(path).fingerprint()
        for metadata in folder.glob('*.json'):
            try:
                if (json.loads(metadata.read_text(encoding='utf-8')).get('fingerprint') == fingerprint
                        and metadata.with_suffix('.pixloom').is_file()):
                    return None
            except (OSError, ValueError):
                continue
        if any(folder.glob(f'*-{digest}.pixloom')):
            return None
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = folder / f'{stamp}-{digest}.pixloom'
        shutil.copy2(path, target)
        return target

    def check_external_change(self, path):
        entry = self.by_path(path)
        if entry and (not Path(path).is_file() or file_digest(path) != entry['disk_sha256']):
            raise PixelError('Project file changed outside the editor. Save to a new path or reopen it first.',
                             code='PROJECT_FILE_CHANGED')
