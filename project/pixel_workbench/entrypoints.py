"""Small console entry points; process options are resolved before runtime imports."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from . import __version__


def options(argv=None, mcp=False):
    parser = argparse.ArgumentParser(prog="pixel-loom-mcp" if mcp else "pixel-loom")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data-dir", type=Path, help="Isolated app data/runtime directory")
    parser.add_argument("--workspace", type=Path, help="Directory for projects and exports")
    parser.add_argument("--headless", action="store_true", help="Run document backend without a desktop window")
    parser.add_argument("--mcp", action="store_true", help="Serve standard MCP over stdio")
    parser.add_argument("--project", type=Path, help="Open an existing .pixloom document")
    parser.add_argument("--doctor", action="store_true", help="Print runtime/dependency diagnostics without opening a window")
    parser.add_argument("--launch-backend", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.data_dir:
        os.environ["PIXEL_LOOM_HOME"] = str(args.data_dir.expanduser().resolve())
    if args.workspace:
        os.environ["PIXEL_LOOM_WORKSPACE"] = str(args.workspace.expanduser().resolve())
    if args.headless:
        os.environ["PIXEL_LOOM_HEADLESS"] = "1"
    return args


def main(argv=None):
    args = options(argv)
    if args.launch_backend:
        from .detached_launcher import main as launch
        return launch()
    if args.doctor:
        import importlib.metadata
        import json
        import sys
        from .paths import description
        from .updates import API_URL
        result = {"version": __version__, "python": sys.version.split()[0], "executable": sys.executable,
                  "paths": description(), "dependencies": {name: importlib.metadata.version(name) for name in ("Pillow", "numpy", "mcp", "jsonschema")}}
        result["updates"] = {"release_source": API_URL, "startup_checks": "desktop only",
                             "download_behavior": "browser on explicit click"}
        try:
            import tkinter
            result["tk_version"] = tkinter.TkVersion
        except ImportError:
            result["tk_version"] = None
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.mcp:
        from .mcp_server import run
        return run()
    if args.headless:
        from .headless import main as headless
        return headless()
    from .app import main as desktop
    return desktop(args.project)


def mcp_main(argv=None):
    options(argv, mcp=True)
    from .mcp_server import run
    return run()


def cli_main():
    from .cli import main
    return main()
