"""Evidence-based finish/review/repair workflow. Numeric checks never certify aesthetics."""
from __future__ import annotations

from collections import Counter, OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import uuid
import weakref
from typing import Literal

from PIL import Image, ImageChops, ImageDraw
from typing_extensions import TypedDict
from pydantic import ConfigDict

from .model import Document, PixelError, integer, pixels

DEFAULT_POLICY = {"brief": "", "expected_width": None, "expected_height": None, "expected_frames": None,
                  "max_colors": None, "transparent_background": None, "fixed_regions": [], "detail_regions": [],
                  "uniform_timing": False, "loop": True, "criteria": [], "max_rounds": 3}


class QualitySettings(TypedDict, total=False):
    brief: str
    expected_width: int | None
    expected_height: int | None
    expected_frames: int | None
    max_colors: int | None
    transparent_background: bool | None
    fixed_regions: list[str]
    detail_regions: list[str]
    uniform_timing: bool
    loop: bool
    criteria: list[str]
    max_rounds: int


class VisualCheck(TypedDict):
    criterion_id: str
    verdict: Literal["pass", "fail", "uncertain", "acceptable", "needs_fix"]
    reason: str


class WarningResolution(TypedDict):
    warning_id: str
    verdict: Literal["pass", "fail", "uncertain", "acceptable", "needs_fix"]
    reason: str


for _argument in (QualitySettings, VisualCheck, WarningResolution):
    _argument.__pydantic_config__ = ConfigDict(extra="forbid")


RECORD_LIMIT = 256  # All 128 supported action tags plus bounded rechecks.


def validate_policy(value, allow_tag_policies=True):
    allowed = sorted([*DEFAULT_POLICY, *(['tag_policies'] if allow_tag_policies else [])])
    if not isinstance(value, dict):
        raise PixelError("Quality settings must be an object", details={"allowed_fields": allowed})
    unknown = sorted(set(value)-set(allowed))
    if unknown:
        raise PixelError(f"Unknown quality settings: {', '.join(unknown)}. Allowed fields: {', '.join(allowed)}",
            recovery="Use the exact settings names from pixel_review_settings; for example expected_width and expected_frames.",
            details={"unknown_fields": unknown, "allowed_fields": allowed})
    policy = {**deepcopy(DEFAULT_POLICY), **deepcopy(value)}
    for key, maximum in (("expected_width", 512), ("expected_height", 512), ("expected_frames", 256), ("max_colors", 65536)):
        if policy[key] is not None:
            integer(policy[key], key, 1, maximum)
    for key in ("uniform_timing", "loop"):
        if not isinstance(policy[key], bool):
            raise PixelError(f"{key} must be boolean")
    if policy["transparent_background"] is not None and not isinstance(policy["transparent_background"], bool):
        raise PixelError("transparent_background must be boolean or null")
    if not isinstance(policy["brief"], str) or len(policy["brief"]) > 2000:
        raise PixelError("Quality brief must contain at most 2000 characters")
    for key, limit, length in (("fixed_regions", 16, 120), ("detail_regions",8,120), ("criteria", 12, 300)):
        values = policy[key]
        if not isinstance(values, list) or len(values)>limit or any(not isinstance(v, str) or not v.strip() or len(v)>length for v in values):
            raise PixelError(f"Invalid quality {key}")
        policy[key] = list(dict.fromkeys(v.strip() for v in values))
    integer(policy["max_rounds"], "max_rounds", 1, 20)
    if 'tag_policies' in value:
        overrides=value['tag_policies']
        if not isinstance(overrides,dict) or len(overrides)>128:
            raise PixelError('At most 128 tag review policies are supported')
        clean={}
        for name,patch in overrides.items():
            if not isinstance(name,str) or not name.strip() or len(name)>120:
                raise PixelError('Invalid review tag name')
            normalized=validate_policy(patch,allow_tag_policies=False)
            if patch:clean[name]={key:normalized[key] for key in patch}
        if clean:policy['tag_policies']=clean
        else:policy.pop('tag_policies',None)
    return policy


def effective_policy(doc, tag=None):
    policy=validate_policy(doc.quality_policy or {})
    if tag is None:return policy
    doc.frame_indices(tag)  # Reject misspelled/deleted tags; never silently use global scope.
    overrides=policy.pop('tag_policies',{})
    policy['expected_frames']=None  # Global count describes the complete source timeline.
    return validate_policy({**policy,**overrides.get(tag,{})},allow_tag_policies=False)


def update_policy(doc, settings, mode='merge', tag=None):
    if mode not in ('merge','replace'):
        raise PixelError('Review settings mode must be merge or replace',details={'allowed_modes':['merge','replace']})
    normalized=validate_policy(settings,allow_tag_policies=False)
    patch={key:normalized[key] for key in settings}
    policy=validate_policy(doc.quality_policy or {})
    overrides=policy.pop('tag_policies',{})
    if tag is None:
        policy=validate_policy({**(policy if mode=='merge' else {}),**patch})
    else:
        doc.frame_indices(tag)
        entry={**(overrides.get(tag,{}) if mode=='merge' else {}),**patch}
        if entry:overrides[tag]=entry
        else:overrides.pop(tag,None)
    if overrides:policy['tag_policies']=overrides
    return policy


def validate_records(records):
    if not isinstance(records, list) or len(records)>RECORD_LIMIT:
        raise PixelError(f"At most {RECORD_LIMIT} quality records are stored in a project")
    for record in records:
        if not isinstance(record, dict) or len(json.dumps(record, ensure_ascii=False))>100_000:
            raise PixelError("Invalid quality review record")
        if record.get("status") not in ("passed", "needs_changes", "uncertain"):
            raise PixelError("Invalid quality review status")
        if not isinstance(record.get("content_digest"), str) or len(record["content_digest"])!=64:
            raise PixelError("Invalid quality content digest")
        if not isinstance(record.get("scope"), dict) or not isinstance(record.get("visual_checks"), list):
            raise PixelError("Invalid quality review scope/checks")
        scope=record["scope"]
        if scope.get('tag') is not None and not isinstance(scope['tag'],str):
            raise PixelError('Invalid quality tag scope')
        if record.get('digest_version',1) not in (1,2):
            raise PixelError('Unsupported quality digest version')
        if not isinstance(scope.get("layers"),list) or any(not isinstance(v,str) for v in scope["layers"]) or not isinstance(scope.get("frames"),list):
            raise PixelError("Invalid quality scope fields")
        for frame in scope["frames"]:
            integer(frame,"review frame",0,255)
        if record.get("method") not in ("frames_and_timing","playback_and_frames") or not isinstance(record.get("summary"),str):
            raise PixelError("Invalid quality method/summary")
    return deepcopy(records)


def content_digest(doc):
    data = doc.to_dict()
    for key in ("revision", "active_layer", "active_frame", "selection", "quality_reviews", "feedback", "material"):
        data.pop(key, None)
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def review_scope(doc, tag=None, layers=None):
    if layers is not None:
        included = {doc.layer(item).id for item in layers}
        if not included:
            raise PixelError("Select at least one layer for review")
    else:included={layer.id for layer in doc.layers if layer.visible}
    return {'tag':tag,'layers':sorted(l.id for l in doc.layers if l.id in included and l.opacity>0),
            'frames':doc.frame_indices(tag)}


def scoped_document(doc, tag=None, layers=None):
    scope=review_scope(doc,tag,layers)
    clone = Document.from_dict(doc.to_dict())
    if layers is not None:
        for layer in clone.layers:
            layer.visible = layer.id in scope['layers']
    return clone, scope


def scope_digest(doc, scope):
    """Hash only evidence inputs for this action, including raw contributing cels."""
    included=set(scope['layers'])
    if included-set(layer.id for layer in doc.layers):raise PixelError('Reviewed layer was removed')
    frames=doc.frame_indices(scope.get('tag'))
    if frames!=scope['frames']:raise PixelError('Reviewed frame range changed')
    policy=effective_policy(doc,scope.get('tag'))
    data={'document_id':doc.id,'size':[doc.width,doc.height],'scope':scope,'policy':policy,
          'durations':[doc.durations[f] for f in frames],
          'tags':doc.tags if scope.get('tag') is None else {scope['tag']:doc.tags[scope['tag']]},
          'regions':doc.regions,'reference':doc.reference,'character':doc.character,
          'layers':[(layer.id,layer.opacity) for layer in doc.layers if layer.id in included]}
    h=hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())
    for layer in doc.layers:
        if layer.id in included:
            for frame in frames:h.update(layer.cels[frame].tobytes())
    return h.hexdigest()


def review_sequences(doc, scope, policy):
    if scope.get('tag') is not None or not doc.tags:
        return [{'tag':scope.get('tag'),'frames':scope['frames'],
                 'playback_frames':doc.frame_indices(scope.get('tag'),playback=True),'policy':policy}]
    sequences=[{'tag':tag,'frames':doc.frame_indices(tag),'playback_frames':doc.frame_indices(tag,playback=True),
                'policy':effective_policy(doc,tag)} for tag in doc.tags]
    covered={f for seq in sequences for f in seq['frames']}
    # Unnamed source frames also need acceptance; they are not an invented looping action.
    for frame in scope['frames']:
        if frame not in covered:
            sequences.append({'tag':None,'frames':[frame],'playback_frames':[frame],
                              'policy':{**{k:v for k,v in policy.items() if k!='tag_policies'},'expected_frames':None,'loop':False}})
    return sequences


def required_criteria(doc, policy, frames):
    criteria = [{"id": "requirements", "label": "是否满足任务要求与交付规格"},
                {"id": "silhouette", "label": "轮廓、辨识度与像素边缘是否清楚"},
                {"id": "color_detail", "label": "配色、明暗与局部细节是否协调"}]
    if doc.reference and doc.reference.get("subject"):
        criteria.append({"id": "reference_match", "label": "主体特征与要求的参考画风是否吻合"})
    if doc.character:
        criteria.append({"id": "character_consistency", "label": "与角色规范对照，脸部、配色和各视角特征是否一致"})
    if len(frames)>1:
        criteria += [{"id": "motion", "label": "动作是否自然，衣物是否出现贴片平移、断接或抖动"},
                     {"id": "timing", "label": "按真实帧时长观察，节奏和循环过渡是否合适"}]
    for i, label in enumerate(policy["criteria"]):
        criteria.append({"id": f"custom_{i+1}", "label": label})
    return criteria


def changed_pixels(a, b):
    diff = ImageChops.difference(a, b)
    box = diff.getbbox(alpha_only=False)
    return sum(any(c) for c in pixels(diff.crop(box))) if box else 0


def _analyze_sequence(doc, scope, policy, playback_frames=None):
    frames = scope["frames"]
    images = [doc.composite(f) for f in frames]
    checks, warnings = [], []
    def check(key, label, passed, details):
        checks.append({"id": key, "label": label, "passed": bool(passed), "details": details})
    for key, actual in (("expected_width", doc.width), ("expected_height", doc.height), ("expected_frames", len(frames))):
        target = policy[key]
        check(key, {"expected_width": "画布宽度", "expected_height": "画布高度", "expected_frames": "动画帧数"}[key],
              target is None or actual==target, {"actual": actual, "required": target})
    blank = [f for f, image in zip(frames, images) if not image.getbbox()]
    check("nonempty", "画面不是空白", not blank, {"blank_frames": blank})
    colors = set()
    color_overflow = False
    for image in images:
        entries=image.getcolors(65536)
        if entries is None:
            color_overflow=True
            break
        colors.update(c for _, c in entries if c[3])
        if len(colors)>65536:
            color_overflow=True
            break
    check("palette", "色数限制", policy["max_colors"] is None or not color_overflow and len(colors)<=policy["max_colors"],
          {"opaque_colors": ">65536" if color_overflow else len(colors), "required_maximum": policy["max_colors"]})
    transparent = all(image.getchannel("A").getextrema()[0]==0 for image in images)
    check("transparency", "透明背景要求", policy["transparent_background"] is not True or transparent,
          {"has_transparent_pixels_in_every_frame": transparent, "required": policy["transparent_background"]})
    durations = [doc.durations[f] for f in frames]
    check("uniform_timing", "帧时长要求", not policy["uniform_timing"] or len(set(durations))==1, {"durations_ms": durations})
    for name in policy["fixed_regions"]:
        if name not in doc.regions:
            check("fixed_"+name, "固定部位 · "+name, False, {"error": "Named region is missing"})
            continue
        x, y, w, h = doc.regions[name]
        first = images[0].crop((x,y,x+w,y+h)).tobytes()
        moved = [f for f, image in zip(frames, images) if image.crop((x,y,x+w,y+h)).tobytes()!=first]
        check("fixed_"+name, "固定部位 · "+name, not moved, {"rect": [x,y,w,h], "changed_frames": moved})
    blocked=pending_feedback(doc,frames)
    if getattr(doc,"feedback",[]):
        check("feedback_resolved","用户标记的问题已处理",not blocked,
              {"pending_issue_ids":[i["id"] for i in blocked],"count":len(blocked)})
    playback_frames=playback_frames if playback_frames is not None else doc.frame_indices(scope["tag"],playback=True)
    by_frame=dict(zip(frames,images))
    playback_images=[by_frame[f] for f in playback_frames]
    changes = [changed_pixels(a,b) for a,b in zip(playback_images, playback_images[1:])]
    seam = changed_pixels(playback_images[-1], playback_images[0]) if len(playback_images)>1 and policy['loop'] else 0
    if len(images)>1:
        if len({image.tobytes() for image in images})==1:
            warnings.append({"id": "static_animation", "message": "全部动画帧画面相同；请确认是否真的完成了动作。"})
        ratio = max(durations)/min(durations)
        if ratio>=4:
            warnings.append({"id": "uneven_timing", "message": f"最长/最短帧时长相差 {ratio:.1f} 倍；请按真实节奏检查停顿与突跳。"})
        if policy["loop"] and seam>max(4, max(changes, default=0)*1.75):
            warnings.append({"id": "loop_jump", "message": "循环首尾的像素变化明显大于内部转场，请检查回跳。"})
        rigid = []
        for layer in doc.layers:
            if not layer.visible or layer.opacity==0:
                continue
            cels = [layer.cels[f] for f in frames]
            boxes = [image.getbbox() for image in cels]
            valid = [(im, box) for im, box in zip(cels, boxes) if box]
            if len(valid)<2:
                continue
            shapes = {im.crop(box).tobytes() for im, box in valid}
            sizes = {(box[2]-box[0], box[3]-box[1]) for _, box in valid}
            points = {(box[0],box[1]) for _, box in valid}
            if len(shapes)==1 and len(sizes)==1 and len(points)>1 and (valid[0][1][2]-valid[0][1][0])*(valid[0][1][3]-valid[0][1][1])>=16:
                rigid.append(layer.name)
        if rigid:
            warnings.append({"id": "rigid_translation", "message": "这些图层只有整块平移："+"、".join(rigid)+"。物体位移可能合理；衣物需检查固定点和局部弯曲。"})
    return {"technical_passed": all(c["passed"] for c in checks), "technical_checks": checks, "warnings": warnings,
            "metrics": {"frames": frames, "playback_frames":playback_frames,
                        "duration_ms": sum(doc.durations[f] for f in playback_frames), "durations_ms": durations,
                        "changed_pixels_between_frames": changes, "loop_seam_changed_pixels": seam,
                        "distinct_poses": len({image.tobytes() for image in images})},
            "criteria": required_criteria(doc, policy, frames), "automatic_verdict": "程序检查不代表画风和动作自然度合格。"}


def analyze(doc, scope, policy):
    result=_analyze_sequence(doc,scope,policy)
    sequences=review_sequences(doc,scope,policy)
    if scope.get('tag') is None and doc.tags:
        # Keep document dimensions/count/colors global, but check motion and fixed anchors per action.
        result['technical_checks']=[c for c in result['technical_checks'] if c['id'] not in ('uniform_timing','transparency') and not c['id'].startswith('fixed_')]
        result['warnings']=[]
        for seq in sequences:
            sub=_analyze_sequence(doc,{**scope,'tag':seq['tag'],'frames':seq['frames']},seq['policy'],seq['playback_frames'])
            prefix='tag:'+seq['tag'] if seq['tag'] is not None else 'frame:'+str(seq['frames'][0])
            result['technical_checks'] += [{**c,'id':prefix+':'+c['id'],'label':prefix+' · '+c['label']} for c in sub['technical_checks']]
            result['warnings'] += [{**w,'id':prefix+':'+w['id'],'message':prefix+' · '+w['message']} for w in sub['warnings']]
            result['criteria'] += [{**c,'id':prefix+':'+c['id'],'label':prefix+' · '+c['label']} for c in sub['criteria'] if c['id'].startswith('custom_')]
        result['technical_passed']=all(c['passed'] for c in result['technical_checks'])
        result['metrics']['changed_pixels_between_frames']=[]
        result['metrics']['loop_seam_changed_pixels']=None
        result['metrics']['playback_frames']=[]
        result['metrics']['playback_order']='independent_sequences'
        result['metrics']['duration_ms']=sum(sum(doc.durations[f] for f in s['playback_frames']) for s in sequences)
    result['metrics']['sequences']=[{'tag':s['tag'],'frames':s['frames'],'playback_frames':s['playback_frames'],
        'loop':s['policy']['loop'],'duration_ms':sum(doc.durations[f] for f in s['playback_frames'])} for s in sequences]
    return result


def tiled_evidence(doc, frames, labels, columns=8, tile=100, rect=None):
    columns = min(columns, len(frames))
    rows = math.ceil(len(frames)/columns)
    out = Image.new("RGBA", (columns*(tile+8), rows*(tile+30)), "#171d28")
    draw = ImageDraw.Draw(out)
    for index, (frame, label) in enumerate(zip(frames, labels)):
        im = doc.preview(frame, scale=1,rect=rect)
        ratio = min(tile/im.width, tile/im.height)
        size = max(1,round(im.width*ratio)),max(1,round(im.height*ratio))
        im = im.resize(size, Image.Resampling.NEAREST)
        x, y = index%columns*(tile+8), index//columns*(tile+30)
        out.paste(im,(x+(tile+8-size[0])//2,y+5+(tile-size[1])//2))
        draw.text((x+4,y+tile+10), label, fill="#dce7f5")
    return out


def criteria_verdicts(values, expected, key="criterion_id", allowed=("pass","fail","uncertain")):
    expected = set(expected)
    if not isinstance(values,list):
        raise PixelError(f"Review {key} conclusions must be a list", code="REVIEW_INCOMPLETE",
                         details={"expected_ids":sorted(expected),"missing_ids":sorted(expected)})
    ids=[]; invalid=[]
    for index,value in enumerate(values):
        if not isinstance(value,dict):
            invalid.append({"index":index,"error":"must be an object"});continue
        if set(value)!={key,"verdict","reason"} or not isinstance(value.get(key),str):
            invalid.append({"index":index,"missing_fields":sorted({key,"verdict","reason"}-set(value)),
                            "unknown_fields":sorted(set(value)-{key,"verdict","reason"})})
        if isinstance(value.get(key),str):ids.append(value[key])
    missing=sorted(expected-set(ids));unknown=sorted(set(ids)-expected)
    duplicates=sorted(v for v,count in Counter(ids).items() if count>1)
    if missing or unknown or duplicates or invalid:
        details={"id_field":key,"missing_ids":missing,"unknown_ids":unknown,"duplicate_ids":duplicates,
                 "invalid_items":invalid,"expected_ids":sorted(expected)}
        raise PixelError(f"Review {key} mismatch: missing={missing}; unknown={unknown}; duplicates={duplicates}; invalid_items={invalid}",
            code="REVIEW_INCOMPLETE",details=details,
            recovery="Use only the exact criterion_id / warning_id values returned by this pixel_review. Submit one conclusion per id.")
    found = {}
    for value in values:
        aliases = ({"acceptable":"pass","needs_fix":"fail"} if "pass" in allowed else {"pass":"acceptable","fail":"needs_fix"})
        raw=value["verdict"]
        verdict = aliases.get(raw,raw) if isinstance(raw,str) else None
        if verdict not in allowed or not isinstance(value["reason"],str) or not 1<=len(value["reason"].strip())<=2000:
            raise PixelError(f"Invalid conclusion for {key}={value[key]!r}: use pass/fail/uncertain and a concrete reason (1–2000 characters).",
                code="REVIEW_INCOMPLETE",details={"id_field":key,"invalid_id":value[key],
                    "allowed_verdicts":["pass","fail","uncertain","acceptable","needs_fix"]})
        found[value[key]] = {**deepcopy(value),"verdict":verdict}
    return list(found.values())


def pending_feedback(doc, frames=None):
    from .feedback import summary
    needed=set(frames) if frames is not None else None
    return [i for i in summary(doc)["issues"] if i["status"] not in ("resolved","dismissed") and
            (needed is None or needed.intersection(i["frames"]))]


class QualityManager:
    def __init__(self, runtime):
        self.runtime = Path(runtime)/"review-cache"
        self.tickets = OrderedDict()
        self._digest_cache = None
        self._scope_cache = OrderedDict()

    def digest(self, doc):
        key = weakref.ref(doc),doc.id,doc.content_serial
        if not self._digest_cache or self._digest_cache[0]!=key:
            self._digest_cache = key, content_digest(doc)
        return self._digest_cache[1]

    def scoped_digest(self, doc, scope):
        key=(weakref.ref(doc),doc.id,doc.content_serial,json.dumps(scope,sort_keys=True))
        if key not in self._scope_cache:
            self._scope_cache[key]=scope_digest(doc,scope)
            while len(self._scope_cache)>512:self._scope_cache.popitem(last=False)
        return self._scope_cache[key]

    def is_current(self, doc, record):
        try:
            digest=self.scoped_digest(doc,record['scope']) if record.get('digest_version')==2 else self.digest(doc)
            return record['content_digest']==digest
        except (PixelError,KeyError,IndexError):return False

    def matching_record(self, doc, tag=None, layers=None, frame=None):
        if not doc.quality_reviews:
            return None
        scope = review_scope(doc, tag, layers)
        needed = {frame} if frame is not None else set(scope["frames"])
        for record in reversed(doc.quality_reviews):
            reviewed = record.get("scope",{})
            compatible=frame is not None or reviewed.get('tag') is None or reviewed.get('tag')==tag
            if compatible and self.is_current(doc,record) and reviewed.get("layers")==scope["layers"] and needed.issubset(set(reviewed.get("frames",[]))):
                return record
        return None

    def coverage(self, doc, tag=None, layers=None, frame=None):
        scope=review_scope(doc,tag,layers)
        needed={frame} if frame is not None else set(scope['frames'])
        records=[r for r in reversed(doc.quality_reviews) if r['scope'].get('layers')==scope['layers'] and self.is_current(doc,r)]
        if frame is not None:contexts=[(None,needed)]
        elif tag is not None or not doc.tags:contexts=[(tag,needed)]
        else:
            contexts=[(t,set(doc.frame_indices(t))) for t in doc.tags]
            uncovered=needed-set().union(*(fs for _,fs in contexts))
            if uncovered:contexts.append((None,uncovered))
        missing=set();missing_tags=[];blocked=[];used=[];parts=[]
        for context,frames in contexts:
            remaining=set(frames);failed=set();part_ids=[]
            for record in records:
                reviewed=record['scope']
                if frame is None and reviewed.get('tag') is not None and reviewed.get('tag')!=context:continue
                overlap=remaining.intersection(reviewed['frames'])
                if not overlap:continue
                remaining-=overlap
                if record['status']!='passed':failed|=overlap;blocked.append(record['review_id'])
                else:used.append(record['review_id']);part_ids.append(record['review_id'])
            absent=remaining|failed;missing|=absent
            if absent and context is not None:missing_tags.append(context)
            parts.append({'tag':context,'frames':sorted(frames),'missing_frames':sorted(absent),
                          'status':'passed' if not absent else 'review_required','review_ids':list(dict.fromkeys(part_ids))})
        failures=[]
        if tag is None and frame is None:
            policy=effective_policy(doc)
            for key,actual in [('expected_width',doc.width),('expected_height',doc.height),('expected_frames',len(doc.durations))]:
                if policy[key] is not None and policy[key]!=actual:
                    failures.append({'id':key,'actual':actual,'required':policy[key]})
            if policy['max_colors'] is not None and not missing:
                # Per-action palettes may each pass while their atlas union exceeds the global limit.
                colors=set()
                for f in scope['frames']:
                    image=doc.composite(f,layers=scope['layers'])
                    entries=image.getcolors(65536)
                    if entries is None:failures.append({'id':'palette','actual':'>65536','required':policy['max_colors']});break
                    colors.update(c for _,c in entries if c[3])
                    if len(colors)>policy['max_colors']:
                        failures.append({'id':'palette','actual':len(colors),'required':policy['max_colors']});break
        return {'passed':not missing and not failures,'scope':scope,'missing_frames':sorted(missing),
                'missing_tags':missing_tags,'blocked_review_ids':list(dict.fromkeys(blocked)),
                'review_ids':list(dict.fromkeys(used)),'parts':parts,'technical_failures':failures}

    def summary(self, doc):
        blocked=pending_feedback(doc)
        if blocked:
            asking=sum(i["status"]=="needs_clarification" for i in blocked)
            return {"status":"needs_changes","summary":f"还有 {len(blocked)} 条用户问题待处理"+
                    (f"，其中 {asking} 条等待用户回复" if asking else ""),
                    "pending_issue_ids":[i["id"] for i in blocked],"next_action":"pixel_feedback",
                    "final_export_requires_review":True}
        if not doc.quality_reviews:
            return {"status":"pending","summary":"待程序检查与 AI 看图复核","next_action":"pixel_review","final_export_requires_review":True}
        coverage=self.coverage(doc)
        if coverage['passed']:
            return {'status':'passed','summary':'当前图集的全部动作与帧已通过复核','scope':coverage['scope'],
                    'review_ids':coverage['review_ids'],'coverage':coverage,'next_action':'save_and_export'}
        for record in reversed(doc.quality_reviews):
            if self.is_current(doc,record):
                return {'status':'partial' if record['status']=='passed' else record['status'],
                        'scope':record['scope'],'summary':'部分范围已通过，整张图集仍需复核' if record['status']=='passed' else record['summary'],
                        'coverage':coverage,'next_action':'pixel_review','final_export_requires_review':True}
        return {"status": "stale" if doc.quality_reviews else "pending", "summary": "作品已修改，请重新自检" if doc.quality_reviews else "待程序检查与 AI 看图复核",
                "next_action": "pixel_review", "final_export_requires_review": True}

    def start(self, doc, tag=None, layers=None):
        snapshot, scope = scoped_document(doc, tag, layers)
        policy = effective_policy(doc,tag)
        analysis = analyze(snapshot, scope, policy)
        review_id = uuid.uuid4().hex
        folder = self.runtime/review_id
        folder.mkdir(parents=True,exist_ok=True)
        sequences=review_sequences(snapshot,scope,policy)
        assets=[]
        for index,seq in enumerate(sequences):
            playback_frames=seq['playback_frames']
            playback_images=[snapshot.composite(f) for f in playback_frames]
            alpha_binary=all(set(pixels(im.getchannel('A'))).issubset({0,255}) for im in playback_images)
            colors=set();overflow=False
            for im in playback_images:
                entries=im.getcolors(256)
                if entries is None:overflow=True;break
                colors.update(c for _,c in entries if c[3])
                if len(colors)>255:overflow=True;break
            looping=seq['policy']['loop'] and len(playback_frames)>1
            asset=folder/f'playback-{index}.png'
            if looping and alpha_binary and not overflow:
                asset=asset.with_suffix('.gif');snapshot.export(asset,'gif',scale=1,tag=seq['tag'])
            else:
                playback_images[0].save(asset,format='PNG',save_all=len(playback_images)>1,
                    append_images=playback_images[1:],duration=[snapshot.durations[f] for f in playback_frames],
                    loop=0 if looping else 1,disposal=2)
            assets.append({'path':str(asset),'tag':seq['tag'],'frames':seq['frames'],'loop':looping,
                           'duration_ms':sum(snapshot.durations[f] for f in playback_frames)})
        ticket = {"id": review_id, "doc": snapshot, "scope": scope, "policy": policy, "analysis": analysis,
                  "content_digest": self.scoped_digest(doc,scope), "digest_version":2,
                  "pages": math.ceil(len(scope["frames"])/32), "seen": set(),
                  "folder": folder, "asset": Path(assets[0]['path']), 'assets':assets,'sequences':sequences,"submitted": None,
                  "stored_record": self.matching_record(doc,tag,layers)}
        ticket['stored_coverage']=self.coverage(doc,tag,layers)
        stored=ticket['stored_record'];coverage=ticket['stored_coverage']
        if stored and stored['review_id'] not in (coverage['review_ids'] if coverage['passed'] else coverage['blocked_review_ids']):
            ticket['stored_record']=None
        self.tickets[review_id] = ticket
        while len(self.tickets)>4:
            self.tickets.popitem(last=False)
        return ticket

    def ticket(self, review_id, doc):
        if review_id not in self.tickets:
            raise PixelError("Review evidence expired; call pixel_review for a fresh snapshot",code="REVIEW_EXPIRED")
        ticket = self.tickets[review_id]
        if ticket["doc"].id!=doc.id or not self.is_current(doc,ticket):
            raise PixelError("Artwork or requirements changed after this evidence. Re-run pixel_review.",code="REVIEW_STALE")
        return ticket

    def evidence(self, ticket, page=0, mark_seen=True):
        integer(page,"page",0,ticket["pages"]-1)
        doc, scope = ticket["doc"],ticket["scope"]
        frames = scope["frames"][page*32:(page+1)*32]
        sheets = [("frame_contact",tiled_evidence(doc,frames,[f"#{f} {doc.durations[f]}ms" for f in frames]))]
        for seq in ticket['sequences']:
            # Each action's timing appears on the page containing its first source frame.
            if seq['frames'][0] not in frames:continue
            playback=seq['playback_frames'];total=sum(doc.durations[f] for f in playback)
            looping=seq['policy']['loop'];cycles=2 if looping else 1
            count=min(24,max(8,len(playback)*2));sampled=[]
            for i in range(count):
                elapsed=(i*total*cycles//count)%total;cursor=0
                for frame in playback:
                    cursor+=doc.durations[frame]
                    if elapsed<cursor:sampled.append(frame);break
            prefix=('tag:'+seq['tag']+':' if seq['tag'] is not None else 'frame:'+str(seq['frames'][0])+':') if len(ticket['sequences'])>1 else ''
            if len(playback)>1:
                role='two_loop_timing' if looping else 'one_shot_timing'
                sheets.append((prefix+role,tiled_evidence(doc,sampled,[f"{i*total*cycles//count}ms #{f}" for i,f in enumerate(sampled)])))
                if looping:
                    edge=playback[-2:]+playback[:2]
                    sheets.append((prefix+'loop_seam',tiled_evidence(doc,edge,[f"#{f} {doc.durations[f]}ms" for f in edge],columns=4,tile=144)))
        details=ticket["policy"]["detail_regions"]
        if not details:
            details=[name for name in doc.regions if any(key in name.lower() for key in ("cloth","face","eyes","blink","裙","衣","脸","眼"))][:2]
        for name in details[:8]:
            if name in doc.regions:
                sheets.append(("detail:"+name,tiled_evidence(doc,frames,[f"#{f} {doc.durations[f]}ms" for f in frames],rect=doc.regions[name])))
        if page==0 and doc.reference:
            from .reference import decoded_asset
            for key in ("subject","style"):
                if doc.reference.get(key):
                    sheets.append((key+"_reference",decoded_asset(doc.reference[key]["png"])))
        if page == 0 and doc.character:
            from .reference import decoded_asset
            sheets.append(("character_pose", decoded_asset(doc.character["pose"]["png"])))
            for key, item in doc.character["views"].items():
                sheets.append(("character_" + key, decoded_asset(item["png"])))
        if mark_seen:
            ticket["seen"].add(page)
        data = {"ok":True,"review_id":ticket["id"],"document_id":doc.id,"revision":doc.revision,
                "page":page,"pages":ticket["pages"],"seen_pages":sorted(ticket["seen"]),"scope":scope,
                "policy":ticket["policy"],**ticket["analysis"],"image_roles":[role for role,_ in sheets],
                'playback_asset':ticket['assets'][0],'playback_assets':ticket['assets'],
                "review_status":"visual_review_required","next_action":"Inspect all evidence pages and real timing; fix via pixel_edit, then recheck; submit conclusions with pixel_review_submit.",
                "honesty":"Frames/timing evidence is not direct playback. Report the method actually used. Numeric success alone is not an artistic pass."}
        data["sampling_notice"]="Timing sheets sample equal elapsed intervals and can miss short poses; inspect the complete contact sheets and playable loop too."
        if doc.character:
            from .character import summary as character_summary
            data["character_spec"] = character_summary(doc.character)
        if len(scope["frames"]) > 1:
            data["motion_diagnostics"] = "Before concluding, call pixel_motion_check and inspect all pages of suspect frame/ROI evidence. Apply only chosen, visually confirmed repairs; rerun after editing. These clues do not certify natural motion."
        coverage=ticket['stored_coverage']
        data['existing_review_status']=('passed' if coverage['passed'] else ticket['stored_record']['status'] if ticket['stored_record'] else
                                        'partial' if coverage['review_ids'] else None)
        data['existing_review_coverage']={key:coverage[key] for key in ('passed','review_ids','missing_tags','missing_frames','technical_failures')}
        data["previous_reviews"]=[{"status":r["status"],"summary":r["summary"],"round":r["round"],
            "remaining_findings":[c for c in r["visual_checks"] if c["verdict"]!="pass"]}
            for r in [r for r in doc.quality_reviews if r['scope']==scope][-3:]]
        return data,[im for _,im in sheets]

    def submit(self, doc, review_id, visual_checks, warning_resolutions, method, summary):
        ticket = self.ticket(review_id,doc)
        if ticket["submitted"]:
            raise PixelError("This review was already submitted; start another review after changes",code="REVIEW_ALREADY_SUBMITTED")
        if ticket["seen"]!=set(range(ticket["pages"])):
            missing=sorted(set(range(ticket["pages"]))-ticket["seen"])
            raise PixelError(f"Inspect missing evidence pages before submitting: {missing}",code="REVIEW_INCOMPLETE",
                details={"missing_pages":missing,"seen_pages":sorted(ticket["seen"])})
        if method not in ("frames_and_timing","playback_and_frames") or not isinstance(summary,str) or not 1<=len(summary.strip())<=2000:
            raise PixelError("State the actual viewing method and a concise conclusion",code="REVIEW_INCOMPLETE")
        analysis = ticket["analysis"]
        checks = criteria_verdicts(visual_checks,{c["id"] for c in analysis["criteria"]})
        warnings = criteria_verdicts(warning_resolutions,{w["id"] for w in analysis["warnings"]},"warning_id",("acceptable","needs_fix","uncertain"))
        status = "passed"
        if not analysis["technical_passed"] or any(c["verdict"]=="fail" for c in checks) or any(w["verdict"]=="needs_fix" for w in warnings):
            status = "needs_changes"
        elif any(c["verdict"]=="uncertain" for c in checks+warnings):
            status = "uncertain"
        policy_digest=hashlib.sha256(json.dumps(ticket["policy"],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        round_number=1
        for previous in reversed(doc.quality_reviews):
            if previous['scope']!=ticket['scope']:continue
            if previous["status"]=="passed" or previous.get("policy_digest")!=policy_digest:
                break
            round_number+=1
        budget_reached=status!="passed" and round_number>=ticket["policy"]["max_rounds"]
        record = {"review_id":review_id,"content_digest":ticket["content_digest"],"digest_version":2,"scope":ticket["scope"],"status":status,
                  "method":method,"summary":summary.strip(),"visual_checks":checks,"warning_resolutions":warnings,
                  "technical_checks":analysis["technical_checks"],"metrics":analysis["metrics"],"round":round_number,"policy_digest":policy_digest,
                  "reviewed_at":datetime.now(timezone.utc).isoformat(),
                  "next_action":"save_and_export" if status=="passed" else "report_remaining_issues" if budget_reached else "edit_then_recheck",
                  "round_budget_reached":budget_reached,
                  "evidence":{"pages":ticket["pages"],"source":"actual_document_pixels_and_timing"}}
        doc.record_quality_review(record)
        ticket["submitted"] = record
        return record

    def require_pass(self, doc, tag=None, layers=None, frame=None, continuous=False):
        needed=[frame] if frame is not None else doc.frame_indices(tag)
        blocked=pending_feedback(doc,needed)
        if blocked:
            raise PixelError("User feedback is still open or needs rechecking after artwork changes.",code="FEEDBACK_PENDING",
                recovery="Use pixel_feedback to inspect all reported frames, ask if unclear, repair and resolve. "
                         "A human can export the current version with draft=true without claiming AI acceptance.")
        sequences=review_sequences(doc,review_scope(doc,tag,layers),effective_policy(doc,tag)) if continuous and tag is None and doc.tags else []
        if sequences and (len(sequences)!=1 or sequences[0]['playback_frames']!=doc.frame_indices() or
                          sequences[0]['policy']['loop']!=effective_policy(doc)['loop']):
            raise PixelError('Choose one animation tag for a reviewed GIF; timeline playback differs from the reviewed actions.',
                code='ANIMATION_TAG_REQUIRED',details={'available_tags':list(doc.tags)},
                recovery='Use tag for the intended action; use kind=sheet for the complete reviewed atlas. A combined GIF remains available as an explicit draft preview.')
        coverage=self.coverage(doc,tag,layers,frame)
        if not coverage['passed']:
            raise PixelError("Final export requires a CURRENT visual self-review for these frames/layers. Numeric checks alone do not certify quality.",
                code="REVIEW_REQUIRED",details=coverage,
                recovery="Review missing_tags / missing_frames using pixel_review(tag=...), then submit concrete findings. Keep the exact layer set. Whole-atlas export combines current passing scopes; draft=true remains unreviewed.")
        return {'review_id':coverage['review_ids'][0],'review_ids':coverage['review_ids'],'status':'passed',
                'scope':coverage['scope'],'coverage':coverage['parts']}
