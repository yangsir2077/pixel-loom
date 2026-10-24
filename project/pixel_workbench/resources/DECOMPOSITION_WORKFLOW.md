# 单图分析与干净拆层 / Visible-object decomposition

Use for flattened images during creation/conversion, or preparation for an explicitly requested pose/animation. A flat picture has visible pixels, not complete hidden parts. This guide is general; no semantic model or finished-art preset is provided.

Conversion-only means faithful static draft PLUS editable visible-object layers, not redesign. Hidden completion is separate and requires a real human request. Animation alone does not silently grant it. Opening old projects or importing references alone starts no editing. Preserve source and earlier work.

## Inspect before masks
View source native size and integer zoom. Record a brief analysis: viewpoint/proportions/detail density; actual objects/materials; front-to-back occlusion; contact/joint/grip locations; truly missing hidden areas. Infer ownership from visible structure, not matching colors, rectangles or layer names. Preserve existing pixel dimensions and texture/fingers/folds/outlines. Do not replace a detailed part with a simpler flat shape.

Keep untouched source hidden/locked. Create semantic layers around actual objects and independent editing responsibilities. Use observed stable IDs. A mask may contain the wrong foreground fragment even if its outline looks plausible. More layers or matching rest composite DOES NOT prove clean extraction.

For requested pose/motion, identify coupled parts too: a hand and its held object share a grip; a sleeve follows its arm; attached flexible parts retain their root. Record the useful anchors/overlap order in the existing task notes. Splitting layers does not itself establish these relationships or fill occluded surfaces.

Native region_copy polygon and holes preserve original RGBA. Coordinates are absolute SOURCE positions; query exact schema. Exclude occluder fragments from the rear part. Keep actual background in its own layer unless removal requested. Preserve all visible source pixels and avoid overlaps that duplicate semi-transparent pixels.

## Two complementary checks
A. pixel_preview(frame=..., layers=[observed_layer_id], scale=...) views each complete isolated part without changing visibility/active cel/history, including hidden layers. Check semantic purity, visible contour, stray pixels, mixed foreground/background bands and unintended cuts. Small ROI is useful afterward, not sufficient for certifying the entire layer.
B. Restore composite and compare source/draft at matched logical dimensions/zoom. For image_static, exact palette/pixel/size equality must hold. This invariant complements, not replaces, independent ownership inspection.

Record specific observed findings in pixel_task parts: extraction=pending/clean/needs_repair and hidden=not_requested/not_needed/unfilled/complete/needs_repair. Clean visible extraction may still be hidden=unfilled. Do not call that failed completion or paint unseen areas automatically. A complete mark requires requested completion_scope and fresh complete isolated preview. Changed pixels invalidate checks.

## Conditional next steps
If hidden completion was requested, read completion_workflow. Match actual material palette, light/shadow transitions and detail density; never copy the occluder's color band into the rear object.
If animation was requested, read animation_workflow. Trial the connections with pixel_validate or preserved iterations before full frame production. Inspect grip/contact/gaps at extreme poses. If missing surfaces block motion, clarify the needed completion; do not hide a bad split under many frame patches.

A static extraction task ends after isolated/composite inspection and the existing review/save/export flow; no trial movement or completion is required. Rigid translation/rotation can suit connected pieces; cloth needs attachment-aware contours. Quarter-turn operations are not arbitrary small-angle rotations. Optional host calculations may produce native coordinates honestly, without importing finished animations and claiming native drawing.

Follow inspection_workflow for requested scope. Report actual findings, unresolved uncertainty and paths. Numeric equality, successful export or AI status does not certify beauty/anatomy.
