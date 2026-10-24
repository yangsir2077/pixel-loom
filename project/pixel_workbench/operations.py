"""Single source for operation validation, MCP argument types and discoverable help."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from typing import Annotated, Literal, Union, Any

from jsonschema import Draft202012Validator
from pydantic import ConfigDict, Field, StrictBool, StrictInt, StrictStr
from typing_extensions import Required, TypedDict


def number(low=None, high=None, description=None):
    result = {"type": "integer"}
    if low is not None:
        result["minimum"] = low
    if high is not None:
        result["maximum"] = high
    if description:
        result["description"] = description
    return result


def string(description="", max_length=120):
    return {"type": "string", "minLength": 1, "maxLength": max_length, "description": description}


def array(items, low=0, high=1024):
    return {"type": "array", "items": items, "minItems": low, "maxItems": high}


BOOL = {"type": "boolean"}
COORD = number(-4096, 4096)
FRAME = number(0, 255)
POINT = array(COORD, 2, 2)
RECT = array(number(0, 512), 4, 4)
COLOR = {"anyOf": [number(0, 255), {"type": "string", "pattern": "^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$"},
                     array(number(0, 255), 3, 4)],
         "description": "Palette index, #RRGGBB/#RRGGBBAA, or [r,g,b,a]. Alpha 0 is transparent."}
CLIP = {"anyOf": [string("Named region"), RECT]}
TARGET = {"layer": string("Stable layer id or unique layer name; defaults to active layer."),
          "frame": FRAME, "clip": CLIP}
SPECS = {}


def op(name, category, description, required=(), props=None, example=None, drawing=False):
    properties = {"op": {"const": name, "type": "string"}}
    if drawing:
        properties.update(deepcopy(TARGET))
    properties.update(props or {})
    SPECS[name] = {"category": category, "description": description,
                   "schema": {"type": "object", "additionalProperties": False,
                              "properties": properties, "required": ["op", *required]},
                   "example": example or {"op": name}}


op("pixel", "drawing", "Set one exact RGBA pixel.", ("x", "y"),
   {"x": COORD, "y": COORD, "color": COLOR}, {"op": "pixel", "x": 4, "y": 4, "color": 22}, True)
op("stroke", "drawing", "Connected integer-pixel pencil stroke; no antialiasing.", ("points",),
   {"points": array(POINT, 1, 100000), "color": COLOR, "size": number(1, 32)},
   {"op": "stroke", "points": [[1, 1], [4, 3], [8, 3]], "color": 22}, True)
op("line", "drawing", "Draw a line between two points.", ("x1", "y1", "x2", "y2"),
   {key: COORD for key in ("x1", "y1", "x2", "y2")} | {"color": COLOR, "size": number(1, 32)},
   {"op": "line", "x1": 1, "y1": 1, "x2": 8, "y2": 5, "color": 22}, True)
for kind in ("rect", "ellipse"):
    op(kind, "drawing", "Integer-pixel shape; width and height are sizes, not end coordinates.", ("x", "y", "width", "height"),
       {"x": COORD, "y": COORD, "width": number(1, 4096), "height": number(1, 4096),
        "color": COLOR, "filled": BOOL, "size": number(1, 32)},
       {"op": kind, "x": 4, "y": 4, "width": 12, "height": 8, "color": 18, "filled": True}, True)
op("polygon", "drawing", "Native filled or outlined polygon; useful for organic silhouettes and individual teeth.", ("points",),
   {"points": array(POINT, 3, 1024), "color": COLOR, "filled": BOOL, "size": number(1, 32)},
   {"op": "polygon", "points": [[4, 12], [8, 3], [16, 10], [12, 15]], "color": 18}, True)
op("bezier", "drawing", "Native quadratic (3 points) or cubic (4 points) pixel curve.", ("points",),
   {"points": array(POINT, 3, 4), "color": COLOR, "size": number(1, 32)},
   {"op": "bezier", "points": [[2, 16], [2, 2], [14, 2], [14, 16]], "color": 22}, True)
op("fill", "drawing", "Flood-fill connected equal-color pixels, constrained to clip when supplied.", ("x", "y"),
   {"x": COORD, "y": COORD, "color": COLOR}, {"op": "fill", "x": 8, "y": 8, "color": 18}, True)
op("clear", "drawing", "Erase a cel, or just a named/rectangular clip.", (), {}, {"op": "clear", "clip": [4, 4, 8, 8]}, True)
op("replace", "drawing", "Replace an exact color in the target cel/clip.", ("old_color",),
   {"old_color": COLOR, "color": COLOR}, {"op": "replace", "old_color": 22, "color": 18}, True)
op("translate", "transform", "Move the whole cel by integer offsets; pixels outside the canvas are clipped.", ("dx", "dy"),
   {"dx": COORD, "dy": COORD}, {"op": "translate", "dx": 1, "dy": -1}, True)
op("flip", "transform", "Mirror the whole cel across its canvas.", (),
   {"axis": {"enum": ["horizontal", "vertical"]}}, {"op": "flip", "axis": "horizontal"}, True)
op("outline", "drawing", "Add a one-pixel outside outline to opaque pixels.", (),
   {"color": COLOR, "diagonal": BOOL}, {"op": "outline", "color": 1}, True)
op("dither", "drawing", "Fill a rectangle with a two-color checker pattern.", ("other_color",),
   {"rect": RECT, "color": COLOR, "other_color": COLOR},
   {"op": "dither", "rect": [2, 2, 8, 8], "color": 18, "other_color": 17}, True)
STAMP_FIELDS = {"name": string("Previously defined stamp name"), "rows": array(string("Pixel symbols; '.' skips a pixel", 512), 1, 512),
                "colors": {"type": "object", "additionalProperties": COLOR}, "x": COORD, "y": COORD, "scale": number(1, 16)}
op("stamp", "drawing", "Paste an ASCII pixel pattern: supply name OR rows+colors. '.' means leave existing pixels unchanged.", (),
   STAMP_FIELDS, {"op": "stamp", "x": 6, "y": 6, "rows": [".a.", "aaa", ".a."], "colors": {"a": 22}}, True)
op("stamp_define", "library", "Name a reusable ASCII pixel pattern.", ("name", "rows", "colors"),
   {k: STAMP_FIELDS[k] for k in ("name", "rows", "colors")},
   {"op": "stamp_define", "name": "spark", "rows": [".a.", "aaa", ".a."], "colors": {"a": 22}})
op("region_define", "selection", "Name a rectangular semantic body part; all drawing clips can reference it.", ("name", "rect"),
   {"name": string(), "rect": RECT}, {"op": "region_define", "name": "eyes", "rect": [8, 8, 12, 6]})
op("region_delete", "selection", "Delete a semantic region definition; artwork is unchanged.", ("name",),
   {"name": string()}, {"op": "region_delete", "name": "eyes"})
op("selection_set", "selection", "Set a rectangular selection; omit rect to clear it. Selection is view state.", (),
   {"rect": RECT}, {"op": "selection_set", "rect": [4, 4, 12, 12]})
op("region_transform", "transform", "Move, flip or rotate only a region/selection. Destination is top-left anchored; clipping is explicit.", ("kind",),
   {"rect": CLIP, "kind": {"enum": ["translate", "flip_horizontal", "flip_vertical", "rotate_cw", "rotate_ccw"]},
    "dx": COORD, "dy": COORD, "copy": BOOL, "update_region": BOOL, "layer": TARGET["layer"], "frame": FRAME},
   {"op": "region_transform", "rect": "eyes", "kind": "translate", "dx": 1, "dy": 0})
op("region_copy", "transform", "Copy source pixels without changing the source. Optional polygon/holes use absolute SOURCE coordinates for clean object extraction; no hidden pixels are invented.", ("rect", "x", "y"),
   {"rect": CLIP, "x": COORD, "y": COORD, "source_layer": TARGET["layer"], "source_frame": FRAME,
    "layer": TARGET["layer"], "frame": FRAME, "blend": {"enum": ["replace", "over"]},
    "polygon": array(POINT,3,1024), "holes": array(array(POINT,3,1024),0,32)},
   {"op": "region_copy", "rect": [4, 4, 8, 8], "x": 16, "y": 4})
op("canvas_resize", "canvas", "Change canvas bounds by padding/cropping; pixels are not scaled. Undo restores cropped pixels.", ("width", "height"),
   {"width": number(1, 512), "height": number(1, 512), "anchor": {"enum": ["top_left", "center", "bottom_center"]}},
   {"op": "canvas_resize", "width": 64, "height": 64, "anchor": "center"})
op("sprite_scale", "canvas", "Scale every cel using nearest-neighbor sampling, preserving crisp pixel edges.", ("width", "height"),
   {"width": number(1, 512), "height": number(1, 512)}, {"op": "sprite_scale", "width": 64, "height": 64})
op("layer_add", "layers", "Add an empty layer above existing layers; names and ids must be unique.", (),
   {"name": string(), "id": string()}, {"op": "layer_add", "name": "eyes", "id": "eyes"})
op("layer_set", "layers", "Rename a layer or set visibility, lock and 0–255 opacity.", (),
   {"layer": TARGET["layer"], "name": string(), "visible": BOOL, "locked": BOOL, "opacity": number(0, 255)},
   {"op": "layer_set", "layer": "eyes", "locked": True})
op("layer_move", "layers", "Move a layer to a bottom-to-top stack index.", ("index",),
   {"layer": TARGET["layer"], "index": number(0, 63)}, {"op": "layer_move", "index": 0})
op("layer_delete", "layers", "Delete an unlocked layer; the last layer cannot be deleted.", (),
   {"layer": TARGET["layer"]}, {"op": "layer_delete", "layer": "eyes"})
op("layer_duplicate", "layers", "Duplicate all cels of a layer with an independent id and pixel buffers.", (),
   {"layer": TARGET["layer"], "name": string(), "id": string()}, {"op": "layer_duplicate", "name": "eyes-copy"})
op("layer_merge_down", "layers", "Merge current layer into its visible, unlocked neighbor below, baking their opacities.", (),
   {"layer": TARGET["layer"]}, {"op": "layer_merge_down"})
op("frame_add", "animation", "Insert one copied or blank frame after a frame; layer cels stay aligned.", (),
   {"after": FRAME, "copy_from": FRAME, "blank": BOOL, "duration_ms": number(16, 60000)},
   {"op": "frame_add", "after": 0, "copy_from": 0, "duration_ms": 120})
op("frame_set", "animation", "Set a frame's duration in milliseconds.", ("duration_ms",),
   {"frame": FRAME, "duration_ms": number(16, 60000)}, {"op": "frame_set", "frame": 0, "duration_ms": 120})
op("frame_delete", "animation", "Delete one frame; keep at least one frame. Tags shrink or disappear as needed.", (),
   {"frame": FRAME}, {"op": "frame_delete", "frame": 1})
op("frame_move", "animation", "Move a frame with all its cels and timing. Tags describe timeline positions.", ("frame", "index"),
   {"frame": FRAME, "index": FRAME}, {"op": "frame_move", "frame": 2, "index": 1})
op("frame_duplicate_range", "animation", "Duplicate an inclusive frame range after a frame; all layers are copied.", ("start", "end", "after"),
   {"start": FRAME, "end": FRAME, "after": FRAME}, {"op": "frame_duplicate_range", "start": 0, "end": 3, "after": 3})
op("tag_set", "animation", "Define an inclusive named animation range such as idle, walk or attack.", ("name", "start", "end"),
   {"name": string(), "start": FRAME, "end": FRAME, "direction": {"enum": ["forward", "reverse", "pingpong"]}},
   {"op": "tag_set", "name": "idle", "start": 0, "end": 3, "direction": "pingpong"})
op("tag_delete", "animation", "Delete an animation tag; frames are unchanged.", ("name",),
   {"name": string()}, {"op": "tag_delete", "name": "idle"})
op("select", "selection", "Change the active cel; it is safer to also supply explicit targets on drawing commands.", (),
   {"layer": TARGET["layer"], "frame": FRAME}, {"op": "select", "layer": "eyes", "frame": 0})
op("palette_add", "palette", "Append unique RGBA colors to the palette, up to 256 entries.", ("colors",),
   {"colors": array(COLOR, 1, 256)}, {"op": "palette_add", "colors": ["#75c3c9ff"]})
op("palette_set", "palette", "Replace the palette, optionally mapping artwork to its nearest entries. Transparency stays transparent.", ("colors",),
   {"colors": array(COLOR, 1, 256), "remap": BOOL},
   {"op": "palette_set", "colors": ["#00000000", "#080f13ff", "#75c3c9ff"], "remap": True})
op("palette_lock", "palette", "Enable or disable palette-only drawing.", ("enabled",),
   {"enabled": BOOL}, {"op": "palette_lock", "enabled": True})
op("rename", "canvas", "Rename the document.", ("name",), {"name": string()}, {"op": "rename", "name": "forest-creature"})
op("reference_context", "reference", "Set portable reference context as one undoable metadata edit. Prefer pixel_reference_setup for local file import and typed settings.",
   ("data",), {"data": {"type": "object"}}, {"op": "reference_context", "data": {}})
op("quality_policy", "quality", "Set acceptance requirements as undoable metadata. Prefer pixel_review_settings for typed fields; changing requirements invalidates earlier reviews.",
   ("data",), {"data": {"type": "object"}}, {"op": "quality_policy", "data": {}})
op("material_context", "material", "Set/clear optional portable normal maps and lighting settings as one undoable metadata edit. Prefer pixel_material preview/apply; original color cels are unchanged.",
   ("data",), {"data": {"anyOf": [{"type": "object"}, {"type": "null"}]}}, {"op": "material_context", "data": None})
op("character_profile", "character", "Set/clear portable approved character metadata in one undo step. Prefer pixel_character for validated capture, references and import/export.",
   ("data",), {"data": {"anyOf": [{"type": "object"}, {"type": "null"}]}}, {"op": "character_profile", "data": None})


@lru_cache(maxsize=None)
def validator(name):
    return Draft202012Validator(SPECS[name]["schema"])


def validate(operation):
    if not isinstance(operation, dict) or operation.get("op") not in SPECS:
        raise ValueError("Unknown operation. Read pixel_help(topic='operations') for supported op names.")
    errors = sorted(validator(operation["op"]).iter_errors(operation), key=lambda error: str(list(error.path)))
    if errors:
        error = errors[0]
        field = ".".join(map(str, error.path)) or "operation"
        raise ValueError(f"{field}: {error.message}")


def guide(topic="overview", operation=None):
    if operation:
        if operation not in SPECS:
            raise ValueError(f"Unknown operation {operation!r}; available: {', '.join(SPECS)}")
        return {"operation": operation, **deepcopy(SPECS[operation])}
    if topic == "operations":
        return {"operations": {name: {"category": value["category"], "description": value["description"]} for name, value in SPECS.items()},
                "next": "Call pixel_help(operation='<op>') to get its exact schema and a runnable example."}
    selected = {name: value for name, value in SPECS.items() if value["category"] == topic}
    if selected:
        return {"topic": topic, "operations": deepcopy(selected)}
    return {"topics": list(dict.fromkeys(["overview", "operations", *[value["category"] for value in SPECS.values()]])),
            "workflow": ["pixel_onboard", "pixel_status", "pixel_feedback list / inspect marked frames / ask if unclear",
                         "pixel_help(operation='polygon')", "pixel_validate", "pixel_edit", "pixel_preview / pixel_contact_sheet",
                         "pixel_feedback NEW inspect / resolve", "pixel_review / pixel_review_submit",
                         "pixel_project(action='save')", "pixel_export"],
            "feedback": "Read human canvas issues before repairing. Inspect every annotated frame and page; if unclear ask the user and wait for their actual reply. Do not guess answers or resolve from metadata. Reports are portable metadata and survive paint undo.",
            "coordinates": "Integer pixels; origin top-left. x right, y down. All frame/palette/stack indexes are zero-based. Rects are [x,y,width,height].",
            "targets": "Drawing commands accept layer id/name and frame; clip accepts a named region or rectangle. Explicit targets reduce accidental edits.",
            "transactions": "An edit batch is one atomic undo step. Pass the document_id and revision you actually read. Re-read and re-plan after conflicts.",
            "palette": "Use existing palette indexes or add RGBA hex colors first. Drawing is aliased; resizing uses nearest-neighbor.",
            "patterns": "Use native polygon/bezier for silhouettes; stamps are optional reusable pixel patterns, not a requirement to script outside the editor.",
            "new_document_example": [{"op": "layer_add", "id": "body", "name": "body"}, SPECS["polygon"]["example"]]}


def full_schema():
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Pixel Loom edit operation",
            "oneOf": [deepcopy(item["schema"]) for item in SPECS.values()]}


def python_type(schema):
    if "const" in schema:
        result = Literal[schema["const"]]
    elif "enum" in schema:
        result = Literal[tuple(schema["enum"])]
    elif "anyOf" in schema:
        result = Union[tuple(python_type(item) for item in schema["anyOf"])]
    else:
        result = {"integer": StrictInt, "string": StrictStr, "boolean": StrictBool, "null": type(None)}.get(schema.get("type"))
        if schema.get("type") == "array":
            result = list[python_type(schema["items"])]
        elif schema.get("type") == "object":
            extra = schema.get("additionalProperties", {})
            result = dict[str, python_type(extra)] if isinstance(extra, dict) and extra else dict
        if result is None:
            result = object
    constraints = {dest: schema[source] for source, dest in [("minimum", "ge"), ("maximum", "le"),
                    ("minLength", "min_length"), ("maxLength", "max_length"), ("pattern", "pattern"),
                    ("minItems", "min_length"), ("maxItems", "max_length"), ("description", "description")] if source in schema}
    return Annotated[result, Field(**constraints)] if constraints else result


def operation_type():
    types = []
    for name, item in SPECS.items():
        schema = item["schema"]
        fields = {key: Required[python_type(value)] if key in schema["required"] else python_type(value)
                  for key, value in schema["properties"].items()}
        model = TypedDict("".join(part.title() for part in name.split("_")) + "Operation", fields, total=False)
        model.__pydantic_config__ = ConfigDict(extra="forbid")
        model.__doc__ = item["description"]
        types.append(model)
    return Annotated[Union[tuple(types)], Field(discriminator="op")]


EditOperation = operation_type()

# Thin discovery schema, full authoritative schemas remain in guide/full_schema.
# Existing payloads are unchanged; Document.apply/validate still checks EVERY op
# with SPECS before committing anything. Avoid repeating every full schema in each tool.
NativeOperation = Annotated[dict[str, Any], Field(json_schema_extra={
    "properties":{"op":{"type":"string","enum":list(SPECS)}},"required":["op"],
    "description":"Native op object. Read pixel_help(operation='<op>') for its exact fields; all fields are validated atomically by the editor."})]
