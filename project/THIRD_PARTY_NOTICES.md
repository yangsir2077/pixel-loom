# Third-party components

Pixel Loom application code is distributed under the MIT license in `LICENSE`.
Dependencies retain their own licenses. Python, Tk, Pillow, NumPy, the official MCP Python SDK, Pydantic, JSON Schema tooling, pywin32 on Windows and their transitive dependencies are not relicensed by this project.

NumPy supplies the optional local material renderer's numerical calculations. Portable builds include its metadata and license notices, including any native numerical-library notices supplied by that wheel.

Portable builds that include the optional CFFI or Brotli native modules also carry their corresponding license files in `THIRD_PARTY_LICENSES/`. Dependency notices inside `_internal/*.dist-info` and Tk's `_internal/_tk_data/license.terms` remain part of the distribution.

The source distribution declares dependencies in `pyproject.toml`; source installers obtain their original distributions. Windows portable builds include dependency metadata/license files collected by the build specification and PyInstaller hooks. Consult those files for exact notices for the built versions.

User projects, teaching samples and reference videos are not included in public release packages. The application does not bundle finished-art presets.

The maintainer explicitly supplied the WeChat receipt posters in `pixel_workbench/resources/support/` for the optional creator-support screen. They are distributed intentionally with this feature; private project artwork and reference media remain excluded.
