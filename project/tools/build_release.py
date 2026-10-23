"""Build a shareable source bundle from an allowlist, excluding all private workspace state."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP = ["README.md", "README.en.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "CONTRIBUTORS.md", "SECURITY.md",
       "THIRD_PARTY_NOTICES.md", "AGENTS.md", "CLAUDE.md", ".gitignore", "MANIFEST.in", "pyproject.toml", "requirements.txt",
       "setup.ps1", "launch.ps1", "打开像素织机.cmd", "mcp_server.py"]
TREES = ["pixel_workbench", "skills", "tests", ".github"]
DOCS = ["USER_GUIDE.md", "AI_GUIDE.md", "ARCHITECTURE.md", "RELEASE.md", "operations.schema.json"]
EXTRA = ["integrations/connect.py", "integrations/codex.toml", "integrations/claude-desktop.json",
         "tools/build_release.py", "tools/package_windows.py", "tools/package_handoff.py", "tools/frozen_entry.py", "tools/windows.spec"]
PRIVATE_MARKERS = [re.compile(r"[A-Za-z]:[\\/]+xyx[0-9]+", re.I), re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.I),
                   re.compile(r"wxid_[a-zA-Z0-9_]+"), re.compile(r"xwechat_files", re.I)]


def documentation_files(root=ROOT):
    """Ship maintained documentation, never arbitrary local plans dropped in docs/."""
    paths = [root / "docs" / name for name in DOCS]
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Release file missing: docs/{path.name}")
    return paths


def source_files(root=ROOT):
    selected = []
    for name in TOP + EXTRA:
        path = root / name
        if not path.is_file():
            raise ValueError(f"Release file missing: {name}")
        selected.append(path)
    for name in TREES:
        for path in sorted((root / name).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".pyo"):
                selected.append(path)
    return sorted(set(selected + documentation_files(root)))


def audit(paths, root=ROOT):
    for path in paths:
        relative = path.relative_to(root)
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Release file points outside the source tree: {relative}")
        if any(part in (".runtime", ".venv", ".codex", "projects", "assets", "research") for part in relative.parts):
            raise ValueError(f"Private path entered release: {relative}")
        if path.suffix in (".py", ".md", ".json", ".toml", ".ps1", ".cmd", ".yml", ".txt", ".spec"):
            text = path.read_text(encoding="utf-8-sig")
            # This audit's marker declarations intentionally describe what to reject.
            if relative.as_posix() != "tools/build_release.py" and any(pattern.search(text) for pattern in PRIVATE_MARKERS):
                raise ValueError(f"Machine-specific path or private reference found in {relative}")
    return {"files": len(paths), "source_bytes": sum(path.stat().st_size for path in paths), "private_state_excluded": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    from pixel_workbench import __version__
    paths = source_files()
    report = audit(paths)
    from pixel_workbench.operations import full_schema
    schema_path = ROOT / "docs" / "operations.schema.json"
    if not schema_path.exists() or json.loads(schema_path.read_text(encoding="utf-8")) != full_schema():
        raise ValueError("docs/operations.schema.json is out of date; regenerate it from operations.full_schema()")
    if not args.check:
        folder = ROOT / "dist"
        folder.mkdir(exist_ok=True)
        target = folder / f"pixel-loom-{__version__}-source.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, Path(f"pixel-loom-{__version__}") / path.relative_to(ROOT))
        report.update({"archive": target.name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        (folder / "source-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
