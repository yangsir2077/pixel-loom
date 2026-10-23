"""Add distribution notices and archive an already-tested portable build."""
from __future__ import annotations

from importlib.metadata import Distribution, distribution, packages_distributions
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pixel_workbench import __version__
from tools.build_release import documentation_files


def copy_documentation(folder, root=ROOT):
    target = folder / "docs"
    paths = documentation_files(root)
    allowed = {path.name for path in paths}
    unexpected = [path.relative_to(target).as_posix() for path in target.rglob('*')
                  if path.is_file() and path.relative_to(target).as_posix() not in allowed]
    if unexpected:
        raise ValueError('Unmaintained portable docs; use a clean staging folder: ' + ', '.join(sorted(unexpected)[:8]))
    target.mkdir(parents=True, exist_ok=True)
    for path in paths:
        shutil.copy2(path, target / path.name)


def component_names(folder):
    """Read the actual frozen import graph, including optional indirect imports."""
    from PyInstaller.archive.readers import CArchiveReader

    reader = CArchiveReader(str(folder / "PixelLoom.exe"))
    archive = reader.open_embedded_archive(next(name for name in reader.toc if name.endswith(".pyz")))
    modules = set(archive.toc)
    roots = {name.split(".")[0] for name in modules}
    owners = packages_distributions()
    names = {"pyinstaller", "mcp", "Pillow", "jsonschema", "pydantic", "pywin32"}
    for module in roots - sys.stdlib_module_names - {"pixel_workbench"}:
        if module.startswith("pyi"):
            continue
        distributions = owners.get(module, [])
        if distributions:
            for owner in distributions:
                if len(distributions) > 1:
                    candidates = []
                    for item in distribution(owner).files or []:
                        path = Path(item)
                        if path.suffix == ".py" and ".." not in path.parts:
                            qualified = path.with_suffix("").as_posix().replace("/", ".")
                            candidates.append(qualified.removesuffix(".__init__"))
                    if not any(name in modules for name in candidates):
                        continue  # Shared namespaces do not imply every installed owner is bundled.
                names.add(owner)
        elif module.startswith(("win32", "pywin")) or module in ("commctrl", "winerror"):
            names.add("pywin32")
        else:
            raise ValueError(f"Identify the distribution and license for bundled module {module}")
    for name, pattern in (("cffi", "_cffi_backend*"), ("Brotli", "_brotli*")):
        if any((folder / "_internal").glob(pattern)):
            names.add(name)
    return sorted({name.lower().replace("_", "-").replace(".", "-") for name in names})


def collect_notices(folder):
    """Prefer metadata already bundled with the runtime; use its build environment for optional imports."""
    folder = Path(folder)
    notices = folder / "THIRD_PARTY_LICENSES"
    notices.mkdir(exist_ok=True)
    canonical = lambda name: name.lower().replace("_", "-").replace(".", "-")
    bundled = {}
    for path in (folder / "_internal").glob("*.dist-info"):
        item = Distribution.at(path)
        bundled[canonical(item.metadata["Name"])] = item
    included = []
    for name in component_names(folder):
        dist = bundled.get(canonical(name)) or distribution(name)
        number = 0
        for item in dist.files or []:
            source = Path(dist.locate_file(item))
            if source.is_file() and any(word in source.name.lower() for word in ("license", "copying", "notice")):
                number += 1
                shutil.copy2(source, notices / f"{name}-{number}-{source.name}")
        if not number:
            raise ValueError(f"No license text found for bundled distribution {name}")
        included.append({"name": name, "version": dist.version, "notice_files": number})
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        shutil.copy2(python_license, notices / "Python-LICENSE.txt")
    (notices / "components.json").write_text(json.dumps(included, indent=2), encoding="utf-8")
    return included


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--folder',type=Path,default=ROOT/'dist'/'PixelLoom')
    args=parser.parse_args()
    folder = args.folder.resolve()
    if not (folder / "PixelLoom.exe").exists() or not (folder / "PixelLoomMCP.exe").exists():
        raise SystemExit("Build tools/windows.spec first")
    for name in ("README.md", "README.en.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "CONTRIBUTORS.md"):
        shutil.copy2(ROOT / name, folder / name)
    copy_documentation(folder)
    shutil.copytree(ROOT / "skills", folder / "skills", dirs_exist_ok=True)
    shutil.copy2(ROOT/'pixel_workbench/resources/FEEDBACK_IMAGE_GUIDE.md',folder/'截图反馈给AI.md')
    included = collect_notices(folder)
    target = ROOT / "dist" / f"pixel-loom-{__version__}-windows-x64.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, Path("PixelLoom") / path.relative_to(folder))
    report = {"artifact": target.name, "bytes": target.stat().st_size,
              "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
              "executables": ["PixelLoom.exe", "PixelLoomMCP.exe"], "dependency_notices": included}
    (ROOT / "dist" / "windows-artifact.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "dependency_notices"}, indent=2))


if __name__ == "__main__":
    main()
