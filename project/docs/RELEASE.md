# Release preparation

The repository can be prepared locally without publishing a repository, uploading artwork or changing accounts.

```powershell
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m tests.mcp_public_smoke
python -m tests.mcp_api_first_batch_smoke
python -m tests.mcp_tag_quality_smoke
python -m tests.mcp_export_formats_smoke
python -m tests.mcp_creation_smoke
python -m tests.mcp_task_smoke
python -m tests.mcp_material_smoke
python -m tests.mcp_reference_smoke
python -m tests.mcp_cutout_smoke
python -m tests.mcp_quality_smoke
python -m tests.mcp_feedback_smoke
python -m tests.mcp_projects_smoke
python -m tests.mcp_storage_smoke
python -m tests.mcp_character_smoke
python -m tests.gui_smoke
python -m tests.gui_material_smoke
python -m tests.gui_tag_quality_smoke
python -m tests.gui_export_formats_smoke
python -m tests.gui_editing_smoke
python -m tests.gui_overflow_smoke
python -m tests.gui_layout_smoke
python -m tests.gui_cutout_smoke
python -m tests.gui_updates_smoke
python -m tests.gui_welcome_smoke
python -m tests.gui_feedback_smoke
python -m tests.gui_capture_smoke
python -m tests.gui_projects_smoke
python -m tests.gui_project_navigation_smoke
python -m tests.gui_workflow_smoke
python -m tests.gui_storage_smoke
python -m tests.gui_character_smoke
python tools/build_release.py --check
python tools/build_release.py
python -m build
```

The source ZIP uses an explicit allowlist. Private artwork, reference media, third-party research artifacts, client registration records, local tokens, virtual environments and build caches stay out. The sdist also prunes private workspace trees. The wheel contains the application package, intentionally supplied optional support-screen images.

Maintain the documentation allowlist in tools/build_release.py and MANIFEST.in together. Source and portable packages include maintained guides/schema, not arbitrary local design drafts in docs/. An old portable staging folder containing extra documentation fails packaging without deleting those files; use a clean staging folder. Keep formal tests in the source bundle; local logs and build outputs belong outside the repository.

For local engine verification, run `python -m tests.godot_export_smoke --godot <Godot-4-console-executable>` (optional `--artifacts <isolated-output-folder>`). Godot is not a runtime dependency and is not bundled. This imports the PNGs in a real headless editor, loads SpriteFrames, and checks texture regions/pixels, relative paths, variable durations, loop and reverse/pingpong order. Do not report engine validation when only JSON/unit checks ran.

## Windows portable folder

Install PyInstaller 6.x in the development environment, then:

```powershell
python -m PyInstaller tools/windows.spec --noconfirm
```

`dist/PixelLoom/PixelLoom.exe` is the native GUI. `PixelLoomMCP.exe --mcp` is the stdio server. Keep the whole folder together, including `_internal`.

The two executables share libraries. A dedicated console entry point is necessary for MCP JSON-RPC pipes. The GUI's MCP setup dialog generates a configuration pointing to that sibling console executable. No Python installation is intended on a recipient's machine; verify the bundled executables separately before sharing.

Run `PixelLoomMCP.exe --doctor` to inspect bundled dependency versions. For isolated protocol testing use `--mcp --headless --data-dir <temporary-dir> --workspace <temporary-workspace>`.

The PyInstaller folder above is the intermediate, flat runtime. First collect dependency notices from the matching build environment with `python tools/package_windows.py --folder dist/PixelLoom`. The collector reads the frozen import graph, including optional indirect dependencies, and prefers the runtime's own bundled metadata. It includes CFFI and Brotli when their native binaries are present, and fails if a bundled distribution has no license text. Keep the Python/Tk and transitive dependency license files too.

For the downloadable layout documented in the root README, use the verified application folder and the handoff packager:

```powershell
python tools/package_handoff.py --app ../app --output-dir dist
```

Or pass the verified `dist/PixelLoom` folder after adding its validation report and a SHA256SUMS.txt manifest containing every runtime file. The handoff packager verifies the manifest and native-component notices, then writes `PixelLoom/app/`, the allowlisted complete `PixelLoom/project/`, and the root guide/launcher. It does not modify the input application folder. Output may be directed outside the repository to keep a local handoff clean.

Include README, LICENSE and dependency notices in the folder archive. Keep release checksums and validation notes. The application code uses MIT; dependency code and notices retain their original licenses.

## Publishing releases for update checks

Desktop checks read the public releases list for `yangsir2077/pixel-loom`; no user authentication is required. Use a semantic version tag such as `v0.7.10`, write release notes and attach `pixel-loom-0.7.10-windows-x64.zip`. The matching Windows archive must be uploaded before the download button becomes available. Draft releases are ignored. Public previews are included by default for 0.x builds and clearly marked in the update window; users can choose the stable-only channel.

Existing installations without update checking must upgrade manually once. New builds query public version metadata only, in a background desktop thread. Preferences/cache stay in the per-user runtime and are not part of the distributable. Headless MCP never performs automatic checks. Keep release versions and Windows archive names consistent so clients can find the correct download.

Publishing, code signing, automatic installation, store submission and external GitHub CI execution are separate release actions and have not been performed by these local build commands.

Each published version gets its own immutable semantic tag and GitHub Release with versioned source/Windows archives, checksums and a validation report. Normally preserve earlier release assets and tags. For 0.7.10, the owner explicitly requested withdrawal of all earlier public releases and their version tags after the replacement is verified. Keep source commit history and user artwork intact. Version 0.7.8 was an internal preview included in 0.7.9; do not invent a separate 0.7.8 release. Push and verify the exact source commit in CI before publishing a new release.
