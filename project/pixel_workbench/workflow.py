"""Task routing, bounded local work notes and compact read views; never paints art."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Literal
from typing_extensions import TypedDict

from .model import PixelError, atomic_json, integer

API_REVISION = 2
WORKFLOW_REVISION = "static-layers-1"
TaskKind = Literal['text_static','image_static','edit_static','layer_completion','animation']
Stage = Literal['analyze','static','separate','complete','animate','inspect','deliver']

ROUTES = {
    'text_static': {'title':'文字静态创作','help':'text_workflow','stages':['analyze','static','separate','inspect','deliver']},
    'image_static': {'title':'图片转静态像素','help':'image_workflow','stages':['analyze','static','separate','inspect','deliver']},
    'edit_static': {'title':'已有作品局部修改','help':'workflow','stages':['analyze','static','separate','inspect','deliver']},
    'layer_completion': {'title':'按需补齐图层','help':'completion_workflow','stages':['analyze','complete','inspect','deliver']},
    'animation': {'title':'按需制作动画','help':'animation_workflow','stages':['analyze','static','separate','animate','inspect','deliver']},
}

class PartNote(TypedDict, total=False):
    layer: str
    frame: int
    extraction: Literal['pending','clean','needs_repair']
    hidden: Literal['not_requested','not_needed','unfilled','complete','needs_repair']
    note: str

def capabilities():
    return {'api_revision':API_REVISION,'workflow_revision':WORKFLOW_REVISION,
            'features':['task_context','compact_reads','conditional_preview','isolated_preview','polygon_copy','review_settings_modes',
                        'tag_review','combined_review_export','engine_export_formats','art_direction','generation_handoff','generation_handoff_v2',
                        'conditional_generation_source','material_lighting'],
            'sheet_formats':['native','aseprite_hash','aseprite_array','godot']}

def route(task=None):
    if task is not None and task not in ROUTES:raise PixelError('Unknown workflow task')
    if task is None:
        return {'task':None,'choose_from':{k:v['title'] for k,v in ROUTES.items()},
                'read_next':{'tool':'pixel_help','arguments':{'topic':'workflow'}}}
    r=deepcopy(ROUTES[task])
    return {'task':task,**r,'read_next':{'tool':'pixel_help','arguments':{'topic':r['help']}},
            'optional_art_direction':{'tool':'pixel_help','arguments':{'topic':'art_direction'}},
            'defaults':{'static_first':True,'semantic_layers':True,
                        'completion':'only requested layers','animation':'only on human request',
                        'background_removal':'optional; object separation retains background separately'},
            'record_next':"pixel_task(action='plan', task=..., brief=..., expected_task_revision=0, observed document/revision) on the intended project; image_static starts after the faithful draft exists."}

def compact_state(state):
    """An opt-in view. Legacy full responses and all existing field meanings survive."""
    keep=('ok','document_id','revision','name','width','height','active_layer','active_frame','unsaved_changes',
          'app_version','project_path','workspace','selection','can_undo','can_redo','dry_run','base_revision','original_revision','replayed','capabilities','workflow_context')
    result={k:deepcopy(state[k]) for k in keep if k in state}
    if 'layers' in state:
        result['layers']=[{k:deepcopy(v) for k,v in item.items() if k in ('id','name','visible','locked','opacity','bounds')} for item in state['layers']]
    if 'palette' in state:result['palette_size']=len(state['palette'])
    if 'frames' in state:
        frames=state['frames']; result['frame_count']=len(frames)
        index=state.get('active_frame',0)
        if frames and 0<=index<len(frames):result['active_duration_ms']=frames[index]['duration_ms']
    if 'quality_review' in state:
        result['quality_review']={k:deepcopy(v) for k,v in state['quality_review'].items() if k in ('status','next_action','pending_issue_ids')}
    if 'material' in state:
        result['material']={k:deepcopy(v) for k,v in state['material'].items() if k in ('configured','normal_frames','normal_origin','warnings','help')}
    if 'reference_workflow' in state:
        ref=state['reference_workflow']
        result['reference_revision']=ref.get('reference_revision')
        result['subject']=deepcopy(ref.get('subject'))
    if state.get('project_library'):
        lib=state['project_library']; active=lib.get('active')
        result['project_library']={'count':lib.get('count'),'active':{k:active[k] for k in ('id','name','path') if k in active} if active else None}
    for key in ('projects','project_list_paging','page','pages','total','limit','has_more','versions','read_only',
                'items','image_roles','project_id','version_id','version','view','time_ms','history_preserved','files_preserved','changed_project_ids','changes'):
        if key in state:result[key]=deepcopy(state[key])
    if 'proposed_state' in state:result['proposed_state']=compact_state(state['proposed_state'])
    result['detail']='summary'
    result['expand']="pixel_status() for palette, frame durations, regions and full reference/review state"
    return result


def compact_action_reply(state, action=None):
    """Opt-in write receipts: retain outcomes/guards, not the unchanged whole document."""
    keep=('ok','document_id','revision','name','width','height','active_layer','active_frame','unsaved_changes',
          'app_version','project_path','can_undo','can_redo','settings_mode','settings_scope','updated_fields','effective_policy')
    result={k:deepcopy(state[k]) for k in keep if k in state}
    if 'layers' in state:result['layer_count']=len(state['layers'])
    if 'frames' in state:result['frame_count']=len(state['frames'])
    if 'palette' in state:result['palette_size']=len(state['palette'])
    active=state.get('project_library',{}).get('active')
    if active:result['project_id']=active['id']
    if 'quality_review' in state:
        result['quality_review']={k:deepcopy(v) for k,v in state['quality_review'].items()
            if k in ('status','next_action','pending_issue_ids','summary')}
        coverage=state['quality_review'].get('coverage')
        if isinstance(coverage,dict):
            result['quality_review']['coverage']={k:deepcopy(coverage[k]) for k in
                ('passed','missing_tags','missing_frames','technical_failures') if k in coverage}
    feedback=state.get('feedback')
    if isinstance(feedback,dict):
        result['feedback']={k:deepcopy(v) for k,v in feedback.items() if k!='issues'}
    if 'issues' in state:
        result['issues']=deepcopy(state['issues'])
    elif action=='list' and isinstance(feedback,dict) and 'issues' in feedback:
        result['issues']=deepcopy(feedback['issues'])
    if 'issue' in state:result['issue']=deepcopy(state['issue'])
    if 'review' in state:
        review=state['review']
        result['review']={k:deepcopy(v) for k,v in review.items() if k in
            ('review_id','status','scope','method','summary','next_action','round','round_budget_reached')}
        result['review']['remaining_findings']=[deepcopy(v) for v in review.get('visual_checks',[])
            if v.get('verdict')!='pass']+[deepcopy(v) for v in review.get('warning_resolutions',[])
            if v.get('verdict')!='acceptable']
    result['detail']='receipt'
    result['expand']='pixel_status() for full document state; compact=False retains the legacy full reply.'
    return result

def part_key(doc,layer,frame=0):
    layer=doc.layer(layer); frame=integer(frame,'frame',0,len(doc.durations)-1)
    h=hashlib.sha256(json.dumps([doc.id,doc.width,doc.height,layer.id,layer.opacity,frame]).encode())
    h.update(layer.cels[frame].tobytes())
    return h.hexdigest()

def image_key(doc):
    return hashlib.sha256(doc.composite(0).tobytes()).hexdigest()

def palette_key(doc):
    return hashlib.sha256(json.dumps(sorted(doc.palette)).encode()).hexdigest()

def _text(value,name,maximum):
    if not isinstance(value,str) or len(value)>maximum:raise PixelError(f'{name} must be text of at most {maximum} characters')
    return value.strip()

class TaskStore:
    """Separate local notes, like project history; no new .pixloom format or art undo steps."""
    def __init__(self,runtime):self.folder=Path(runtime)/'workflow-context'

    def path(self,doc):return self.folder/(hashlib.sha256(doc.id.encode()).hexdigest()+'.json')

    def load(self,doc):
        p=self.path(doc)
        if not p.exists():return {'revision':0,'context':None}
        try:
            if p.stat().st_size>65536:raise ValueError('Oversized context')
            v=json.loads(p.read_text(encoding='utf-8'))
            if v.get('format')!='pixel-loom/task/v1' or v.get('document_id')!=doc.id:raise ValueError('Wrong context identity/format')
            integer(v.get('revision'),'task revision',0)
            c=v.get('context')
            if c is not None:
                if not isinstance(c,dict) or c.get('task') not in ROUTES or not isinstance(c.get('parts'),list) or len(c['parts'])>64:raise ValueError('Invalid context')
                if not all(k in c for k in ('stage','next_action','brief','baseline','completion_scope')):raise ValueError('Incomplete context')
                if not isinstance(c['completion_scope'],list) or any(not isinstance(x,str) for x in c['completion_scope']):raise ValueError('Invalid scope')
                if c.get('direction'):
                    from .art_direction import validate_direction
                    validate_direction(c['direction'])
                for part in c['parts']:
                    if not isinstance(part,dict) or not all(k in part for k in ('layer','frame','extraction','hidden')):raise ValueError('Invalid part')
                    if not isinstance(part['layer'],str):raise ValueError('Invalid layer id')
                    integer(part['frame'],'part frame',0,255)
                    if part['extraction'] not in ('pending','clean','needs_repair') or part['hidden'] not in ('not_requested','not_needed','unfilled','complete','needs_repair'):raise ValueError('Invalid part state')
            return v
        except (OSError,ValueError,TypeError,AttributeError) as e:
            raise PixelError('Local workflow notes are unreadable; keep the file for recovery.',code='TASK_CONTEXT_INVALID') from e

    def status(self,doc,brief=False):
        v=self.load(doc); c=deepcopy(v['context'])
        if c is None:return {'task_revision':v['revision'],'context':None}
        pending=[]
        for part in c['parts']:
            try:
                layer=doc.layer(part['layer'])
                part['current']=part.get('checked_key')==part_key(doc,layer.id,part.get('frame',0))
                part['name']=layer.name
            except (ValueError,KeyError):part['current']=False;part['missing']=True
            if (part['extraction']!='clean' or not part['current'] or part['hidden']=='needs_repair' or
                    (part['layer'] in c['completion_scope'] and part['hidden']!='complete')):pending.append(part['layer'])
            part.pop('checked_key',None)
        recorded={p['layer'] for p in c['parts']}
        pending.extend(layer for layer in c['completion_scope'] if layer not in recorded)
        if c['task'] in ('text_static','image_static'):
            pending.extend(layer.id for layer in doc.layers if layer.visible and layer.opacity and layer.cels[0].getchannel('A').getbbox() and layer.id not in recorded)
        if brief:
            direction=c.get('direction')
            c={k:c[k] for k in ('task','stage','next_action')}
            c['part_count']=len(v['context']['parts']); c['needs_check']=list(dict.fromkeys(pending))[:16]
            if direction:
                from .art_direction import summary
                c['direction']=summary(direction,doc)
        return {'task_revision':v['revision'],'context':c,'assessment':'AI-reported semantic checks, not automatic segmentation or visual certification'}

    def update(self,doc,payload,receipts,quality):
        old=self.load(doc)
        if integer(payload.get('expected_task_revision'),'expected_task_revision',0)!=old['revision']:
            raise PixelError('Workflow notes changed. Read pixel_task status and re-plan.',code='TASK_REVISION_CONFLICT')
        action=payload.get('action','status')
        if action=='clear':context=None
        elif action in ('plan','update'):
            if action=='plan':
                task=payload.get('task')
                if task not in ROUTES:raise PixelError('Choose an observed workflow task')
                if task in ('text_static','image_static') and len(doc.durations)!=1:
                    raise PixelError('A new static task needs a separate single-frame project; preserve the animation.',code='STATIC_TASK_REQUIRES_SINGLE_FRAME')
                context={'task':task,'stage':'analyze','brief':'','next_action':'','parts':[],'completion_scope':[],
                         'baseline':{'size':[doc.width,doc.height],'frames':len(doc.durations),'palette':palette_key(doc),'image':image_key(doc)}}
            else:
                if old['context'] is None:raise PixelError('Plan a workflow first')
                context=deepcopy(old['context'])
                if payload.get('task') is not None:raise PixelError('Use plan to change the task')
            for k,limit in [('brief',1200),('next_action',300)]:
                if payload.get(k) is not None:context[k]=_text(payload[k],k,limit)
            if not context['brief']:raise PixelError('Provide a short brief based on the real human request')
            if 'direction' in payload:
                from .art_direction import validate_direction
                direction=validate_direction(payload['direction'],doc)
                if direction:context['direction']=direction
                else:context.pop('direction',None)
            if payload.get('completion_scope') is not None:
                scope=payload['completion_scope']
                if not isinstance(scope,list) or len(scope)>64 or any(not isinstance(x,str) or not x or len(x)>120 for x in scope):raise PixelError('Invalid completion_scope')
                if scope and context['task'] not in ('layer_completion','animation'):raise PixelError('Static extraction does not authorize hidden-area completion')
                context['completion_scope']=list(dict.fromkeys(doc.layer(x).id for x in scope))
            if context['task']=='layer_completion' and not context['completion_scope']:raise PixelError('Name the layers the human asked to complete')
            if payload.get('stage') is not None:
                stage=payload['stage']; allowed=ROUTES[context['task']]['stages']
                if stage not in allowed and not(stage=='complete' and context['task']=='animation' and context['completion_scope']):
                    raise PixelError('This stage is outside the selected task. Completion and animation require their own human request.',code='TASK_SCOPE_CONFLICT')
                context['stage']=stage
            if payload.get('parts') is not None:
                parts=payload['parts']
                if not isinstance(parts,list) or len(parts)>64:raise PixelError('At most 64 part records')
                checked=[];seen=set()
                for raw in parts:
                    if not isinstance(raw,dict) or set(raw)-{'layer','frame','extraction','hidden','note'}:raise PixelError('Invalid part record')
                    layer=_text(raw.get('layer'),'layer',120);frame=integer(raw.get('frame',0),'frame',0,len(doc.durations)-1)
                    layer=doc.layer(layer).id
                    ex=raw.get('extraction','pending'); hidden=raw.get('hidden','not_requested')
                    if not layer or (layer,frame) in seen or ex not in ('pending','clean','needs_repair') or hidden not in ('not_requested','not_needed','unfilled','complete','needs_repair'):raise PixelError('Invalid or duplicate part state')
                    seen.add((layer,frame))
                    part={'layer':layer,'frame':frame,'extraction':ex,'hidden':hidden,'note':_text(raw.get('note',''),'note',240)}
                    if hidden=='complete' and layer not in context['completion_scope']:raise PixelError('Completion was not requested for this layer',code='TASK_SCOPE_CONFLICT')
                    if ex=='clean' or hidden=='complete':
                        actual=doc.layer(layer);key=part_key(doc,layer,frame)
                        if not actual.cels[frame].getchannel('A').getbbox():raise PixelError('An empty layer is not a clean extracted object')
                        if receipts.get((doc.id,actual.id,frame))!=key:
                            raise PixelError('Inspect this complete isolated layer with pixel_preview before marking it clean/complete.',code='PART_PREVIEW_REQUIRED')
                        part['layer']=actual.id;part['checked_key']=key
                    checked.append(part)
                context['parts']=checked
            if context['stage']=='deliver':
                self.check_delivery(doc,context)
                if quality.summary(doc).get('status')!='passed':
                    raise PixelError('Finish the existing pixel_review visual evidence checks before marking delivered.',code='QUALITY_REVIEW_REQUIRED')
        else:raise PixelError('Unknown task action')
        value={'format':'pixel-loom/task/v1','document_id':doc.id,'revision':old['revision']+1,'context':context}
        if len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8'))>65536:
            raise PixelError('Workflow summary exceeds 64 KiB; shorten the brief/part notes',code='TASK_CONTEXT_TOO_LARGE')
        self.folder.mkdir(parents=True,exist_ok=True);atomic_json(self.path(doc),value)
        return self.status(doc)

    def check_delivery(self,doc,context=None):
        c=context if context is not None else self.load(doc)['context']
        if c is None:return
        task=c['task'];parts=c['parts']
        if task in ('text_static','image_static') and len(doc.durations)!=1:raise PixelError('Static work must not acquire unsolicited animation frames',code='TASK_SCOPE_CONFLICT')
        if task=='image_static':
            baseline=c['baseline']
            if [doc.width,doc.height]!=baseline['size'] or palette_key(doc)!=baseline['palette'] or image_key(doc)!=baseline['image']:
                raise PixelError('Image separation must preserve the faithful draft size, palette and visible pixels. A different requested edit needs its own plan.',code='DRAFT_FIDELITY_CHANGED')
        if task!='edit_static' and not parts:raise PixelError('Record and inspect the editable object layers first',code='PART_CHECK_REQUIRED')
        checked={}
        for p in parts:
            try:key=part_key(doc,p['layer'],p['frame'])
            except ValueError:key=None
            if p['extraction']!='clean' or p.get('checked_key')!=key or p['hidden']=='needs_repair':
                raise PixelError('A part is uninspected, stale or needs repair',code='PART_CHECK_REQUIRED')
            if p['layer'] in c['completion_scope'] and p['hidden']!='complete':raise PixelError('Requested hidden-area completion still needs checking',code='PART_CHECK_REQUIRED')
            checked[p['layer']]=p
        if any(layer not in checked for layer in c['completion_scope']):
            raise PixelError('Every requested completion layer needs a checked part record',code='PART_CHECK_REQUIRED')
        if task in ('text_static','image_static'):
            for layer in doc.layers:
                if layer.visible and layer.opacity and layer.cels[0].getchannel('A').getbbox() and layer.id not in checked:
                    raise PixelError('Inspect every visible object/background layer; keep original full-image references hidden.',code='PART_CHECK_REQUIRED')
