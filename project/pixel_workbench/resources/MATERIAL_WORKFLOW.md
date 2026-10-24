# 按需法线与光照 / Optional material preview

Use only for the human's requested normal/material/lighting work. Ordinary image conversion still follows image_workflow; do not create normal maps, redraw materials or animate merely because this tool exists. This feature is a lightweight local 2D preview, not an automatic 3D reconstruction or a game engine. Importing/previewing does not paint or change the source palette. No model API, network or Godot installation is needed for the app preview.

## Inspect and choose a source

Call pixel_material(action='status') and inspect the original artwork. Use the actual document/revision tokens for every action except status. Normal maps describe surface directions: X+, green=up, Z+. Emission is light produced by a part, not a normal direction. Transparent glass still needs appropriate alpha and sparse reflections; painted highlights already in the color image are not removed by relighting.

Choose normal_source.kind explicitly when needed:
- current (or omit normal_source): continue saved material; if none, preview a flat surface without storing anything. Optional frames=1 shares the previewed frame's map; frames=document count expands a shared map for independent editing.
- import: path to an exact-size PNG; optional frames and columns import an aligned PNG sheet. Count is one shared map or the actual document frame count. No silent resizing.
- flat: start an editable forward-facing map.
- silhouette: estimate a bevel from selected layers' alpha, with bevel/strength controls. Generates aligned maps for all current frames. It estimates only a silhouette bevel, not internal anatomy or material structure.
- height: import an explicit, user-chosen height PNG/sheet and derive slopes. Never treat an ordinary painted color image's brightness as a trustworthy height map by default.

Imported masks and map colors are technical data independent of the artwork palette. specular_path imports a matching highlight mask; an empty string clears that mask. Hidden-source completion, source redesign and background removal keep their existing human-requested scopes.

## Preview, adjust, edit

pixel_material(action='preview', normal_source=..., settings=..., observed tokens) returns preview_id, current tokens, image_key and image_roles. settings are merged with saved settings, or with the specified source_preview_id draft. Continue pending imports/brush changes by passing source_preview_id; omitting it starts from saved material. Nothing is applied until apply. Apply/export previews expire after 15 minutes; retained maps may be re-previewed to obtain a fresh ticket. Other cached previews may be evicted; the current open GUI draft is protected. Previews are not permanent artwork history.

view='comparison' shows the same light with a flat surface and with actual normals. view='source' compares original color and relighting. view='normal' shows normal data plus effect; view='render' shows the effect alone. Coordinates light_x/light_y are normalized canvas positions; light_height and light_radius are relative to the larger canvas dimension. Adjust intensity, ambient, light_color, normal_strength, flip_y, specular, shininess and emission_strength. emission_layers names observed layer ids and keeps those layers unlit in their original compositing order. Preview backgrounds are display-only; export background is explicitly separate.

Large canvases can use preview_limit to reduce interactive shading work. The reply reports logical_size, preview_size and preview_limited. Turn off limited preview for exact pixel checks. Normal-data/brush views and all exports stay at the native grid; a quick preview never resizes saved maps or color cels. Runtime needs depend on canvas/layer count; do not promise every project a fixed frame rate.

normal_edits supports stroke (points, size, normal vector), rect (rect, normal) and erase (rect to a flat vector), with an explicit frame when useful. A shared map edits all animation frames; per-frame maps edit the named frame. Normal vectors are normalized; zero vectors, invalid coordinates and unknown fields fail without changes. Do not guess a part's geometry from its layer name. Use the normal-data image and actual lighting result to correct the map.

Reuse if_image_key only for evidence this client already viewed. Inspect new images after changes. A stable preview appearance is not proof of artistic quality. Moving characters/parts need aligned per-frame maps; a shared non-flat map may slide over moving art. Check all relevant frames, contacts, opacity and emission order. Canvas/frame changes can invalidate maps; import matching data or explicitly regenerate. Source edits produce an alignment warning; inspect again before applying a new binding. rebase=True may re-preview a retained draft on newer art in the SAME document; it does not bypass identity or apply/export revision guards. The GUI protects pending drafts from project replacement. Applied maps/settings share undo/history; a storage_warning means the material is applied in memory but still needs saving, not rolled back.

## Apply, undo and export

apply(preview_id, observed tokens) stores the viewed maps/settings as one shared, undoable material_context change. Color cels, palette and active selections stay intact. pixel_history undo/redo handles committed changes; preview drafts do not add paint history. clear removes optional material only. Save .pixloom to retain normal/specular frames and settings; old projects remain usable without material. Older applications may ignore new optional metadata, so retain a saved version before opening a material project in older software.

export requires a still-current preview_id: kind='normal' exports a PNG with effective strength/Y convention applied; render exports a rendered PNG; sheet exports a ZIP with rendered PNG atlas and frames.json; bundle exports color/normal/specular/emission atlases, frame timing and a relative Godot CanvasTexture. all_frames selects source timeline order; default exports the exact frame that was previewed. Original pixel_export formats/review gates are unchanged. Material exports are explicitly marked material_preview: a color-only passing review does not certify lighting. Inspect actual outputs before presenting a result as finished.

For Godot, keep the map bundle together and assign material.tres to a Sprite2D with Light2D. Set matching frame rows/columns for atlases. The emission map preserves visible upper-layer occlusion and has emission_strength baked in; connect emission/glow separately in the engine. The color atlas still includes original emission, so avoid counting it twice. Source color also retains painted shading; these exports are not automatically clean physical albedo/PBR materials. Report estimated geometry and any untested engine behavior honestly.
