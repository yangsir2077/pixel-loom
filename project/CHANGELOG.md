# Changelog

## 0.7.19 — 2026-10-24: optional normal maps and lighting

- Add an optional local normal-map/lighting workbench and `pixel_material` MCP parity: PNG/sheet import, flat/silhouette/explicit-height sources, direction brush, flat-versus-normal comparison, light/ambient/specular controls, emission layers in original order and per-frame maps.
- Keep preview drafts separate from color cels and palette. Apply/clear use shared undo and portable optional project metadata; stale bindings, oversized maps, unknown fields and cross-document previews fail safely. Preserve an open GUI draft against cache eviction and project switches. Existing color review/export semantics remain intact; material outputs are explicitly preview artifacts.
- Export effective normal/render PNGs or aligned material/render atlases with source timings, metadata and relative Godot CanvasTexture. Add NumPy to the local runtime and packaging notices; no game engine or model API is required for app previews.
- Put supplied-image pixelization first in MCP discovery, the legacy reference prompt and the command palette. Keep artistic redraw as an explicit optional scope and retain existing API identifiers. Remove the conversion UI's small fixed-size shortcuts and inert style-category selector; dimensions/colors remain freely editable, legacy style metadata and optional style references remain supported.
- Clarify source/material limits, independent glass/emission/glow work and optional technical normal-map authoring. Silhouette/height estimates stay labeled after local brush edits; they are not semantic 3D reconstruction. Interactive CPU preview performance depends on canvas/layer count.
- Reuse the existing task routes and bundled guides for static identity baselines, adaptive source/detail parameters, key-pose-first local motion, timing, seam inspection and repeated-defect structural diagnosis. No new content presets, automatic generation/cleanup, hidden filling or animation authorization.
- Remove fixed canvas/frame suggestions from the draw/animation prompt defaults while retaining explicit arguments and all native tools, project history, review and export behavior. Keep detailed steps in on-demand guides instead of a second prompt/checklist pipeline.
- Validate explicit emission layer ids, retain upper-layer occlusion and bake emission strength into exported emission maps. Original color atlases remain unchanged; engine integration must avoid counting emission twice.
- Synchronize the offline operation schema and NumPy dependency lists. Preserve existing project/tab/history, original color review gates and export formats; material exports remain explicitly labeled previews.

## 0.7.18 — 2026-10-23: browser-style project tabs

- Close a project tab from the × on the tab or from its right-click menu (close this tab / tabs to the left / tabs to the right / other tabs). Closing only hides the tab: the `.pixloom` file, project number, id and saved versions are untouched, and the project does not enter the removed list.
- Closing the tab being edited saves its dirty pixels first, then opens the tab to the right (else the left, else a clean empty workspace). A batch close can name the tab that must survive.
- Hidden tabs persist in `project-library.json` as `closed_at` and appear under “项目管理 → 已收起”. Reopening restores the same identity and number, and switching to a closed project reopens its tab automatically.
- MCP parity: `pixel_projects` gains `close` / `closed` / `reopen`; `project_library` reports `open_count` and `closed_count` next to the existing counts.
- Tests: unit cases for close, reopen, persistence across restart and neighbour switching, plus GUI coverage of the × control and the reopen flow.
- Skip missing or corrupt neighbours until another valid open tab is found, and keep the × usable for unavailable inactive files. Expose keep_project_id in the MCP schema and verify it through real clients.
- Add contributor acknowledgments and README links, preserve original commit authorship, and include CONTRIBUTORS.md in source and portable packages.

## 0.7.17 — 2026-10-18: optional art coordination and host-generation handoff

- Keep coordination optional and reuse the existing task; remove repeated guide links and inspection steps. Boards omit identical whole/detail panels and unchanged replies omit repeated statistics. Generation adjustments can conditionally omit an already-viewed original while always returning the new draft.
- Share an explicit maintained-document allowlist between source and portable packaging; keep local design drafts outside deliverables without deleting them.

- Keep native drawing and the existing five task routes. Optional direction notes in pixel_task record shared style/light/palette goals and bounded detail areas without painting, adding versions or changing the project format.
- Add read-only pixel_art_board whole/detail/reference evidence with actual source dimensions, stale-plan checks and unchanged-image reuse. No automatic aesthetic approval or replacement for isolated-layer review.
- Add provider-neutral pixel_generation request/preview/apply. The host supplies an actual image generator or external result; no network/model/key/CLI execution is built in. Preview uses the existing automatic pixel draft conversion and apply preserves outgoing work as a separate saved project.
- Bind temporary candidates to source hashes, document/task/reference revisions and expiry; reject changed inputs. Exact apply retries do not duplicate projects; post-apply save failures report their actual state. Existing cutout, layer separation, review, undo and export rules stay intact.
- Keep the desktop on the actual applied candidate after a post-switch reference/save failure; mark unsaved work explicitly, close old document dialogs, and preserve error/retry semantics. Validate real released-MCP/new-backend and new-MCP/released-backend combinations in isolated local tests.
- Decode candidate images from the same bounded immutable bytes that were hashed. Reject wrong-action fields and implicit width/height/colors, retain strict pre-coercion validation, handle long default names and announce animated first-frame input. Invalidate subject-specific reference crops when the generated subject changes.
- Attempt a separate emergency recovery file and provide a structured task-recovery payload after partial I/O failure. Release applied candidate documents from the temporary cache. Add two-client stale-plan, simultaneous-apply and later-edit retry tests without changing the default drawing/conversion route.
- Add isolated unit, fresh MCP-client and desktop-dispatch regressions. Tests validate software behavior, not every AI's artistic quality.

## 0.7.16 — 2026-10-18: scoped reviews and engine-compatible exports

- Keep the current editor's resolved data directory and workspace in generated MCP host configurations, including isolated portable launches. Verify that copying a configuration cannot silently reconnect to the default workspace.
- Use the API's zero-based source frame numbers consistently in review contact, timing, seam and detail evidence; retain one-based frame numbers in the editor timeline.

- Add optional Aseprite JSON hash/array sheet output while preserving native JSON by default. Keep untrimmed source frames, scaled rectangles/source sizes, milliseconds and rebased action tags/directions/repeat.
- Add optional Godot 4 SpriteFrames bundles with portable relative PNG references, action order, variable timing and loop requirements. Reuse scoped passing coverage, layer filtering and draft/overwrite protections in all formats.
- Integrate a conditional format choice into the existing export dialog and CLI/MCP. Expose on-demand MCP export guidance without adding creation presets.
- Explain Godot's default Fix Alpha Border processing and the opt-in engine import setting for exact translucent colors; never change a user's engine project settings automatically.
- Stage multi-file exports together, restore previous outputs on commit failure, and reject stale same-basename Godot resources when switching formats. Verify actual Godot resource loading as well as exchange metadata.

- Add inherited per-tag review settings and scoped evidence fingerprints. Local action edits preserve unaffected action reviews; legacy records retain whole-document matching.
- Combine current passing action reviews with identical layer sets for whole-atlas sheets. Check all named actions, overlaps, unnamed frames and global atlas constraints; expose missing scopes and contributing review IDs.
- Separate full-review timing, applicable seams and playable evidence by action; one-shot evidence/player stops at the end. Keep whole-document review, draft exports and the existing sheet JSON format. Reviewed multi-action GIFs select an action.
- Integrate action/global requirement selection and per-action playback into the existing optional review dialog. Retain up to 256 bounded review records so 128 supported tags are not displaced after 16 submissions.

- Reject unknown MCP arguments and typed settings instead of silently ignoring them. Explain valid quality field names and preserve the document on validation failure.
- Make review settings explicitly merge by default; add replace mode and report effective requirements. Preserve null/list clearing, undo and existing full replies.
- Accept the same verdict words in visual checks and warning resolutions, preserving canonical saved records. Report missing, unknown and duplicate review IDs and missing evidence pages.
- Add optional compact receipts for save/project actions, feedback, review settings/submission and undo/redo. Retain revision guards, questions, inspection images and unresolved review findings; avoid duplicate feedback lists in compact replies.
- Verify both health and actual editor versions before reusing a running editor. Report the running/requested versions with save/close/restart instructions; never close a window automatically.
- Add isolated unit, real two-client MCP, desktop and engine regression coverage for the API, scoped reviews and exchange formats. No finished-art presets are introduced.

## 0.7.15 — 2026-10-17: focused layout and reliable scrolling

- Reorganize the desktop around a compact header, canvas and timeline. Give layers an expanding independent list, move colors and batch tools into separate tabs, and place frame duration controls beside playback. Preserve preview/feedback focus, all native features, scroll support, shortcuts and undo.
- Unify dark surfaces, spacing, compact tool icons, flat tabs, subdued scrollbars and optional Windows dark title bars; remember the selected drawing panel when returning from preview.
- Add an independent layer-list scrollbar and mouse-wheel scrolling. Keep the browsing position during edits and reordering, and reveal a newly selected layer without scrolling the surrounding dock or changing canvas zoom.
- Fix wheel routing over rebuilt palette swatches and nested quality controls. Add overflow scrollbars for long layer names, saved versions, fixed-part lists, command search, storage details and workflow progress.
- Preserve timeline/project-list/progress reading positions across unrelated refreshes; reveal selected frames using real widget geometry, including after window resizing. Avoid rewriting unchanged progress text and losing its selection.
- Add isolated native regression coverage for large palettes, long timelines, long names, older versions and nested scrolling.

## 0.7.14 — 2026-10-17: task workflows and efficient MCP reads

- Add project-strip arrows, an overflow scrollbar and a complete-list button. Wheel scrolling works over child tabs; switching projects or resizing reveals the active tab rather than clipping later projects.

- Consolidate task routing: text/image static creation with clean visible-object layers; local edits, requested completion and requested animation remain distinct. Remove contradictory stop-after-draft and implicit hidden-repair guidance; preserve all native features.
- Add bounded local task notes/part-check evidence with separate revision guards, draft fidelity checks and stale-check detection. Reuse existing review/history/undo; legacy projects require no migration.
- Add opt-in compact replies, conditional state/PNG reads, bounded preview caching and native polygon/holes region_copy. Keep full legacy calls and full native operation validation; fetch exact schemas on demand.
- Add an optional read-only workflow/progress viewer under More, with no persistent sidebar or creation form.
- Add real stdio task/compact/history metadata regression coverage and desktop progress/project-navigation CI checks. Fresh-context AI tests used isolated fixtures and MCP-provided methods; they do not establish equal artistic ability across models.
- Link the method from initialization, onboarding, animation prompts and bundled guides. Instructions remain general and contain no finished-character templates or automatic segmentation model.
- Add read-only `pixel_preview(layers=[...])` for isolated layers or linked groups, including hidden layers, while preserving stack order, opacity, visibility, active cel, history and artwork. Detect older backends that cannot honor layer selection instead of displaying a composite as an isolated part.
- Extend pixel-level service and real stdio MCP regression tests for discovery, read-only isolation and compatibility.

## 0.7.13 — 2026-10-17: optional background removal

- Add one background-removal entry in the reference importer with original/result comparison, background seed clicks, strength adjustment, optional soft edges, protected rectangles, mask view and explicit application.
- Preserve original files/references and painted artwork. Recompute previews from original pixels; support cutout-only undo/redo/reset, transparent source PNG export, portable parameters in saved drafts and regular undo for bound references. Importing/converting alone never applies cutout.
- Add discoverable MCP help, read-only pixel_cutout_preview and guarded pixel_cutout apply/undo/redo/reset/export. base_preview_id retains masks while adjusting parameters; stale or expired previews cannot apply. Guidance covers optional use, image inspection, settings/coordinates, repairs and honest limits.
- Use a local color/connected-mask method, with explicit keep/remove polygons for AI precision. No semantic segmentation model or content presets are bundled; complex scenes/hair/glass may require manual masks. Stored reference resolution remains bounded to1024px and animated inputs use the first frame.
- Add isolated algorithm/history/portability, two-client MCP and Tk control regression tests.
- Block exports while adjusted previews are pending or unapplied; refresh expired cutout previews before the user explicitly applies again.

## 0.7.12 — 2026-10-17: bundled MCP creation and inspection methods

- Guide newly connected clients from initialization and onboarding to task-independent design, native drawing, layer/motion planning, optional host-side computation and real visual inspection.
- Add focused workflow/animation_workflow/inspection_workflow help and the optional pixel-loom://workflow resource. Keep onboarding compact and make all guidance available through standard MCP without extra user files.
- Teach clean moving cels, anchor/area/grid constraints, actual image/timing/seam checks, bounded repairs and honest review/export. No content generator, finished artwork preset, script executor or new desktop panel is added.
- Cover read-only discovery, fresh independent MCP sessions, native animation, residue repair, stale reviews and final export in isolated protocol tests. These tests do not claim every external AI model has equivalent artistic ability.

## 0.7.11 — 2026-10-16: storage cleanup for humans and AI

- Add space usage, immutable cleanup previews and an explicitly requested cleanup MCP tool. Protect active art, latest/pinned versions, unique recovery and external files; reject stale plans and make retries idempotent.
- Add version pinning, selected-history deletion and selected deleted-project purge through one on-demand storage dialog. Keep stable version numbers after deletion.
- Bound project/version/plan metadata with pagination and provide focused human-intent mappings in MCP help and usage documentation. No automatic artwork deletion.

## 0.7.10 — 2026-10-16: general AI tools and project iterations

- Remove the built-in pixel-effect generator, its menu/MCP tool and auto-loaded example artwork. The connected AI creates content using general drawing, layer, frame, preview and export tools.
- Automatically retain editable AI batches and pre-save drafts with labels, source and time. View both animations, step through frames and choose an old version within the same project; preserve every earlier iteration and shared undo.
- Add versions/version_preview/use_version to the existing project MCP interface; guard stale choices and preserve old-project pixels/layers/timing and inert metadata.
- At the owner's request, withdraw previous GitHub release pages/assets and their version tags after this replacement is publicly verified. Source commit history and user artwork remain intact.
- Add persistence, deduplication, two-client MCP and desktop comparison/selection regression coverage.

## 0.7.9 — 2026-10-16: editable pixel VFX

- Add one visual Pixel effects entry with arc slash, lightning, magic aura, fire and explosion/sparks. Color, strength, size, frame count and timing update a background-built preview and optional all-frame overview.
- Generate a new saved independent project while checkpointing current work. Results use ordinary native palette/layer/frame/stamp operations; pixels, layers and frames remain editable and undoable.
- Preserve the original bounded deterministic recipe in projects. Regeneration creates variants and never overwrites manual corrections.
- Add pixel_effect with typed settings, read-only presets/preview and guarded create. Actual all-frame images and draft GIF evidence are returned. No external generation API is required.
- Move advanced character/motion entry to command search to keep the main menu focused.
- Add source/frozen MCP, model/persistence/export and asynchronous GUI regression coverage.


## 0.7.8 — internal preview (included in 0.7.9; not separately released)

- Keep the main canvas unchanged; add one on-demand More → Character and motion window.
- Save an approved pose, palette, baseline, optional fixed regions and four optional view references. Specs are portable in projects and .pixelchar files; importing never repaints existing artwork.
- Add pixel_character and pixel_motion_check MCP tools with focused help and onboarding. Forked actions inherit the character spec. Metadata changes are undoable and canvas resizing transforms it consistently.
- Scan every frame for suspect new tiny islands, fixed-part/color drift, empty frames and abrupt transitions. Return exact frames/ROIs and immutable paged before/current/after images.
- Offer exact-pixel cleanup only for an explicitly selected unlocked tiny island, in one undo step. Changed artwork invalidates old reports and cleanup. No automatic artistic pass or bulk erasure.
- Include approved character images and consistency criterion in final visual review. Add unit, real two-client MCP and asynchronous Tk workflow tests.


## 0.7.7 — release checks and download reminders

- Add More → Check for updates and a searchable command. Version checks run in a background thread so editing and MCP remain responsive.
- Check public GitHub releases after desktop startup, at most once per 24 hours after a successful check. A new version produces a nonblocking banner with release notes and a Windows ZIP download button.
- Support stable and public preview channels, including the existing 0.x preview releases. Compare semantic versions numerically and ignore drafts or invalid tags.
- Keep startup/channel preferences in the user's data directory. Allow startup checks to be disabled; headless MCP and diagnostics do not check the network automatically.
- Handle offline requests, rate limits, malformed responses and missing packages without blocking application use. Browser links are restricted to this project's HTTPS release/download paths and open only on explicit clicks.
- Request public version metadata only; never upload artwork, references, saved paths or client settings. Downloading and installing remain explicit user actions.
- Test notification, cache, preferences, slow requests, link opening and shutdown in an isolated GUI runtime; exclude test data and local usage records from release bundles.

## 0.7.6 — reliable editing and a roomier workspace

- Frame, layer and selection navigation preserves drawing undo/redo and avoids serializing the entire document. Refresh only affected timeline thumbnails.
- Erase to transparent pixels independently of palette order. Paste full-color PNG selections without filling a disabled palette; expose the palette constraint in the desktop.
- Honor the human's cancel/save/discard choice when generating a pixel draft.
- Fit large canvases below 100% and add 12.5%, 25%, 50% and 75% nearest-neighbor zoom.
- Pause on the displayed frame, resume there, and provide a separate Stop button returning to the action start.
- Compact the top controls, hide an empty project shelf, and provide resizable sidebar/timeline panes with local layout preferences.
- Warn when an export snapshot becomes old and offer an explicit refresh. Disable invalid exports and provide actionable Chinese desktop error messages.
- Add regression coverage for editing, view transactions, layout, playback and exported snapshot fidelity. Preserve the startup guide and optional creator support.

## 0.7.5 — startup guide and optional creator support

- Show a compact usage guide when the desktop window starts; enter directly, or view voluntary creator support.
- Offer 5, 10, 15 and 20 yuan choices with the author's corresponding original WeChat receipt images.
- Enter, Escape and closing the guide all allow normal use. No payment state, network request or feature gate is introduced.
- Reopen the guide through More. Headless MCP remains unchanged, and the desktop bridge stays responsive while the guide is open.
- Declare the Windows launcher dependency for clean source installations.

## 0.7.4 — optional imported style references

- Identify style images as imported workspace images or embedded project references. Ship no built-in style image.
- Add import/replace, view and clear actions together beside the style name. Clearing keeps original artwork intact and remains undoable in a bound project.
- A different ordinary source clears the previous style without changing the previous project's references. Reloading the same source preserves its chosen style.
- Explain that style images do not affect automatic draft sampling or authorize artistic redraw; expose source information to MCP clients.

## 0.7.3 — automatic draft by default

- Image conversion creates one editable sampling layer by default, preserving the exact automatic draft.
- Artistic redraw is an explicit mode. Align GUI labels, copied instructions, MCP onboarding, prompts and documentation with the human's requested scope.

## 0.7.2 — preview playback speed

- Add 0.25×–4× speed selection beside Play, including changes during playback. Preview speed does not modify frame durations, history or exported timing.

## 0.7.1 — project management

- Add an on-demand project manager for importing existing files without switching the current artwork, opening, selecting multiple projects, reversible removal and restoration.
- Add project-tab context menus and a clear Manage projects entry. Removed projects keep their original files, history, identities and numbers under Deleted.
- Removing the active project saves outgoing changes before selecting a remaining project; removing all leaves an empty workspace that stays empty after restart. New work does not create an extra placeholder project.
- Extend `pixel_projects` with remove/deleted/undelete. Keep removal reversible and require the human's intent before an AI removes any project.
- Cancel desktop timers on close so restarting the editor does not leave callbacks attached to destroyed widgets.

## 0.7.0 — retained projects and animation comparison

- Persistent numbered project shelf with independent file paths, identities and parent links. Fork/new/switch checkpoint the outgoing project, including unnamed and unsaved work.
- Pre-save version backups, external-file-change protection, and restore into a separate project without replacing the source.
- Read-only two-project desktop comparison with independent frame timing, simultaneous playback, time scrubbing and shared pixel magnification.
- New `pixel_projects` MCP tool exposes list/register/fork/new/switch/versions/restore/compare; comparison evidence is paged across every animation frame. Onboarding instructs agents to fork before making a different action or variant.
- Preserve previous drawing, animation, reference, screenshot, review, save and export workflows. Existing explicit unsaved-replacement guards remain available.

## 0.6.2 — contextual workspace

- Preview hides both sidebars and gives the canvas the full workspace width. Manual editing reveals the drawing rail, navigator, layers, palette and automation tools.
- Replace the permanent creation/feedback tab with a compact screenshot toolbar shown only in screenshot mode. Remove the AI connection tab; keep first-time MCP setup, collaboration history, legacy reports and screenshot guidance in More.
- The local service continues to start automatically. MCP initialization and onboarding explain direct tool use and screenshot feedback without asking users to open or enable an AI panel.
- Preserve screenshot clipboard formats, all native drawing/animation operations, legacy project reports, shared history, save and export.

## 0.6.1 — screenshot-first feedback

- Replace the default problem form with one-click canvas screenshot and image copy, followed by a clear reminder to paste into the AI conversation.
- Keep optional lasso/rectangle/ellipse marks; captures include full canvas, marked detail, visible problem designation and document/frame/ROI identity.
- Embed a versioned `pixel_loom_feedback` PNG property, with visible fallback information when chat clients discard metadata. Windows clipboard publishes PNG and CF_DIB formats.
- Bundle a single AI screenshot convention guide and expose it through `pixel_help(topic="feedback_images")`. A capture is not a queued ticket; ambiguous changes are clarified in the user's conversation.
- Preserve existing reports under an advanced history view. Capturing does not edit pixels, add reports, or change painting history.

## 0.6.0 — simpler workspace and annotated feedback

- Three clear entry points: preview the result, circle a problem, or edit by hand. Common tools stay visible; advanced tools and acceptance settings remain available on demand.
- Non-destructive lasso, rectangle and ellipse problem marks with affected frames, original pixel snapshots and portable conversations.
- New `pixel_feedback` MCP tool provides precise masks, original/current frame images, explicit clarification questions, real user answers and evidence-bound resolution. Local submission does not silently start an external AI client.
- Drawing undo preserves user reports and replies. Revisions, changed pixels, removed frames and changed canvas bounds prevent stale repairs from being treated as current.
- Unresolved feedback blocks AI-certified delivery. Human editors can still save and directly export their current version without claiming AI acceptance.
- A user can close an obsolete issue with a reason; its original evidence and conversation remain in the project.
- Integration coverage exercises the real shared Tk/MCP workflow, not a mock interface. No third-party editor code, icons or trial binaries are included.

## 0.5.0 — evidence-based AI self-review

- Acceptance requirements, rendered frame/timing/seam/detail/reference evidence, playable GIF/APNG previews and an in-editor review player.
- Program checks for size, frame count, colors, transparency and planted regions; targeted warnings for rigid cut-outs, timing disparity and loop jumps.
- Three MCP review tools and a finish-and-review prompt enforce concrete visual findings, repair/recheck loops and honest uncertainty.
- Final exports require a current passing review for the selected content/frames/layers. Explicit draft exports remain available and labeled.
- Portable review records expire when artwork or requirements change; verdicts never become artistic passes merely because numeric checks succeed.

## 0.4.0 — reference redraw

- Import ordinary source and optional style images, with a three-way comparison workspace and drag-to-crop controls.
- Configure target size/colors, fit, brightness, contrast, saturation, alpha threshold and an artistic brief. Automatic drafts are explicitly distinguished from AI redraws.
- Three MCP tools expose reference images/settings, dry-run comparisons and protected layered project creation; a redraw prompt and onboarding guide tell agents how to continue.
- Embed normalized source/style PNGs in portable .pixloom projects. Bound reference edits share native undo history; display overlays do not change artwork/export pixels.
- Test reference conflicts, source preservation, transparent export, project portability and real two-client MCP redraws.

## 0.3.0 — visual workspace

- Redesigned native desktop with vector tool icons, contextual hints, an inspector/automation/AI dock and compact thumbnail timeline.
- Exact raster symmetry, visible axes, live polygon/curve previews and cached palette/thumbnail widgets.
- Five parameter-driven workflows with read-only contact/timed previews, document/revision guards and atomic undo.
- New-project size presets, canvas resize previews, export size/layout feedback, paginated frame overview and searchable command palette.
- Fixed manual stroke/path coordinates rejected by strict schema validation; preview/commit pixel equality is covered by the GUI smoke test.
- Added workflow tests for source preservation, independent cels, selection bounds, timing, locks, capacity rollback and even-width symmetry.

## 0.2.0 — public preview

- 41 validated native operations, including polygons, Bézier curves, local transforms, canvas resize/scale, layer duplication/merging and animation tags.
- Rectangular selection, copy/cut/paste, local rotation, interactive polygon/curve tools and tag playback in the desktop editor.
- 12 MCP tools with typed operation schemas, onboarding, dry-run image previews, animation contact sheets and structured recovery errors.
- Three MCP resources and two task prompts; a distributable agent skill and executable native-drawing recipes.
- Per-user runtime/workspace paths, installable package/entry points and generated client configuration.
- Duplicate-request protection, unsaved artwork protection, export collision checks and content-based dirty tracking.
- Isolated tests, source/wheel release preparation and a Windows portable-build specification.

## 0.1.0 — local prototype

Layered integer-pixel editing, basic animation, local MCP bridge and PNG/sheet/GIF export.
