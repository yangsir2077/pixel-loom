# Shared-library portable folder: windowed GUI + a console MCP entry point.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

repo = Path(SPECPATH).parent
datas = [(str(repo / "pixel_workbench" / "resources"), "pixel_workbench/resources")]
for dependency in ("mcp", "Pillow", "numpy", "jsonschema"):
    datas += copy_metadata(dependency, recursive=True)
hidden = collect_submodules("pixel_workbench") + ["win32com.client", "pythoncom", "PIL._tkinter_finder"]
a = Analysis([str(repo / "tools" / "frozen_entry.py")], pathex=[str(repo)], binaries=[], datas=datas,
             hiddenimports=hidden, hookspath=[], runtime_hooks=[],
             excludes=["pandas", "matplotlib", "cv2", "IPython", "pytest"], noarchive=False)
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PixelLoom", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False)
mcp = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PixelLoomMCP", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=True)
coll = COLLECT(gui, mcp, a.binaries, a.datas, strip=False, upx=False, name="PixelLoom")
