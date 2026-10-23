# Contributing

See [CONTRIBUTORS.md](CONTRIBUTORS.md) for acknowledgments and the complete GitHub contributor graph. Preserve original commit authorship when merging. Contributions to code, tests, design and issue diagnosis may also be acknowledged there with a link to their PR or issue.

Start in the source directory containing `pyproject.toml`: from the root of a Git clone or the complete source ZIP, run `cd project` first. Install Python 3.11+ and a virtual environment, then run `python -m pip install -e '.[dev]'` with that environment activated. A source checkout does not include the portable Windows executables; normal users can download the Windows asset from [Releases](https://github.com/yangsir2077/pixel-loom/releases).

```sh
python -m unittest discover -s tests -v
python -m tests.mcp_public_smoke
python -m ruff check pixel_workbench tests tools/build_release.py
python tools/build_release.py --check
```

The MCP smoke test launches an isolated headless backend and two standard clients from a temporary directory. It does not edit the user's open project. Desktop visual checks are separate and require a display.

`model.py` owns artwork/history. `operations.py` owns operation schemas and derives MCP types; do not duplicate schemas in another layer. `service.py` owns shared file/concurrency behavior. `app.py` and `headless.py` host the same service. `mcp_server.py` exposes typed tools/resources/prompts. `paths.py` owns portable user-data paths.

Add a regression test for behavior changed by a bug fix. For new operations, keep model validation, machine schemas, focused help and runnable recipes consistent. Never log session tokens or model credentials to stdout; MCP uses stdout for JSON-RPC.

Describe the user-visible problem and resulting behavior in a pull request. Keep generated exports, private artwork, reference media and client configuration out of the application repository. The release builder uses an allowlist instead of zipping the entire workspace.
