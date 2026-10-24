"""Fresh standard MCP material workflow in an isolated workspace; no model API."""
import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import zipfile

from PIL import Image
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pixel_workbench import __version__
from tests import cleanup_runtime


def data(result):
    value=result.structuredContent or json.loads(result.content[0].text)
    assert not result.isError,value
    return value


def tokens(state):return {'expected_document_id':state['document_id'],'expected_revision':state['revision']}


async def run(artifacts=None,server_executable=None):
    with tempfile.TemporaryDirectory(prefix='pixel-loom-material-mcp-') as folder:
        root=Path(folder);work=root/'work';work.mkdir();home=root/'data'
        params=StdioServerParameters(command=str(server_executable or sys.executable),
            args=[*(['--mcp'] if server_executable else ['-m','pixel_workbench','--mcp']),'--headless',
                  '--data-dir',str(home),'--workspace',str(work)],cwd=str(work))
        try:
            async with stdio_client(params) as streams:
                async with ClientSession(*streams) as session:
                    init=await session.initialize();assert init.serverInfo.version==__version__
                    tools=await session.list_tools();assert 'pixel_material' in {t.name for t in tools.tools}
                    guide=data(await session.call_tool('pixel_help',{'topic':'material_workflow'}))
                    assert 'height' in guide['guide'] and 'emission' in guide['guide']
                    state=data(await session.call_tool('pixel_status',{}))
                    state=data(await session.call_tool('pixel_projects',{'action':'new','width':19,'height':23,'name':'Material protocol fixture',**tokens(state)}))
                    state=data(await session.call_tool('pixel_edit',{'ops':[{'op':'rect','x':3,'y':4,'width':10,'height':13,'color':7},
                            {'op':'frame_set','frame':0,'duration_ms':70},{'op':'frame_add','duration_ms':130}],**tokens(state),'compact':True}))
                    original=data(await session.call_tool('pixel_status',{}))
                    preview=data(await session.call_tool('pixel_material',{'action':'preview','normal_source':{'kind':'silhouette','bevel':2,'strength':4},'view':'normal','show_in_editor':True,**tokens(state)}))
                    assert preview['normal_frames']==2 and preview['approximate']
                    assert preview['viewer']['presented'] is False
                    current=data(await session.call_tool('pixel_status',{}));assert current['revision']==original['revision']
                    assert current['material']['configured'] is False
                    bad=await session.call_tool('pixel_material',{'action':'preview','settings':{'intensity':'wrong'},**tokens(state)})
                    assert bad.isError
                    brush=data(await session.call_tool('pixel_material',{'action':'preview','source_preview_id':preview['preview_id'],
                        'normal_edits':[{'op':'rect','frame':1,'rect':[5,5,3,3],'normal':[1,0,0]}],'frame':1,'view':'normal',**tokens(state)}))
                    state=data(await session.call_tool('pixel_material',{'action':'apply','preview_id':brush['preview_id'],**tokens(state)}))
                    assert state['configured'] and state['color_pixels_unchanged']
                    state=data(await session.call_tool('pixel_history',{'action':'undo',**tokens(state)}))
                    assert not data(await session.call_tool('pixel_material',{}))['configured']
                    state=data(await session.call_tool('pixel_history',{'action':'redo',**tokens(state)}))
                    assert data(await session.call_tool('pixel_material',{}))['configured']
                    current=data(await session.call_tool('pixel_status',{}));assert original['palette']==current['palette']
                    preview=data(await session.call_tool('pixel_material',{'action':'preview','frame':1,'view':'render',**tokens(state)}))
                    cached=data(await session.call_tool('pixel_material',{'action':'preview','frame':1,'view':'render','if_image_key':preview['image_key'],**tokens(state)}))
                    assert cached['unchanged'] and 'images_png' not in cached
                    export=data(await session.call_tool('pixel_material',{'action':'export','preview_id':preview['preview_id'],'kind':'bundle',
                                'all_frames':True,'columns':2,'path':'exports/material.zip',**tokens(state)}))
                    with zipfile.ZipFile(export['path']) as archive:
                        metadata=json.loads(archive.read('frames.json'))
                        assert [f['duration_ms'] for f in metadata['frames']]==[70,130]
                    state=data(await session.call_tool('pixel_edit',{'ops':[{'op':'pixel','x':0,'y':0,'color':7}],**tokens(state),'compact':True}))
                    stale=await session.call_tool('pixel_material',{'action':'apply','preview_id':preview['preview_id'],**tokens(state)})
                    assert stale.isError and stale.structuredContent['code']=='MATERIAL_PREVIEW_STALE'
                    rebased=data(await session.call_tool('pixel_material',{'action':'preview','source_preview_id':preview['preview_id'],'rebase':True,**tokens(state)}))
                    assert rebased['alignment_warning']
                    state=data(await session.call_tool('pixel_project',{'action':'save','path':'projects/material.pixloom'}))
                    if artifacts:
                        import shutil
                        target=Path(artifacts);target.mkdir(parents=True,exist_ok=True)
                        shutil.copy2(export['path'],target/'material.zip');shutil.copy2(work/'projects/material.pixloom',target/'material.pixloom')
                    print(json.dumps({'ok':True,'version':__version__,'checks':['fresh MCP discovery','on-demand guide','no art edits on preview',
                        'strict settings','per-frame normal brush','apply/undo/redo','palette preserved','conditional images',
                        'portable ZIP timing','stale preview rejected','explicit same-project rebase','editable save']}))
        finally:
            session_file=home/'runtime/session.json'
            if session_file.exists():
                from pixel_workbench.cli import Client
                Client(session_file).mutate('/shutdown',{'discard_changes':True})
            await cleanup_runtime(root)


if __name__=='__main__':asyncio.run(run())
