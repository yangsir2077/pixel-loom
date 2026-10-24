# 动画制作 / Animation workflow

Read pixel_help(topic="workflow") first. Design motion for the current brief; this guide contains no object preset or finished artwork coordinates.

## Before animation from a flattened image

Animation needs the human's request. Choose animation from compact onboarding and preserve a different action in a fork. Read decomposition_workflow for merged source images. Analyze structure, occlusion, joints and grips; separate visible objects, inspect each isolated part and restored composite first. Hidden completion is a separate requested scope: if movement needs missing surfaces, clarify before painting them. Static conversion also needs clean visible-object layers, but no animation trial or hidden filling. Matching rest pixels does not certify correct ownership. pixel_task records brief, parts and next_action without art/history changes; frame-0 part checks complement the full-frame review below.

## 1. Define the motion contract

Specify the checked static identity baseline, fixed parts, anchors, moving parts, extent, frame durations and whether motion loops or plays once. Keep the baseline/source and earlier versions available for comparison or rollback. Keep static geometry/highlights/labels fixed unless the intended material calls for movement. Do not move an entire object layer when only one internal part should change. Preserve identifying details; do not freely regenerate the whole subject to obtain a local action.

Choose frame count, key-pose count and durations for the requested action and source detail, honoring any explicit human values within tool limits. More frames alone do not fix bad poses or timing. Use spacing, duration, acceleration/deceleration, holds and secondary lag where appropriate; uniform speed is only suitable when the motion calls for it.

Keep independent actions in named tags. Use pixel_review_settings(tag=..., settings=...) for each action's source frame count, loop/one-shot and fixed-part requirements, then pixel_review(tag=...). Global expected_frames describes the complete atlas, not every action. Current passing action reviews with identical layer sets combine for whole-sheet export; no idle-to-run loop is invented. After a local action edit recheck only stale scopes listed by REVIEW_REQUIRED. Read inspection_workflow for inherited requirements and export coverage.

For procedurally sampled cyclic motion, phase = 2*pi*frame/frame_count is one optional construction. Inspect the actual last-to-first transition; the last image need not duplicate the first or add an unintended hold. For a one-shot action, check entry/exit against another action only when that transition was requested; never invent an idle-to-run loop across separate atlas tags.

## 2. Key poses before transitions

Draw and inspect a convincing static design first. Select the important poses/contact/extreme states for THIS action, with their anchors, grip positions and occlusion order. Trial their assembly before producing all transitions. A rigid limb uses stable segment lengths and joint arcs; a flexible part may use changing curves with a fixed root. C/S curves are optional shape aids for flexible parts, not a universal rule for rigid limbs or mechanisms.

Build transitions between the checked poses while preserving the baseline's identity. Centerlines/trajectory samples can aid positioning; equal spatial slices do not solve articulation, perspective or overlap. Reuse unchanged pixels from the reliable static/key-pose layers where they belong. If a part inherits parent motion, align its local coordinates rather than pasting rest-position pixels over a moving joint. Check coupling and attachment continuity as well as silhouette.

If the human chooses externally generated pose references, the host must actually provide and inspect those images. pixel_generation handles static-source handoff/conversion, not animation interpolation. Reuse only justified changing regions through supported operations, not a whole generated frame with unrelated identity changes; compare masks and assembled seams against the baseline. Native drawing remains available without another image model.

## 3. Separate static and moving cels

Construct each target cel from a reliable baseline/key pose rather than repeatedly warping the preceding in-between. Use either clean-frame strategy:
- Before drawing frame-0 motion, copy the static composition and empty moving layers to all frames, then paint each moving cel explicitly.
- If the source already contains motion, copy it, clear ONLY the moving layer in each target frame and redraw that frame. Never clear static layers by accident.
frame_add(blank=true) creates blank cels for all layers; it does not preserve a static background. Use copy_from for static content, then clear the appropriate moving cels. Query the current operation schemas.

Do not accumulate new silhouettes over old ones. For a local repair, clear/rebuild the affected moving cel or an explicit bounded clip. Keep unrelated layers, anchors, palette and frames intact. Use tags for the intended action range.

## 4. Calculate useful constraints, not a full-image shortcut

Host-side code can compute per-frame geometry and output native rect/polygon/line/pixel operations. Merge adjacent same-color pixels into runs where helpful instead of making a network call per pixel.

Possible task-dependent constraints:
- A liquid interior can use a periodic tilted/wavy surface inside a bottle mask. Choose a target filled-pixel count from THAT design, rank interior pixels by depth below the proposed surface, and select the same count each frame. This preserves 2D pixel area, not a full 3D fluid simulation.
- A flexible part can keep its attachment fixed while its tip lags. Rebuild its contour; simple whole-patch translation can detach it.
- A tiled surface needs a specified grid, neighbor rules, edge continuity and consistent frame placement. Validate it in the target engine when the task asks for engine-ready tiles.
- Particles may intentionally be disconnected. Their origin, path, fade and lifetime should be designed rather than treated as accidental orphan pixels.

These are design principles, not an invitation to add built-in content presets or copy a finished example. Choose new geometry, colors, constraints and timing from the human's task.

## 5. Inspect complete motion evidence

Use pixel_contact_sheet for EVERY frame, paging/chunking long ranges. Inspect native size, integer zoom and named local regions. Check anchor contact, silhouette/volume consistency, material highlights, color drift, clipping, ghost pixels and trajectory continuity.

Check moving/static mask boundaries and coupled joints across neighboring frames. Repair the smallest sufficient affected region while retaining original shading/detail; there is no fixed pixel quota. A clean seam and a convincing action both matter: do not freeze the intended motion merely to obtain matching outlines.

Use pixel_motion_check and read every returned page. It reports suspicions, not a natural-motion verdict. View before/current/after crops; only apply selected repairs justified by actual images. Do not bulk-erase particles or decorations.

Examine actual durations, a two-loop timing sheet and last/first frames for loops. Short key poses can be missed by elapsed-time sampling, so also inspect the complete frame list. The desktop preview playback rate does not change export timing. GIF uses 10ms timing units; choose compatible durations or report rounding.

Continue with pixel_help(topic="inspection_workflow"), repair observed defects, obtain fresh evidence and save the editable project after submitting the review.
