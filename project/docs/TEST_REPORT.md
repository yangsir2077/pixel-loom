# 测试报告 · 项目标签页关闭功能

- **分支 / 提交**：`star-find-cloud` @ `cab14ef`（Close project tabs without deleting projects）
- **日期**：2026-10-23
- **结论**：**通过** —— 292 个单元测试 + 35 个冒烟模块全部通过，0 失败

## 1. 被测变更

项目栏原先直接展示 `ProjectLibrary` 的全量列表，没有"关闭"概念。本次为其加入浏览器式关闭：

- 每个标签带 `×`，右键菜单提供「关闭此标签页 / 关闭左侧 / 关闭右侧 / 关闭其他」
- 关闭只写 `closed_at`，**不删除**工程文件、编号、id 和历史版本，也不进入"已删除"列表
- 关闭当前正在编辑的标签时，先保存未存改动，再切到右侧邻居（其次左侧，最后空工作区）
- 收起状态持久化到 `project-library.json`，可在「项目管理 → 已收起」重新打开
- MCP 侧 `pixel_projects` 同步新增 `close` / `closed` / `reopen`

## 2. 测试环境

| 项 | 值 |
|---|---|
| 操作系统 | Windows 11 专业版 build 22621（64 位） |
| Python | 3.12.13（`project/.venv`，uv 托管） |
| 依赖 | Pillow 12.3.0 / mcp 1.30.0 / jsonschema 4.26.0 / pywin32 312 / pydantic 2.14.1 |
| 项目版本 | pixel-loom 0.7.17（editable 安装） |
| 静态检查 | ruff 0.17.2 |
| Godot | 4.7.2.stable.mono.official.ed1daf0bf |
| 旧版后端 | 0.7.16 便携版 `E:\pixel-loom\PixelLoom\app\PixelLoomMCP.exe` |

依赖经清华镜像 `https://pypi.tuna.tsinghua.edu.cn/simple` 安装。

## 3. 结果汇总

| 测试集 | 数量 | 结果 |
|---|---|---|
| 单元测试 `unittest discover -s tests` | 292（2 skipped） | 通过 |
| GUI 冒烟 `gui_*smoke` | 17 | 17 / 17 |
| MCP 冒烟 `mcp_*smoke` | 17 | 17 / 17 |
| Godot 导出验证 `godot_export_smoke` | 1 | 通过（真机） |
| Ruff（仓库配置 `E9/F63/F7/F82`） | — | All checks passed |

冒烟测试总计 35 个模块，全部通过；测试实例均使用隔离的 `--data-dir` / `--workspace`，结束后无残留进程与临时工程。

## 4. 参数化冒烟的实际输出

这两个脚本必须显式传入外部程序，否则只报 usage 错误，不构成失败。

### 4.1 Godot 导出验证

```json
{"ok": true, "animations": 2, "json_formats": 2, "relative_path": true,
 "durations": true, "reverse_pingpong": true, "loop": true, "pixels": true}
```

覆盖：SpriteFrames 图集矩形、逐帧毫秒时长、loop/pingpong/reverse、半透明像素不丢失、中文文件名 `中文 图集.tres`、`aseprite_hash` 与 `aseprite_array` 两种 JSON、选中 tag 的源索引重基。

### 4.2 旧版后端兼容矩阵

```json
{"ok": true, "current_version": "0.7.17", "legacy_version": "0.7.16",
 "mixed_versions": true,
 "checks": ["version mismatch rejected in both directions before mutation",
            "updated file opened/saved by released backend with identical pixels",
            "rejected mixed client preserves the running editor and task notes"],
 "isolated": true}
```

覆盖：跨版本客户端在**任何写入前**即被拒绝（双向）、0.7.16 后端能打开并保存 0.7.17 写出的工程且像素一致、被拒绝的混合客户端不影响运行中的编辑器与任务记录。

## 5. 本次新增用例（`tests/test_projects.py`，+8）

| 用例 | 验证点 |
|---|---|
| `test_close_hides_tab_without_touching_files_or_remove_list` | 文件字节不变、不进已删除 |
| `test_close_active_opens_right_neighbour_and_keeps_dirty_pixels` | 关当前项目切右邻居并保存未存像素 |
| `test_close_active_without_neighbour_leaves_clean_workspace` | 无邻居时留干净空工作区 |
| `test_close_persists_across_restart_and_reopen_restores_same_identity` | 重启后仍收起、重开保持 id/编号 |
| `test_switching_to_a_closed_project_reopens_its_tab` | 切到已收起项目自动恢复标签 |
| `test_remove_clears_the_closed_flag` | 删除清掉收起标记，不双重占位 |
| `test_close_rejects_unknown_ids_without_changing_tabs` | 非法 id 整体拒绝、标签不变 |
| `test_project_library_counts_separate_open_and_closed` | `open_count` / `closed_count` 计数正确 |

GUI 冒烟额外覆盖 `×` 控件存在与绑定、关闭后标签消失、重开后标签回归；MCP 冒烟新增 `close` / `closed` / `reopen` 三段的双客户端断言。

## 6. 跳过项与未覆盖

跳过的 2 个单元测试均为**平台权限**导致，与本次改动无关：

- `test_configuration_preserves_virtualenv_interpreter_symlink` —— 当前账户不能创建符号链接
- `test_symlink_cache_and_history_redirects_never_delete_external_files` —— 同上

本次**未验证**：

- macOS / Linux 桌面端（项目仅在 Windows 本地验证）
- 便携版重新打包后的行为（本次只验证源码运行；`app/` 为 0.7.16 旧包）
- 第三方 AI 客户端（Codex / Claude Desktop）的真实多轮使用；MCP 侧以 stdio 双客户端脚本代替

## 7. 复现

```powershell
Set-Location E:\ai-tools\pixel-loom\project
$py = '.venv\Scripts\python.exe'

# 单元测试
& $py -m unittest discover -s tests

# GUI 冒烟（逐个执行）
Get-ChildItem 'tests\gui_*smoke.py' | ForEach-Object { & $py -m ('tests.' + $_.BaseName) }

# MCP 冒烟（逐个执行）
Get-ChildItem 'tests\mcp_*smoke.py' | ForEach-Object { & $py -m ('tests.' + $_.BaseName) }

# 需要外部程序的两项
& $py -m tests.godot_export_smoke --godot 'D:\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64\Godot_v4.7.2-stable_mono_win64_console.exe'
& $py -m tests.mcp_legacy_art_compat_smoke --legacy-exe 'E:\pixel-loom\PixelLoom\app\PixelLoomMCP.exe'

# 静态检查
& '.venv\Scripts\ruff.exe' check .
```
