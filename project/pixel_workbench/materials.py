"""Optional, local normal-map editing and 2D lighting. Never repaints color cels."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
import base64
import hashlib
import io
import json
import math
from pathlib import Path
import time
from typing import Literal
import uuid
import zipfile

from PIL import Image, ImageChops, ImageDraw, ImageFilter, PngImagePlugin
from typing_extensions import TypedDict
from pydantic import ConfigDict, StrictInt

from .model import MAX_PIXELS, PixelError, integer, rgba


class LightingSettings(TypedDict, total=False):
    light_x: float
    light_y: float
    light_height: float
    light_radius: float
    intensity: float
    ambient: float
    light_color: str
    normal_strength: float
    flip_y: bool
    specular: float
    shininess: float
    emission_strength: float
    emission_layers: list[str]
    background: Literal['checker', 'dark', 'light', 'transparent']


class NormalSource(TypedDict, total=False):
    kind: Literal['current', 'flat', 'import', 'silhouette', 'height']
    path: str
    columns: StrictInt
    frames: StrictInt
    bevel: float
    strength: float
    layers: list[str]


class NormalEdit(TypedDict, total=False):
    op: Literal['stroke', 'rect', 'erase']
    frame: StrictInt
    points: list[list[StrictInt]]
    rect: list[StrictInt]
    size: StrictInt
    normal: list[float]


for _type in (LightingSettings, NormalSource, NormalEdit):
    _type.__pydantic_config__ = ConfigDict(extra='forbid', strict=True)

DEFAULTS = dict(light_x=.3, light_y=.25, light_height=.45, light_radius=1.4,
                intensity=1.15, ambient=.28, light_color='#fff1d4', normal_strength=1.,
                flip_y=False, specular=.18, shininess=28., emission_strength=1.,
                emission_layers=[], background='checker')
RANGES = {'light_x':(-2.,3.), 'light_y':(-2.,3.), 'light_height':(.01,4.),
          'light_radius':(.05,8.), 'intensity':(0.,8.), 'ambient':(0.,2.),
          'normal_strength':(0.,4.), 'specular':(0.,2.), 'shininess':(1.,128.),
          'emission_strength':(0.,4.)}
MAX_MAP_PIXELS = MAX_PIXELS


def number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise PixelError(f'{name} must be a finite number in [{low}, {high}]')
    return float(value)


def fields(value, allowed, name):
    if not isinstance(value,dict) or set(value)-set(allowed):
        raise PixelError(f'Unknown {name} fields', details={'allowed_fields':sorted(allowed),
                         'unknown_fields':sorted(set(value)-set(allowed)) if isinstance(value,dict) else []})


def layer_ids(value):
    if not isinstance(value,list) or len(value)>64 or any(not isinstance(v,str) or not 1<=len(v)<=120 for v in value) or len(set(value))!=len(value):
        raise PixelError('emission/source layers must be up to 64 distinct observed layer ids')
    return value.copy()


def settings(value=None, base=None):
    value={} if value is None else value
    fields(value, DEFAULTS, 'lighting settings')
    result=deepcopy(DEFAULTS if base is None else base)
    result.update(value)
    for key,(low,high) in RANGES.items():result[key]=number(result[key],key,low,high)
    if not isinstance(result['flip_y'],bool):raise PixelError('flip_y must be boolean')
    color=rgba(result['light_color'])
    if not isinstance(result['light_color'],str) or color[3]!=255:raise PixelError('light_color must be an opaque hex color')
    result['light_color']='#'+''.join(f'{v:02x}' for v in color[:3])
    result['emission_layers']=layer_ids(result['emission_layers'])
    if result['background'] not in ('checker','dark','light','transparent'):raise PixelError('Unknown lighting preview background')
    return result


def encode(image):
    output=io.BytesIO();image.save(output,format='PNG');return base64.b64encode(output.getvalue()).decode('ascii')


@lru_cache(maxsize=16)
def decode(encoded, size):
    if not isinstance(encoded,str) or len(encoded)>1_500_000:raise PixelError('Material PNG exceeds its bounded map size')
    try:
        raw=base64.b64decode(encoded,validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='PNG' or image.size!=size:raise PixelError('Material map dimensions do not match its binding')
            return image.convert('RGBA')
    except (ValueError,OSError) as exc:raise PixelError('Invalid material PNG data') from exc


def validate_material(value):
    if value is None:return None
    required={'format','size','source_frames','normal','specular','settings','source_key','normal_origin'}
    fields(value,required,'material')
    if set(value)!=required or value['format']!='pixel-loom/material/v1':raise PixelError('Invalid material record')
    size=value['size']
    if not isinstance(size,list) or len(size)!=2:raise PixelError('Invalid material size')
    size=[integer(x,'material size',1,512) for x in size]
    count=integer(value['source_frames'],'material frame count',1,256)
    total=0
    for key in ('normal','specular'):
        maps=value[key]
        if not isinstance(maps,list) or (key=='normal' and not maps) or maps and len(maps) not in (1,count):raise PixelError('Material map frames must be shared or match their binding')
        total+=len(maps)*size[0]*size[1]
        if total>MAX_MAP_PIXELS:raise PixelError('Material maps exceed the pixel memory limit')
        for data in maps:
            image=decode(data,tuple(size))
            if key=='normal':
                bad=image.getchannel('B').point(lambda v:255 if v<127 else 0)
                visible=image.getchannel('A').point(lambda v:255 if v else 0)
                if ImageChops.multiply(bad,visible).getbbox():
                    raise PixelError('Use front-facing tangent normals (blue >=127); this may be a color image rather than a normal map.',code='INVALID_NORMAL_MAP')
    if not isinstance(value['source_key'],str) or len(value['source_key'])!=64 or any(c not in '0123456789abcdef' for c in value['source_key']):raise PixelError('Invalid material source signature')
    if value['normal_origin'] not in ('flat','import','silhouette','height','painted'):raise PixelError('Invalid normal origin')
    return {**deepcopy(value),'size':size,'settings':settings(value['settings'])}


def source_key(doc):
    digest=hashlib.sha256(f'{doc.width},{doc.height},{len(doc.durations)}'.encode())
    for layer in doc.layers:
        digest.update(json.dumps([layer.id,layer.visible,layer.opacity]).encode())
        for cel in layer.cels:digest.update(cel.tobytes())
    return digest.hexdigest()


def map_at(record, key, frame):
    maps=record[key]
    return decode(maps[0 if len(maps)==1 else frame],tuple(record['size'])) if maps else None


def compatible(record,doc):
    if record['size']!=[doc.width,doc.height]:
        raise PixelError('Color canvas changed; import matching maps or explicitly regenerate them.',code='MATERIAL_SIZE_MISMATCH')
    if any(maps and len(maps) not in (1,len(doc.durations)) for maps in (record['normal'],record['specular'])):
        raise PixelError('Animation frame count changed; import aligned map frames or regenerate them.',code='MATERIAL_FRAME_MISMATCH')
    missing=set(record['settings']['emission_layers'])-{l.id for l in doc.layers}
    if missing:raise PixelError('Some emission layers no longer exist',code='MATERIAL_LAYER_MISMATCH',details={'missing_layers':sorted(missing)})


def import_maps(path,size,count=1,columns=1):
    count=integer(count,'map frames',1,256);columns=integer(columns,'map columns',1,count)
    if size[0]*size[1]*count>MAX_MAP_PIXELS:raise PixelError('Map sheet exceeds the pixel limit')
    path=Path(path)
    if path.stat().st_size>50_000_000:raise PixelError('Map image is too large')
    raw=path.read_bytes()
    if len(raw)>50_000_000:raise PixelError('Map image is too large')
    with Image.open(io.BytesIO(raw)) as image:
        expected=(size[0]*columns,size[1]*math.ceil(count/columns))
        if image.format!='PNG' or image.size!=expected:
            raise PixelError('Import a same-size PNG, or an explicitly arranged PNG sheet. No implicit resizing.',
                             details={'expected_size':list(expected),'actual_size':list(image.size)})
        if image.mode not in ('1','L','LA','P','RGB','RGBA'):
            raise PixelError('Use an 8-bit PNG normal/height map; convert higher-bit-depth data explicitly before import.')
        image=image.convert('RGBA')
    return [image.crop(((i%columns)*size[0],(i//columns)*size[1],(i%columns+1)*size[0],(i//columns+1)*size[1])) for i in range(count)]


def generate_normal(height,strength):
    import numpy as np
    data=np.asarray(height.convert('L'),dtype=np.float32)/255.
    padded=np.pad(data,1,mode='edge')
    dx=(padded[1:-1,2:]-padded[1:-1,:-2])*.5
    dy=(padded[2:,1:-1]-padded[:-2,1:-1])*.5
    vectors=np.stack((-dx*strength,dy*strength,np.ones_like(dx)),axis=2)
    vectors/=np.maximum(np.linalg.norm(vectors,axis=2,keepdims=True),1e-8)
    return Image.fromarray(np.rint((vectors+1)*127.5).astype('uint8'),'RGB').convert('RGBA')


def paint(maps,edits,current_frame,frame_count):
    if not isinstance(edits,list) or len(edits)>256:raise PixelError('At most 256 normal brush operations')
    result=list(maps);changed={}
    for edit in edits:
        fields(edit,NormalEdit.__annotations__,'normal brush')
        kind=edit.get('op');frame=integer(edit.get('frame',current_frame),'normal frame',0,frame_count-1)
        index=0 if len(result)==1 else frame
        if index not in changed:changed[index]=result[index].copy()
        image=changed[index];draw=ImageDraw.Draw(image)
        if kind=='erase':normal=[0.,0.,1.]
        else:normal=edit.get('normal')
        if not isinstance(normal,list) or len(normal)!=3:raise PixelError('Brush normal must have three components')
        vector=[number(v,'normal component',-1,1) for v in normal];length=math.sqrt(sum(v*v for v in vector))
        if length<1e-6:raise PixelError('A normal cannot be the zero vector')
        if vector[2]<0:raise PixelError('2D normal brush directions must face the front hemisphere (Z >=0)')
        color=tuple(round((v/length+1)*127.5) for v in vector)+(255,)
        if kind in ('rect','erase'):
            rect=edit.get('rect')
            if not isinstance(rect,list) or len(rect)!=4:raise PixelError('Normal rectangle needs [x,y,width,height]')
            x,y,w,h=[integer(v,'normal rect',0,512) for v in rect]
            if not w or not h or x+w>image.width or y+h>image.height:raise PixelError('Normal rectangle is outside the map')
            draw.rectangle((x,y,x+w-1,y+h-1),fill=color)
        elif kind=='stroke':
            points=edit.get('points');size=integer(edit.get('size',1),'normal brush size',1,32)
            if not isinstance(points,list) or not 1<=len(points)<=4096:raise PixelError('Normal stroke needs 1–4096 points')
            checked=[]
            for point in points:
                if not isinstance(point,list) or len(point)!=2:raise PixelError('A brush point needs x,y')
                checked.append((integer(point[0],'brush x',0,image.width-1),integer(point[1],'brush y',0,image.height-1)))
            if len(checked)>1:draw.line(checked,fill=color,width=size)
            radius=size//2
            for x,y in checked:draw.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color)
        else:raise PixelError('Unknown normal brush operation')
    for index,image in changed.items():result[index]=image
    return result


def normal_vectors(image,config,flat=False):
    import numpy as np
    raw=np.asarray(image,dtype=np.float32)
    vectors=raw[:,:,:3]/127.5-1.
    vectors[abs(vectors)<.004]=0
    vectors[raw[:,:,3]==0]=(0,0,1)
    if flat:vectors[:]=(0,0,1)
    else:
        vectors[:,:,:2]*=config['normal_strength']
        if config['flip_y']:vectors[:,:,1]*=-1
    lengths=np.linalg.norm(vectors,axis=2,keepdims=True)
    vectors=np.divide(vectors,np.maximum(lengths,1e-8))
    vectors[lengths[:,:,0]<1e-8]=(0,0,1)
    return vectors


def render(doc,record,frame,flat=False,limit=None):
    import numpy as np
    compatible(record,doc);frame=integer(frame,'render frame',0,len(doc.durations)-1)
    s=record['settings'];width,height=doc.width,doc.height
    if limit and max(width,height)>limit:
        ratio=limit/max(width,height);width=max(1,round(width*ratio));height=max(1,round(height*ratio))
    def fit(image):return image.resize((width,height),Image.Resampling.NEAREST) if image.size!=(width,height) else image
    size=max(width,height)
    normal=normal_vectors(fit(map_at(record,'normal',frame)),s,flat)
    yy,xx=np.mgrid[:height,:width].astype(np.float32)
    lx=s['light_x']*max(width-1,1)-xx;ly=yy-s['light_y']*max(height-1,1)
    lz=np.full_like(lx,size*s['light_height'])
    vectors=np.stack((lx,ly,lz),axis=2);vectors/=np.linalg.norm(vectors,axis=2,keepdims=True)
    diffuse=np.maximum(np.sum(normal*vectors,axis=2),0)
    falloff=np.maximum(0,1-(lx*lx+ly*ly)/(size*s['light_radius'])**2)**2
    half=vectors.copy();half[:,:,2]+=1;half/=np.maximum(np.linalg.norm(half,axis=2,keepdims=True),1e-8)
    spec=np.maximum(np.sum(normal*half,axis=2),0)**s['shininess']*s['specular']*s['intensity']*falloff
    light=np.asarray(rgba(s['light_color'])[:3],dtype=np.float32)/255
    def linear(c):return np.where(c<=.04045,c/12.92,((c+.055)/1.055)**2.4)
    light=linear(light)
    mask=map_at(record,'specular',frame)
    if mask:
        raw_mask=np.asarray(fit(mask),dtype=np.float32)/255
        mask=raw_mask[:,:,:3]*raw_mask[:,:,3:]
    else:mask=np.ones((height,width,3),dtype=np.float32)
    output=np.zeros((height,width,3),dtype=np.float32);alpha=np.zeros((height,width,1),dtype=np.float32)
    emit=set(s['emission_layers'])
    for layer in doc.layers:
        if not layer.visible or not layer.opacity:continue
        data=np.asarray(fit(layer.cels[frame]),dtype=np.float32)/255
        a=data[:,:,3:]*layer.opacity/255
        color=linear(data[:,:,:3])
        if layer.id in emit:color=color*s['emission_strength']
        else:color=color*(s['ambient']+(diffuse*falloff*s['intensity'])[:,:,None]*light)+spec[:,:,None]*mask*light
        output=color*a+output*(1-a);alpha=a+alpha*(1-a)
    output=np.clip(output/np.maximum(alpha,1e-8),0,1)
    output=np.where(output<=.0031308,output*12.92,1.055*output**(1/2.4)-.055)
    result=np.zeros((height,width,4),dtype=np.uint8)
    result[:,:,:3]=np.rint(output*255).astype(np.uint8)
    result[:,:,3]=np.asarray(fit(doc.composite(frame)).getchannel('A'))
    result[result[:,:,3]==0,:3]=0
    if s['ambient']==1 and s['intensity']==0 and s['emission_strength']==1:return fit(doc.composite(frame)).copy()
    return Image.fromarray(result,'RGBA')


def displayed(image,background):
    if background=='transparent':return image.copy()
    if background=='checker':
        canvas=Image.new('RGBA',image.size,'#303948');draw=ImageDraw.Draw(canvas)
        for y in range(0,image.height,8):
            for x in range(0,image.width,8):
                if (x//8+y//8)%2:draw.rectangle((x,y,x+7,y+7),fill='#222b38')
    else:canvas=Image.new('RGBA',image.size,'#101824' if background=='dark' else '#e6edf4')
    canvas.alpha_composite(image);return canvas


def emission_image(doc,record,frame):
    """Export only visible emission, attenuated by every upper opaque surface."""
    import numpy as np
    result=doc.blank();emit=set(record['settings']['emission_layers'])
    for layer in doc.layers:
        if not layer.visible or not layer.opacity:continue
        image=layer.cels[frame]
        alpha=image.getchannel('A').point(lambda value:value*layer.opacity//255)
        if layer.id in emit:
            image=image.copy();image.putalpha(alpha);result.alpha_composite(image)
        else:
            result.putalpha(ImageChops.multiply(result.getchannel('A'),ImageChops.invert(alpha)))
    data=np.array(result)
    strength=record['settings']['emission_strength']
    if strength!=1:
        colors=data[:,:,:3].astype(np.float32)/255
        colors=np.where(colors<=.04045,colors/12.92,((colors+.055)/1.055)**2.4)*strength
        colors=np.clip(colors,0,1)
        colors=np.where(colors<=.0031308,colors*12.92,1.055*colors**(1/2.4)-.055)
        data[:,:,:3]=np.rint(colors*255).astype(np.uint8)
    data[data[:,:,3]==0,:3]=0
    return Image.fromarray(data,'RGBA')


class MaterialManager:
    def __init__(self):self.previews=OrderedDict();self.pinned=set()

    def retain(self,key):
        if key in self.previews:self.pinned.add(key)

    def release(self,key):self.pinned.discard(key)

    def status(self,doc):
        value=doc.material
        warnings=[]
        if value:
            try:compatible(value,doc)
            except PixelError as error:warnings.append({'code':error.code,'message':str(error)})
            if value['source_key']!=source_key(doc):warnings.append({'code':'MATERIAL_SOURCE_CHANGED','message':'Color art changed; inspect alignment before applying a fresh preview.'})
            missing=set(value['settings']['emission_layers'])-{layer.id for layer in doc.layers}
            if missing:warnings.append({'code':'MATERIAL_LAYER_MISSING','message':'Some saved emission layers no longer exist; choose current layers before exporting.','layer_ids':sorted(missing)})
            if len(doc.durations)>1 and len(value['normal'])==1 and value['normal_origin']!='flat':warnings.append({'code':'SHARED_ANIMATION_NORMAL','message':'One normal is shared: moving shapes may require aligned per-frame maps.'})
        return {'configured':value is not None,'normal_frames':len(value['normal']) if value else 0,
                'specular_frames':len(value['specular']) if value else 0,'normal_origin':value['normal_origin'] if value else None,
                'settings':deepcopy(value['settings'] if value else DEFAULTS),'warnings':warnings,
                'help':"pixel_help(topic='material_workflow')",'color_pixels_unchanged':True}

    def ticket(self,doc,key,rebase=False,revive=False):
        ticket=self.previews.get(key)
        if not ticket or not revive and time.monotonic()-ticket['created']>900:raise PixelError('Material preview expired; create a new preview.',code='MATERIAL_PREVIEW_EXPIRED')
        if ticket['document_id']!=doc.id or not rebase and ticket['revision']!=doc.revision:
            raise PixelError('Artwork/revision changed; inspect a fresh material preview before applying/exporting.',code='MATERIAL_PREVIEW_STALE')
        self.previews.move_to_end(key);return ticket

    def preview(self,service,payload):
        doc=service.doc;service.guard(payload)
        frame=integer(payload.get('frame',doc.active_frame),'frame',0,len(doc.durations)-1)
        scale=integer(payload.get('scale',2),'scale',1,16)
        if doc.width*doc.height*scale*scale>4_194_304:raise PixelError('Material preview is too large')
        if not isinstance(payload.get('rebase',False),bool):raise PixelError('rebase must be boolean')
        prior=self.ticket(doc,payload['source_preview_id'],payload.get('rebase',False),revive=True)['material'] if payload.get('source_preview_id') else doc.material
        changed_source=prior is not None and prior['source_key']!=source_key(doc)
        old_size=prior['size'] if prior else [doc.width,doc.height]
        value=deepcopy(prior) if prior else {'format':'pixel-loom/material/v1','size':[doc.width,doc.height],
            'source_frames':len(doc.durations),'normal':[encode(Image.new('RGBA',(doc.width,doc.height),(128,128,255,255)))],
            'specular':[],'settings':deepcopy(DEFAULTS),'source_key':source_key(doc),'normal_origin':'flat'}
        value['settings']=settings(payload.get('settings'),value['settings'])
        if 'emission_layers' in (payload.get('settings') or {}):
            for layer in value['settings']['emission_layers']:doc.layer(layer)
        source=payload.get('normal_source')
        if source is not None:
            fields(source,NormalSource.__annotations__,'normal source')
            kind=source.get('kind','current')
            if kind=='current':
                if set(source)-{'kind','frames'}:raise PixelError('current normal source accepts only an optional frame count')
                if 'frames' in source:
                    count=integer(source['frames'],'normal frames',1,len(doc.durations))
                    if count not in (1,len(doc.durations)):raise PixelError('Normal maps must be shared or per-frame')
                    compatible(value,doc)
                    if count==1:value['normal']=[value['normal'][0 if len(value['normal'])==1 else frame]]
                    elif len(value['normal'])==1:value['normal']*=count
                    value['source_frames']=len(doc.durations)
            elif kind=='flat':
                if set(source)-{'kind','frames'}:raise PixelError('flat normal source accepts only an optional frame count')
                count=integer(source.get('frames',1),'normal frames',1,len(doc.durations))
                if count not in (1,len(doc.durations)):raise PixelError('Normal maps must be shared or per-frame')
                value['normal']=[encode(Image.new('RGBA',(doc.width,doc.height),(128,128,255,255)))]*count;value['normal_origin']=kind
                value['size']=[doc.width,doc.height];value['source_frames']=len(doc.durations)
            elif kind in ('import','height','silhouette'):
                allowed={'kind','path','columns','frames'} if kind=='import' else {'kind','path','columns','frames','strength'} if kind=='height' else {'kind','bevel','strength','layers'}
                if set(source)-allowed:raise PixelError('Fields do not belong to this normal source',details={'allowed_fields':sorted(allowed)})
                strength=number(source.get('strength',4.),'generation strength',.01,64.)
                if kind=='silhouette':
                    bevel=number(source.get('bevel',3.),'bevel',.1,64.)
                    layers=source.get('layers')
                    if layers is not None:
                        layers=layer_ids(layers)
                        if not layers:raise PixelError('Choose nonempty source layers')
                        for layer in layers:doc.layer(layer)
                    maps=[generate_normal(doc.composite(i,layers=layers).getchannel('A').filter(ImageFilter.GaussianBlur(bevel)),strength) for i in range(len(doc.durations))]
                else:
                    if not source.get('path'):raise PixelError('A map source path is required')
                    count=source.get('frames',1)
                    if count not in (1,len(doc.durations)):raise PixelError('Map frames must be shared or match this animation')
                    maps=import_maps(service.resolve(source['path']),(doc.width,doc.height),count,source.get('columns',1))
                    if kind=='height':maps=[generate_normal(image,strength) for image in maps]
                value.update(normal=[encode(image) for image in maps],normal_origin=kind,size=[doc.width,doc.height],source_frames=len(doc.durations))
            else:raise PixelError('Unknown normal source')
        if payload.get('specular_path') is not None:
            path=payload['specular_path']
            value['specular']=[] if path=='' else [encode(image) for image in import_maps(service.resolve(path),(doc.width,doc.height))]
        cleared_mask=False
        if source and source.get('kind') not in (None,'current') and value['specular'] and payload.get('specular_path') is None and (
            old_size!=[doc.width,doc.height] or len(value['specular']) not in (1,len(doc.durations))):
            value['specular']=[];cleared_mask=True
        compatible(value,doc)
        if payload.get('normal_edits'):
            maps=[decode(data,tuple(value['size'])) for data in value['normal']]
            value['normal']=[encode(image) for image in paint(maps,payload['normal_edits'],frame,len(doc.durations))]
            if value['normal_origin'] not in ('silhouette','height'):value['normal_origin']='painted'
        value['source_key']=source_key(doc);value=validate_material(value)
        view=payload.get('view','comparison')
        if view not in ('comparison','source','normal','render'):raise PixelError('Unknown material preview view')
        limit=integer(payload.get('preview_limit',512),'preview_limit',32,512)
        if view=='normal':limit=512  # Brush/data inspection stays on the native grid.
        factor=min(1,limit/max(doc.width,doc.height));preview_size=(max(1,round(doc.width*factor)),max(1,round(doc.height*factor)))
        digest=hashlib.sha256(json.dumps([value,frame,scale,view,limit],sort_keys=True).encode()).hexdigest()
        key=uuid.uuid4().hex
        self.previews[key]={'document_id':doc.id,'revision':doc.revision,'frame':frame,'view':view,'material':value,'created':time.monotonic()}
        while len(self.previews)>8 or sum(sum(len(data) for group in (t['material']['normal'],t['material']['specular']) for data in group) for t in self.previews.values())>64_000_000:
            old=next((item for item in self.previews if item not in self.pinned and item!=key),None)
            if old is None:break  # At most the live UI draft plus the newest result survive large-map pressure.
            self.previews.pop(old)
        result={'ok':True,'document_id':doc.id,'revision':doc.revision,'preview_id':key,'image_key':digest,
                'frame':frame,'settings':deepcopy(value['settings']),'normal_origin':value['normal_origin'],
                'approximate':value['normal_origin'] in ('silhouette','height'),
                'normal_frames':len(value['normal']),'color_pixels_unchanged':True,
                'logical_size':[doc.width,doc.height],'preview_size':list(preview_size),'preview_limited':factor<1,
                'unchanged':payload.get('if_image_key')==digest,'image_roles':[]}
        if changed_source:result['alignment_warning']='Color art changed: inspect the updated preview before applying these maps.'
        if cleared_mask:result['mask_warning']='An incompatible old specular mask was omitted from this new-map preview; saved material remains intact until apply.'
        if len(doc.durations)>1 and len(value['normal'])==1 and value['normal_origin']!='flat':result['warning']='Shared map: inspect alignment in every moving frame, or import/generate per-frame maps.'
        if not result['unchanged']:
            start=time.perf_counter()
            if view=='normal':images=[map_at(value,'normal',frame),render(doc,value,frame)];roles=['normal_data','lighting_preview']
            elif view=='render':images=[render(doc,value,frame,limit=limit)];roles=['lighting_preview']
            elif view=='source':images=[doc.composite(frame).resize(preview_size,Image.Resampling.NEAREST),render(doc,value,frame,limit=limit)];roles=['original_color','lighting_preview']
            else:images=[render(doc,value,frame,flat=True,limit=limit),render(doc,value,frame,limit=limit)];roles=['flat_surface_lighting','normal_map_lighting']
            result['images_png']=[encode(displayed(image,value['settings']['background']).resize((preview_size[0]*scale,preview_size[1]*scale),Image.Resampling.NEAREST)) for image in images]
            result['image_roles']=roles;result['render_ms']=round((time.perf_counter()-start)*1000,2)
        return result

    def action(self,service,payload):
        action=payload.get('action','status')
        common={'action','expected_document_id','expected_revision'}
        allowed={'status':{'action'},'preview':common|{'settings','normal_source','specular_path','normal_edits','source_preview_id','frame','view','scale','if_image_key','rebase','preview_limit'},
                 'apply':common|{'preview_id'},'clear':common,'export':common|{'preview_id','path','kind','all_frames','columns','scale','overwrite','background'}}
        if action not in allowed:raise PixelError('Unknown material action')
        fields(payload,allowed[action],'material action')
        if action=='status':return {'ok':True,'document_id':service.doc.id,'revision':service.doc.revision,**self.status(service.doc)}
        if action=='preview':return self.preview(service,payload)
        service.guard(payload)
        if action=='export':return self.export(service,payload)
        value=self.ticket(service.doc,payload.get('preview_id'))['material'] if action=='apply' else None
        storage_warning=None
        if value!=service.doc.material:
            service.doc.apply([{'op':'material_context','data':value}], '应用光照材质' if value else '清除光照材质')
            try:service.autosave()
            except OSError as error:storage_warning=str(error)
        return {'ok':True,'document_id':service.doc.id,'revision':service.doc.revision,'can_undo':bool(service.doc.undo_stack),
                'can_redo':bool(service.doc.redo_stack),'unsaved_changes':service.dirty,'applied':True,
                **({'storage_warning':storage_warning} if storage_warning else {}),**self.status(service.doc)}

    def export(self,service,payload):
        import numpy as np
        from .sheet_export import write_bundle
        doc=service.doc;ticket=self.ticket(doc,payload.get('preview_id'));record=ticket['material'];compatible(record,doc)
        path=service.resolve(payload.get('path',''));kind=payload.get('kind','render')
        if kind not in ('normal','render','sheet','bundle'):raise PixelError('Unknown material export kind')
        if path.suffix.lower()!=('.zip' if kind in ('bundle','sheet') else '.png'):raise PixelError('Material export needs PNG or ZIP for the selected kind')
        if not isinstance(payload.get('overwrite',False),bool) or not isinstance(payload.get('all_frames',False),bool):raise PixelError('Export flags must be boolean')
        if path.exists() and not payload.get('overwrite',False):raise PixelError('Material output already exists',code='FILE_EXISTS')
        frames=list(range(len(doc.durations))) if payload.get('all_frames',False) and kind in ('bundle','sheet') else [ticket['frame']]
        scale=integer(payload.get('scale',1),'export scale',1,16);columns=integer(payload.get('columns',min(8,len(frames))),'columns',1,len(frames))
        if doc.width*doc.height*len(frames)*scale*scale>16_777_216:raise PixelError('Material export exceeds 16M pixels')
        background=payload.get('background','transparent')
        if background not in ('transparent','dark','light'):raise PixelError('Export background must be transparent, dark or light')
        metadata={'format':'pixel-loom/material-preview/v1','document_id':doc.id,'revision':doc.revision,
                  'delivery_status':'material_preview','visual_review':'not_certified_by_color_review',
                  'size':[doc.width,doc.height],'settings':record['settings'],'normal_origin':record['normal_origin'],
                  'normal_convention':'X+ Y-up Z+; green=up','columns':columns,
                  'emission_content':'Visible emission after upper-layer occlusion; emission strength baked. Color atlas retains original artwork.',
                  'atlas_size':[doc.width*columns*scale,doc.height*math.ceil(len(frames)/columns)*scale],
                  'frames':[{'index':n,'source_index':i,'x':n%columns*doc.width*scale,'y':n//columns*doc.height*scale,
                             'width':doc.width*scale,'height':doc.height*scale,'duration_ms':doc.durations[i]} for n,i in enumerate(frames)]}
        def png(image):
            output=io.BytesIO();info=PngImagePlugin.PngInfo();info.add_text('pixel_loom_material',json.dumps(metadata,ensure_ascii=False))
            image.save(output,format='PNG',pnginfo=info);return output.getvalue()
        def normal_image(frame):
            normals=normal_vectors(map_at(record,'normal',frame),record['settings'])
            return Image.fromarray(np.rint((normals+1)*127.5).astype('uint8'),'RGB').convert('RGBA')
        def sheet(images):
            result=Image.new('RGBA',(doc.width*columns,doc.height*math.ceil(len(images)/columns)))
            for i,image in enumerate(images):result.paste(image,((i%columns)*doc.width,(i//columns)*doc.height))
            return result.resize((result.width*scale,result.height*scale),Image.Resampling.NEAREST) if scale!=1 else result
        if kind in ('normal','render'):
            image=normal_image(frames[0]) if kind=='normal' else displayed(render(doc,record,frames[0]),background)
            if scale!=1:image=image.resize((image.width*scale,image.height*scale),Image.Resampling.NEAREST)
            data=png(image)
        else:
            files={}
            if kind=='sheet':files['render.png']=png(sheet([displayed(render(doc,record,i),background) for i in frames]))
            else:
                files['color.png']=png(sheet([doc.composite(i) for i in frames]))
                files['normal.png']=png(sheet([normal_image(i) for i in frames]))
                files['specular.png']=png(sheet([map_at(record,'specular',i) or Image.new('RGBA',(doc.width,doc.height),'white') for i in frames]))
                files['emission.png']=png(sheet([emission_image(doc,record,i) for i in frames]))
                files['material.tres']=('\n'.join(['[gd_resource type="CanvasTexture" load_steps=4 format=3]',
                    '[ext_resource type="Texture2D" path="color.png" id="1"]','[ext_resource type="Texture2D" path="normal.png" id="2"]',
                    '[ext_resource type="Texture2D" path="specular.png" id="3"]','[resource]','diffuse_texture = ExtResource("1")',
                    'normal_texture = ExtResource("2")','specular_texture = ExtResource("3")',
                    'specular_color = Color('+', '.join([str(record['settings']['specular'])]*3+['1'])+')',
                    f'specular_shininess = {record["settings"]["shininess"]}','texture_filter = 1',''])).encode('utf-8')
                files['README.txt']=('Optional material preview, not a final visual certification. Keep all files together.\n'
                    'Godot: use material.tres on Sprite2D and add Light2D. Sheet frames share identical color/normal coordinates.\n'
                    'emission.png contains visible emission with upper-layer occlusion and emission strength baked in.\n'
                    'Connect emission/glow separately in the target engine; color.png still contains original artwork, so avoid counting the same emission twice.\n'
                    'Existing painted highlights are not removed. Generated normals are approximate. Original color pixels remain untouched.\n').encode()
            files['frames.json']=json.dumps(metadata,ensure_ascii=False,indent=2).encode('utf-8')
            output=io.BytesIO()
            with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
                for name,content in files.items():archive.writestr(name,content)
            data=output.getvalue()
        write_bundle({path:data})
        return {'ok':True,'path':str(path),'kind':kind,'frames':frames,'delivery_status':'material_preview',
                'color_pixels_unchanged':True,'bytes':len(data)}
