"""Real stdio clients retain/switch/fork projects and inspect paired animation evidence."""
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tests.mcp_public_smoke import data


async def run(server_executable=None):
    with tempfile.TemporaryDirectory(prefix='pixel-loom-projects-mcp-') as folder:
        root=Path(folder)
        args=['--mcp'] if server_executable else ['-m','pixel_workbench','--mcp']
        params=StdioServerParameters(command=str(server_executable or sys.executable),
                args=[*args,'--headless','--data-dir',str(root/'data'),'--workspace',str(root/'work')])
        async with AsyncExitStack() as stack:
            sessions=[]
            for _ in range(2):
                reader,writer=await stack.enter_async_context(stdio_client(params))
                session=await stack.enter_async_context(ClientSession(reader,writer))
                init=await session.initialize()
                assert "action='fork'" in init.instructions
                sessions.append(session)
            first,second=sessions
            definitions = {item.name:item for item in (await first.list_tools()).tools}
            tools = set(definitions)
            assert 'pixel_effect' not in tools and 'pixel_edit' in tools
            assert 'keep_project_id' in definitions['pixel_projects'].inputSchema['properties']
            guide=data(await first.call_tool('pixel_onboard',{}))
            state=guide['current_document']
            def tokens(state):return dict(expected_revision=state['revision'],expected_document_id=state['document_id'])
            idle=data(await first.call_tool('pixel_projects',dict(action='new',name='Idle',width=24,height=32,**tokens(state))))
            state=data(await first.call_tool('pixel_edit',dict(ops=[{'op':'pixel','x':4,'y':5,'color':7},
                *[{'op':'frame_add'} for _ in range(9)]],include_preview=False,**tokens(idle))))
            fork=data(await first.call_tool('pixel_projects',dict(action='fork',name='Walk',**tokens(state))))
            projects=fork['projects']
            idle_entry=next(p for p in projects if p['document_id']==state['document_id'])
            walk_entry=next(p for p in projects if p['active'])
            idle_bytes=Path(idle_entry['path']).read_bytes()
            state=data(await second.call_tool('pixel_edit',dict(ops=[{'op':'pixel','x':5,'y':5,'color':8}],
                                                              include_preview=False,**tokens(fork))))
            ids=[idle_entry['id'],walk_entry['id']]
            comparison=await first.call_tool('pixel_projects',dict(action='compare',project_ids=ids,page=0))
            compared=data(comparison)
            assert compared['read_only'] and compared['pages']==2
            assert len([item for item in comparison.content if item.type=='image'])==2
            page=data(await first.call_tool('pixel_projects',dict(action='compare',project_ids=ids,page=1)))
            assert page['projects'][0]['frames']==[8,9]
            unchanged=data(await second.call_tool('pixel_status',{}))
            assert unchanged['revision']==state['revision'] and unchanged['unsaved_changes']
            switched=data(await first.call_tool('pixel_projects',dict(action='switch',project_id=idle_entry['id'],**tokens(state))))
            assert switched['document_id']==idle_entry['document_id']
            assert Path(idle_entry['path']).read_bytes()==idle_bytes
            versions=data(await first.call_tool('pixel_projects',dict(action='versions',project_id=walk_entry['id'])))
            assert versions['versions']
            oldest = versions['versions'][-1]
            evidence=await first.call_tool('pixel_projects',dict(action='version_preview',project_id=walk_entry['id'],
                version_id=oldest['id'],page=1))
            assert data(evidence)['read_only'] and len([x for x in evidence.content if x.type=='image'])==2
            state=data(await first.call_tool('pixel_projects',dict(action='switch',project_id=walk_entry['id'],**tokens(switched))))
            count=len(versions['versions'])
            chosen=data(await second.call_tool('pixel_projects',dict(action='use_version',project_id=walk_entry['id'],
                version_id=oldest['id'],**tokens(state))))
            assert chosen['document_id']==walk_entry['document_id'] and len(chosen['projects'])==2
            assert chosen['revision']>state['revision'] and chosen['history_preserved']
            updated=data(await first.call_tool('pixel_projects',dict(action='versions',project_id=walk_entry['id'])))
            assert len(updated['versions'])>count
            stale=await first.call_tool('pixel_projects',dict(action='use_version',project_id=walk_entry['id'],
                version_id=oldest['id'],**tokens(state)))
            error = stale.structuredContent or json.loads(next(x.text for x in stale.content if x.type=='text'))
            assert stale.isError and error['code']=='REVISION_CONFLICT'
            switched=chosen
            restored=data(await first.call_tool('pixel_projects',dict(action='restore',project_id=walk_entry['id'],
                version_id=versions['versions'][0]['id'],name='Recovered walk',**tokens(switched))))
            assert restored['document_id'] not in (idle_entry['document_id'],walk_entry['document_id'])
            assert len(restored['projects'])==3
            closed=data(await first.call_tool('pixel_projects',dict(action='close',project_id=idle_entry['id'],**tokens(restored))))
            assert len(closed['projects'])==2 and Path(idle_entry['path']).is_file()
            assert idle_entry['id'] not in [entry['id'] for entry in closed['projects']]
            hidden=data(await second.call_tool('pixel_projects',dict(action='closed')))
            assert [entry['id'] for entry in hidden['projects']]==[idle_entry['id']]
            assert not data(await second.call_tool('pixel_projects',dict(action='deleted')))['projects']
            reopened=data(await second.call_tool('pixel_projects',dict(action='reopen',project_id=idle_entry['id'],**tokens(closed))))
            assert len(reopened['projects'])==3 and idle_entry['id'] in [entry['id'] for entry in reopened['projects']]
            assert not data(await second.call_tool('pixel_projects',dict(action='closed')))['projects']
            selected=data(await first.call_tool('pixel_projects',dict(action='switch',project_id=walk_entry['id'],**tokens(reopened))))
            kept=data(await second.call_tool('pixel_projects',dict(action='close',project_id=walk_entry['id'],
                keep_project_id=idle_entry['id'],**tokens(selected))))
            assert kept['document_id']==idle_entry['document_id']
            reopened=data(await first.call_tool('pixel_projects',dict(action='reopen',project_id=walk_entry['id'],**tokens(kept))))
            removed=data(await first.call_tool('pixel_projects',dict(action='remove',project_id=idle_entry['id'],**tokens(reopened))))
            assert len(removed['projects'])==2 and removed['files_preserved'] and Path(idle_entry['path']).is_file()
            deleted=data(await second.call_tool('pixel_projects',dict(action='deleted')))
            assert deleted['projects'][0]['id']==idle_entry['id']
            unremoved=data(await second.call_tool('pixel_projects',dict(action='undelete',project_id=idle_entry['id'],**tokens(removed))))
            assert unremoved['projects'][0]['number']==idle_entry['number']
            all_ids=[entry['id'] for entry in unremoved['projects']]
            empty=data(await first.call_tool('pixel_projects',dict(action='remove',project_ids=all_ids,**tokens(unremoved))))
            assert not empty['projects'] and empty['project_path'] is None
            assert empty['project_library']['deleted_count']==3
            back=data(await second.call_tool('pixel_projects',dict(action='undelete',project_ids=all_ids,**tokens(empty))))
            assert [entry['id'] for entry in back['projects']]==all_ids
            print(json.dumps({'ok':True,'clients':2,'checks':['discover project preservation instructions',
                'independent project identities and paths','checkpoint dirty source','no idle overwrite',
                'paged paired frame evidence','read-only compare preserves dirty state','shared project switch',
                'pre-save versions','restore as separate project','close hides a tab without touching its file',
                'closed list through second client','reopen restores the tab','reversible remove preserves files/history',
                'deleted list through second client','restore original ids/numbers','remove all leaves empty shelf']}))
        from pixel_workbench.cli import Client
        session_path=root/'data/runtime/session.json'
        Client(session_path).mutate('/shutdown')
        for _ in range(100):
            if not session_path.exists():break
            await asyncio.sleep(.05)
        assert not session_path.exists()
        from tests import cleanup_runtime
        await cleanup_runtime(root)


if __name__=='__main__':asyncio.run(run(Path(sys.argv[1]).resolve() if len(sys.argv)>1 else None))
