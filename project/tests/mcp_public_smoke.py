"""Isolated public-client workflow: discover -> learn -> validate -> draw -> animate -> export.

Uses a temporary data directory and a temporary working directory, never the user's live editor.
"""
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pixel_workbench import __version__


def data(response):
    if response.isError:
        raise AssertionError(response.content)
    return response.structuredContent or json.loads(next(block.text for block in response.content if block.type == "text"))


async def run(artifacts=None, server_executable=None):
    with tempfile.TemporaryDirectory(prefix="pixel-loom-mcp-") as folder:
        root = Path(folder)
        workspace, home = root / "workspace", root / "data"
        workspace.mkdir()
        prefix = ["--mcp"] if server_executable else ["-m", "pixel_workbench", "--mcp"]
        params = StdioServerParameters(command=str(server_executable or sys.executable),
            args=[*prefix, "--headless", "--data-dir", str(home), "--workspace", str(workspace)],
            cwd=str(workspace))
        async with AsyncExitStack() as stack:
            sessions = []
            for _ in range(2):
                reader, writer = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(reader, writer))
                initialized = await session.initialize()
                assert initialized.serverInfo.version == __version__
                assert "pixel_onboard" in initialized.instructions
                assert "ready by default" in initialized.instructions
                assert "feedback_images" in initialized.instructions
                sessions.append(session)
            first, second = sessions
            tools = await first.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"pixel_onboard", "pixel_validate", "pixel_contact_sheet", "pixel_edit"} <= names
            edit_tool = next(tool for tool in tools.tools if tool.name == "pixel_edit")
            encoded_schema = json.dumps(edit_tool.inputSchema)
            assert "polygon" in encoded_schema and "region_transform" in encoded_schema
            assert "additionalProperties" in encoded_schema
            resources = await first.list_resources()
            assert {"pixel-loom://guide", "pixel-loom://schema/operations", "pixel-loom://recipes",
                    "pixel-loom://workflow"} <= {str(resource.uri) for resource in resources.resources}
            prompts = await first.list_prompts()
            assert len(prompts.prompts) == 4
            guide = data(await first.call_tool("pixel_onboard", {}))
            assert "one-time server registration" in guide["desktop_workflow"]
            assert guide["current_document"]["editor"]["mode"] == "headless"
            # Windows may supply an 8.3 TEMP path; the application resolves it
            # to its long form. Compare the directory identity, not spelling.
            assert Path(guide["workspace"]["workspace"]).resolve() == workspace.resolve()
            state = data(await first.call_tool("pixel_project", {"action": "new", "width": 32, "height": 32, "name": "MCP public test"}))
            ops = guide["starter_recipe"]["ops"]
            observed = {"expected_revision": state["revision"], "expected_document_id": state["document_id"]}
            dry = await first.call_tool("pixel_validate", {"ops": ops, **observed})
            assert data(dry)["dry_run"] and any(block.type == "image" for block in dry.content)
            unchanged = data(await second.call_tool("pixel_status", {}))
            assert unchanged["revision"] == state["revision"]
            request = {"ops": ops, **observed, "request_id": "native-sprite", "include_preview": True}
            drawn = await first.call_tool("pixel_edit", request)
            state = data(drawn)
            assert any(block.type == "image" for block in drawn.content)
            repeated = data(await second.call_tool("pixel_edit", request))
            assert repeated["replayed"] and repeated["revision"] == state["revision"]
            stale = await second.call_tool("pixel_edit", {"ops": [{"op": "clear"}], **observed})
            assert stale.isError and stale.structuredContent["code"] == "REVISION_CONFLICT"
            protected = await first.call_tool("pixel_project", {"action": "new", "width": 16, "height": 16})
            assert protected.isError and protected.structuredContent["code"] == "UNSAVED_CHANGES"
            recipe_resource = await first.read_resource("pixel-loom://recipes")
            recipes = json.loads(recipe_resource.contents[0].text)
            state = data(await first.call_tool("pixel_status", {}))
            state = data(await first.call_tool("pixel_edit", {"ops": recipes["animate_starter"]["ops"],
                "expected_revision": state["revision"], "expected_document_id": state["document_id"], "include_preview": False}))
            assert len(state["frames"]) == 3 and state["tags"][0]["name"] == "idle"
            contact = await first.call_tool("pixel_contact_sheet", {"tag": "idle", "scale": 3})
            assert not contact.isError and any(block.type == "image" for block in contact.content)
            inspection = data(await first.call_tool("pixel_inspect", {"region": "face", "layer": "eyes", "frame": 1}))
            assert inspection["rect"] == [10, 14, 12, 8]
            state = data(await first.call_tool("pixel_project", {"action": "save", "path": "projects/public-test.pixloom"}))
            assert not state["unsaved_changes"]
            review=data(await first.call_tool("pixel_review",{"tag":"idle","layers":["body","eyes"],"show_in_editor":False}))
            state=data(await first.call_tool("pixel_review_submit",{"review_id":review["review_id"],
                "visual_checks":[{"criterion_id":c["id"],"verdict":"pass","reason":"Protocol fixture assertion; not a production artistic judgment."} for c in review["criteria"]],
                "warning_resolutions":[{"warning_id":w["id"],"verdict":"acceptable","reason":"Intentional fixture motion for protocol coverage."} for w in review["warnings"]],
                "method":"frames_and_timing","summary":"Automated protocol fixture review", "expected_revision":state["revision"],"expected_document_id":state["document_id"]}))
            assert state["review"]["status"]=="passed"
            state=data(await first.call_tool("pixel_project",{"action":"save"}))
            for kind, name in (("sheet", "public-sheet.png"), ("gif", "public.gif")):
                exported = data(await first.call_tool("pixel_export", {"path": "exports/" + name, "kind": kind, "tag": "idle", "layers": ["body", "eyes"]}))
                assert Path(exported["path"]).is_file()
            collision = await first.call_tool("pixel_export", {"path": "exports/public-sheet.png", "kind": "sheet"})
            assert collision.isError and collision.structuredContent["code"] == "FILE_EXISTS"
            prompt = await first.get_prompt("draw_sprite", {"brief": "a small forest creature"})
            assert prompt.messages
            if artifacts:
                import shutil, base64
                destination = Path(artifacts)
                destination.mkdir(parents=True, exist_ok=True)
                shutil.copy2(workspace / "projects" / "public-test.pixloom", destination / "quickstart.pixloom")
                shutil.copy2(workspace / "exports" / "public.gif", destination / "quickstart.gif")
                image = next(block for block in contact.content if block.type == "image")
                (destination / "contact-sheet.png").write_bytes(base64.b64decode(image.data))
            from pixel_workbench.operations import SPECS
            summary = {"ok": True, "clients": 2, "tools": len(names), "native_operations": len(SPECS),
                       "resources": len(resources.resources), "prompts": len(prompts.prompts),
                       "checks": ["portable module launch", "typed operation discovery", "onboarding recipe", "dry-run image",
                                  "native polygon/curve drawing", "retry idempotency", "structured conflicts", "unsaved protection",
                                  "resource-driven animation", "contact sheet", "local region inspection", "tagged/layer-filtered export"]}
            print(json.dumps(summary, indent=2))
        # No MCP client owns the backend's lifetime. Check it remains alive, then
        # close this isolated test instance through its authenticated local bridge.
        from pixel_workbench.cli import Client
        client = Client(home / "runtime" / "session.json")
        alive = client.request("/state")
        assert alive["name"] == "MCP public test"
        client.mutate("/shutdown")
        for _ in range(100):
            if not (home / "runtime" / "session.json").exists():
                break
            await asyncio.sleep(.05)
        assert not (home / "runtime" / "session.json").exists()
        # The session disappears just before the detached interpreter exits.
        # Windows can still hold its workspace/lock files for a moment; plain
        # rmtree with bounded retries avoids tempfile's recursive error handler.
        from tests import cleanup_runtime
        await cleanup_runtime(root)


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else None))
