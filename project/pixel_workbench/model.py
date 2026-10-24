from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import os
import tempfile
import uuid
import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

from .operations import validate as validate_operation


PALETTE = [
    "#00000000", "#181c2eff", "#30364fff", "#505977ff",
    "#79839bff", "#b1b9ccff", "#e4e8efff", "#ffffffff",
    "#743f5bff", "#b8526aff", "#eb7374ff", "#ffb69aff",
    "#a86435ff", "#df9445ff", "#f5c66aff", "#fff0a6ff",
    "#284d4aff", "#3b8069ff", "#6cbc8bff", "#b0e4a3ff",
    "#243d67ff", "#3978a8ff", "#65bad0ff", "#b1e9e3ff",
    "#543e7aff", "#8864b1ff", "#c29cd1ff", "#f1c4deff",
]
MAX_PIXELS = 8_388_608
MAX_PROJECT_BYTES = 100_000_000


class PixelError(ValueError):
    def __init__(self, message, code="INVALID_ARGUMENT", recovery=None, details=None):
        super().__init__(message)
        self.code = code
        self.recovery = recovery
        self.details = details


def integer(value, name="value", low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise PixelError(f"{name} must be an integer")
    if low is not None and value < low or high is not None and value > high:
        raise PixelError(f"{name} must be between {low} and {high}")
    return value


def rgba(value):
    if isinstance(value, (list, tuple)) and len(value) in (3, 4):
        values = tuple(integer(v, "channel", 0, 255) for v in value)
        return values + (255,) if len(values) == 3 else values
    if isinstance(value, str):
        value = value.removeprefix("#")
        if len(value) in (6, 8):
            try:
                values = tuple(int(value[i:i + 2], 16) for i in range(0, len(value), 2))
                return values + (255,) if len(values) == 3 else values
            except ValueError:
                pass
    raise PixelError("Color must be #RRGGBB, #RRGGBBAA, or an RGBA list")


def hexcolor(color):
    return "#" + "".join(f"{v:02x}" for v in color)


def pixels(image):
    return image.get_flattened_data() if hasattr(image, "get_flattened_data") else image.getdata()


def atomic_json(path, data):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, filename = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".writing", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        if isinstance(data,dict) and data.get('format')=='pixel-loom/v1' and temporary.stat().st_size>MAX_PROJECT_BYTES:
            raise PixelError('Project exceeds the 100 MB portable-file limit; export large material maps separately before saving.',code='PROJECT_TOO_LARGE')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass
class Layer:
    id: str
    name: str
    cels: list
    visible: bool = True
    locked: bool = False
    opacity: int = 255


class Document:
    """The authoritative integer-pixel model, shared by the GUI and agent API."""

    def __init__(self, width=48, height=48, name="未命名作品"):
        self.width = integer(width, "width", 1, 512)
        self.height = integer(height, "height", 1, 512)
        self.id = uuid.uuid4().hex
        self.name = str(name)[:120]
        self.palette = PALETTE.copy()
        self.strict_palette = True
        self.durations = [160]
        self.layers = [Layer(uuid.uuid4().hex[:12], "图层 1", [self.blank()])]
        self.active_layer = self.layers[0].id
        self.active_frame = 0
        self.regions = {}
        self.stamps = {}
        self.tags = {}
        self.selection = None
        self.reference = None
        self.character = None
        self.material = None
        self.effect_recipe = None
        self.quality_policy = None
        self.quality_reviews = []
        self.feedback = []
        self.revision = 0
        self.undo_stack = []
        self.redo_stack = []
        self.events = []
        self.last_change = None
        self.content_serial = 0
        self._fingerprint_cache = None

    def blank(self):
        return Image.new("RGBA", (self.width, self.height))

    def layer(self, target=None):
        target = self.active_layer if target is None else target
        for layer in self.layers:
            if layer.id == target:
                return layer
        matches = [layer for layer in self.layers if layer.name == target]
        if len(matches) == 1:
            return matches[0]
        raise PixelError(f"Unknown or ambiguous layer: {target!r}. Use its stable id.")

    def color(self, value):
        if isinstance(value, int) and not isinstance(value, bool):
            value = self.palette[integer(value, "palette index", 0, len(self.palette) - 1)]
        result = rgba(value)
        if result[3] and self.strict_palette and hexcolor(result) not in self.palette:
            raise PixelError(f"{hexcolor(result)} is outside the palette; add it with palette_add first")
        return result

    def state(self):
        from .character import summary as character_summary
        return {
            "character": character_summary(self.character),
            "document_id": self.id, "name": self.name, "width": self.width,
            "height": self.height, "revision": self.revision,
            "coordinate_system": "Integer pixels, origin top-left; x grows right, y grows down. Rect width/height are sizes.",
            "active_layer": self.active_layer, "active_frame": self.active_frame,
            "palette": self.palette, "strict_palette": self.strict_palette,
            "layers": [{"id": layer.id, "name": layer.name, "visible": layer.visible,
                        "locked": layer.locked, "opacity": layer.opacity,
                        "bounds": list(layer.cels[self.active_frame].getbbox() or [])}
                       for layer in self.layers],
            "frames": [{"index": i, "duration_ms": d} for i, d in enumerate(self.durations)],
            "regions": copy.deepcopy(self.regions), "stamps": sorted(self.stamps),
            "tags": [{"name": name, **tag} for name, tag in self.tags.items()],
            "selection": self.selection.copy() if self.selection else None,
            "can_undo": bool(self.undo_stack), "can_redo": bool(self.redo_stack),
            "events": self.events[-20:],
            "last_change": self.last_change,
        }

    def to_dict(self):
        data = {
            "format": "pixel-loom/v1", "document_id": self.id, "name": self.name,
            "width": self.width, "height": self.height, "revision": self.revision,
            "palette": self.palette.copy(), "strict_palette": self.strict_palette,
            "durations": self.durations.copy(), "active_layer": self.active_layer,
            "active_frame": self.active_frame, "regions": copy.deepcopy(self.regions),
            "stamps": copy.deepcopy(self.stamps),
            "tags": copy.deepcopy(self.tags), "selection": self.selection.copy() if self.selection else None,
            "layers": [{"id": layer.id, "name": layer.name, "visible": layer.visible,
                        "locked": layer.locked, "opacity": layer.opacity,
                        "cels": [base64.b64encode(zlib.compress(cel.tobytes())).decode("ascii")
                                 for cel in layer.cels]} for layer in self.layers],
        }
        if self.reference is not None:
            data["reference"] = copy.deepcopy(self.reference)
        if self.character is not None:
            data["character_profile"] = copy.deepcopy(self.character)
        if self.material is not None:
            data["material"] = copy.deepcopy(self.material)
        if self.effect_recipe is not None:
            data["effect_recipe"] = copy.deepcopy(self.effect_recipe)
        if self.quality_policy is not None:
            data["quality_policy"] = copy.deepcopy(self.quality_policy)
        if self.quality_reviews:
            data["quality_reviews"] = copy.deepcopy(self.quality_reviews)
        if self.feedback:
            data["feedback"] = copy.deepcopy(self.feedback)
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or data.get("format") != "pixel-loom/v1":
            raise PixelError("Unsupported project format; expected pixel-loom/v1")
        doc = cls(data["width"], data["height"], data.get("name", "未命名作品"))
        frames = data.get("durations", [])
        layers = data.get("layers", [])
        if not 1 <= len(frames) <= 256 or not 1 <= len(layers) <= 64:
            raise PixelError("Projects need 1–256 frames and 1–64 layers")
        if doc.width * doc.height * len(frames) * len(layers) > MAX_PIXELS:
            raise PixelError("Project exceeds the pixel memory limit")
        doc.durations = [integer(v, "duration_ms", 16, 60_000) for v in frames]
        palette = data.get("palette", PALETTE)
        if not 1 <= len(palette) <= 256:
            raise PixelError("Palette must contain 1–256 colors")
        doc.palette = list(dict.fromkeys(hexcolor(rgba(v)) for v in palette))
        doc.strict_palette = bool(data.get("strict_palette", True))
        doc.layers = []
        ids = set()
        expected = doc.width * doc.height * 4
        for item in layers:
            layer_id = str(item["id"])
            if layer_id in ids or len(item["cels"]) != len(frames):
                raise PixelError("Duplicate layer ids or inconsistent cel count")
            ids.add(layer_id)
            cels = []
            for encoded in item["cels"]:
                compressed = base64.b64decode(encoded, validate=True)
                decoder = zlib.decompressobj()
                raw = decoder.decompress(compressed, expected + 1)
                if len(raw) != expected or not decoder.eof or decoder.unused_data:
                    raise PixelError("Invalid or oversized cel pixel data")
                cels.append(Image.frombytes("RGBA", (doc.width, doc.height), raw))
            doc.layers.append(Layer(layer_id, str(item["name"])[:120], cels,
                                    bool(item.get("visible", True)), bool(item.get("locked", False)),
                                    integer(item.get("opacity", 255), "opacity", 0, 255)))
        doc.id = str(data.get("document_id", doc.id))
        doc.revision = integer(data.get("revision", 0), "revision", 0)
        doc.active_layer = doc.layer(data.get("active_layer", doc.layers[0].id)).id
        doc.active_frame = integer(data.get("active_frame", 0), "frame", 0, len(frames) - 1)
        doc.regions = copy.deepcopy(data.get("regions", {}))
        for name, rect in doc.regions.items():
            if not isinstance(name, str):
                raise PixelError("Region names must be strings")
            doc.validate_rect(rect)
        doc.stamps = copy.deepcopy(data.get("stamps", {}))
        for stamp in doc.stamps.values():
            doc.validate_stamp(stamp)
        doc.tags = copy.deepcopy(data.get("tags", {}))
        if not isinstance(doc.tags, dict) or len(doc.tags) > 128:
            raise PixelError("Project must contain at most 128 named animation tags")
        for name, tag in doc.tags.items():
            if not isinstance(name, str) or not 1 <= len(name) <= 120:
                raise PixelError("Animation tag names must contain 1–120 characters")
            start = integer(tag["start"], "tag start", 0, len(frames) - 1)
            integer(tag["end"], "tag end", start, len(frames) - 1)
            if tag.get("direction", "forward") not in ("forward", "reverse", "pingpong"):
                raise PixelError("Invalid animation tag direction")
        doc.selection = data.get("selection")
        if doc.selection is not None:
            doc.selection = list(doc.validate_rect(doc.selection))
        if data.get("reference") is not None:
            from .reference import validate_context
            doc.reference = validate_context(data["reference"])
        if data.get("character_profile") is not None:
            from .character import validate_profile
            doc.character = validate_profile(data["character_profile"], doc.width, doc.height)
        if data.get('material') is not None:
            from .materials import validate_material
            doc.material = validate_material(data['material'])
        if data.get("effect_recipe") is not None:
            value = data["effect_recipe"]
            if not isinstance(value, dict) or set(value) != {"format", "settings"} or value["format"] != "pixel-loom/effect/v1" or not isinstance(value["settings"], dict):
                raise PixelError("Invalid effect recipe")
            try:
                if len(json.dumps(value, ensure_ascii=False, allow_nan=False)) > 16_384:
                    raise ValueError('Legacy metadata too large')
            except (TypeError, ValueError, RecursionError) as exc:
                raise PixelError('Invalid legacy effect metadata') from exc
            doc.effect_recipe = copy.deepcopy(value)  # Inert 0.7.9 metadata; never generates artwork.
        if data.get("quality_policy") is not None or data.get("quality_reviews"):
            from .quality import validate_policy, validate_records
            if data.get("quality_policy") is not None:
                doc.quality_policy = validate_policy(data["quality_policy"])
            doc.quality_reviews = validate_records(data.get("quality_reviews", []))
        if data.get("feedback") is not None:
            from .feedback import validate_records as validate_feedback
            doc.feedback = validate_feedback(data["feedback"])
        return doc

    @classmethod
    def open(cls, path):
        if Path(path).stat().st_size > MAX_PROJECT_BYTES:
            raise PixelError("Project file is too large")
        with Path(path).open(encoding="utf-8-sig") as handle:
            return cls.from_dict(json.load(handle))

    def save(self, path):
        atomic_json(path, self.to_dict())

    def fingerprint(self):
        key = self.id, self.revision
        if self._fingerprint_cache and self._fingerprint_cache[0] == key:
            return self._fingerprint_cache[1]
        data = self.to_dict()
        for field in ("revision", "active_layer", "active_frame", "selection"):
            data.pop(field, None)
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
        self._fingerprint_cache = key, digest
        return digest

    def _adopt(self, other):
        # Feedback is a human conversation, not paint history. Undo/redo must
        # never delete a report or restore an old answer from a drawing snapshot.
        for key in ("id", "name", "width", "height", "palette", "strict_palette", "durations",
                    "layers", "active_layer", "active_frame", "regions", "stamps", "tags", "selection", "reference", "character", "material", "effect_recipe", "quality_policy", "quality_reviews"):
            setattr(self, key, getattr(other, key))

    def _event(self, label, source, count):
        self.events.append({"revision": self.revision, "label": str(label)[:200],
                            "source": source, "operations": count})
        self.events = self.events[-100:]

    def record_quality_review(self, record):
        from .quality import RECORD_LIMIT, validate_records
        self.quality_reviews = validate_records([*self.quality_reviews[-(RECORD_LIMIT-1):], record])
        self.revision += 1
        self._event("AI 自检 · "+record["status"], "AI", 0)

    def apply(self, operations, label="像素编辑", expected_revision=None, expected_document_id=None, source="AI"):
        if expected_revision is not None and expected_revision != self.revision:
            raise PixelError(f"Revision conflict: expected {expected_revision}, current {self.revision}. Read state again.",
                             code="REVISION_CONFLICT", recovery="Call pixel_status, inspect the newer artwork, then revise the plan.")
        if expected_document_id is not None and expected_document_id != self.id:
            raise PixelError("Document conflict: a different project is open. Read state again.", code="DOCUMENT_CONFLICT")
        if not isinstance(operations, list) or not 1 <= len(operations) <= 2000:
            raise PixelError("A transaction needs 1–2000 operations")
        for index, operation in enumerate(operations):
            try:
                validate_operation(operation)
            except ValueError as exc:
                raise PixelError(f"Operation {index}: {exc}", code="INVALID_OPERATION",
                                 recovery="Read pixel_help(operation='<op>') for the exact parameter schema.") from exc
        # View changes retain painting history and never clone/compress pixel buffers.
        if all(operation["op"] in ("select", "selection_set") for operation in operations):
            before_view = (self.active_layer, self.active_frame, self.selection)
            try:
                for operation in operations:
                    self.execute(operation)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                self.active_layer, self.active_frame, self.selection = before_view
                raise PixelError(str(exc), code=getattr(exc, "code", "INVALID_OPERATION")) from exc
            if (self.active_layer, self.active_frame, self.selection) != before_view:
                cache = self._fingerprint_cache
                old_key = self.id, self.revision
                self.revision += 1
                if cache and cache[0] == old_key:
                    self._fingerprint_cache = (self.id, self.revision), cache[1]
                self.last_change = {"frames": [], "visible_pixels_changed": 0}
                self._event(label, source, len(operations))
            return self.state()
        before = self.to_dict()
        working = self.from_dict(before)
        for index, operation in enumerate(operations):
            try:
                working.execute(operation)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                raise PixelError(f"Operation {index} ({operation.get('op', '?') if isinstance(operation, dict) else '?'}): {exc}",
                                 code=getattr(exc, "code", "INVALID_OPERATION"), recovery=getattr(exc, "recovery", None)) from exc
        changes = []
        for frame in range(max(len(self.durations), len(working.durations))):
            old = self.composite(frame) if frame < len(self.durations) else self.blank()
            new = working.composite(frame) if frame < len(working.durations) else self.blank()
            if old.size != new.size:
                extent = (max(old.width, new.width), max(old.height, new.height))
                old_canvas, new_canvas = Image.new("RGBA", extent), Image.new("RGBA", extent)
                old_canvas.paste(old, (0, 0))
                new_canvas.paste(new, (0, 0))
                old, new = old_canvas, new_canvas
            diff = ImageChops.difference(old, new)
            box = diff.getbbox(alpha_only=False)
            if box:
                values = diff.crop(box)
                changed_values = pixels(values)
                changes.append({"frame": frame, "rect": [box[0], box[1], box[2] - box[0], box[3] - box[1]],
                                "visible_pixels_changed": sum(any(pixel) for pixel in changed_values)})
        self.undo_stack.append(before)
        self.undo_stack = self.undo_stack[-40:]
        self.redo_stack.clear()
        self._adopt(working)
        self.revision += 1
        self.content_serial += 1
        self.last_change = {"frames": changes, "visible_pixels_changed": sum(item["visible_pixels_changed"] for item in changes)}
        self._event(label, source, len(operations))
        return self.state()

    def undo(self):
        if not self.undo_stack:
            return False
        restored = self.from_dict(self.undo_stack[-1])
        self.redo_stack.append(self.to_dict())
        self.undo_stack.pop()
        self._adopt(restored)
        self.revision += 1
        self.content_serial += 1
        self.last_change = None
        self._event("撤销", "history", 0)
        return True

    def use_version(self, restored, label, source='AI'):
        """Choose earlier artwork within this project; preserve shared undo and human reports."""
        restored.id, restored.name = self.id, self.name
        restored.quality_reviews = []
        self.undo_stack.append(self.to_dict())
        self.undo_stack = self.undo_stack[-40:]
        self.redo_stack.clear()
        self._adopt(restored)
        self.revision += 1
        self.content_serial += 1
        self.last_change = None
        self._event(label, source, 0)

    def redo(self):
        if not self.redo_stack:
            return False
        restored = self.from_dict(self.redo_stack[-1])
        self.undo_stack.append(self.to_dict())
        self.redo_stack.pop()
        self._adopt(restored)
        self.revision += 1
        self.content_serial += 1
        self.last_change = None
        self._event("重做", "history", 0)
        return True

    def rendering_layers(self, layers=None):
        included = None
        if layers is not None:
            if not isinstance(layers, list) or not 1 <= len(layers) <= 64 or any(not isinstance(item, str) for item in layers):
                raise PixelError("layers must be a nonempty list of at most 64 layer ids or names")
            included = {self.layer(item).id for item in layers}
        return [layer for layer in self.layers if (layer.visible if included is None else layer.id in included)]

    def composite(self, frame=None, override=None, layers=None):
        frame = self.active_frame if frame is None else integer(frame, "frame", 0, len(self.durations) - 1)
        result = self.blank()
        for layer in self.rendering_layers(layers):
            image = override[1] if override and override[0] == layer.id else layer.cels[frame]
            if layer.opacity < 255:
                image = image.copy()
                image.putalpha(image.getchannel("A").point(lambda a: a * layer.opacity // 255))
            result = Image.alpha_composite(result, image)
        return result

    def validate_rect(self, rect):
        if not isinstance(rect, (list, tuple)) or len(rect) != 4:
            raise PixelError("Rect must be [x, y, width, height]")
        x, y, w, h = [integer(v, "rect") for v in rect]
        if w < 1 or h < 1 or x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            raise PixelError("Region must be a non-empty rectangle inside the canvas")
        return x, y, w, h

    def validate_stamp(self, stamp):
        rows, colors = stamp["rows"], stamp["colors"]
        if not rows or len(rows) > 512 or not 1 <= len(rows[0]) <= 512:
            raise PixelError("Stamp dimensions must be 1–512")
        if any(not isinstance(row, str) or len(row) != len(rows[0]) for row in rows):
            raise PixelError("Stamp rows must have the same width")
        for row in rows:
            for symbol in row:
                if symbol != "." and symbol not in colors:
                    raise PixelError(f"Stamp symbol {symbol!r} has no color; '.' means skip")
        for symbol, color in colors.items():
            if len(symbol) != 1 or symbol == ".":
                raise PixelError("Stamp symbols must be one character; '.' is reserved")
            self.color(color)

    def _capacity(self, layers=None, frames=None):
        layers = len(self.layers) if layers is None else layers
        frames = len(self.durations) if frames is None else frames
        if layers > 64 or frames > 256 or layers * frames * self.width * self.height > MAX_PIXELS:
            raise PixelError("Project capacity exceeded (64 layers, 256 frames, 8M total pixels)")

    def _tag_insert(self, index, count=1):
        for tag in self.tags.values():
            if index <= tag["start"]:
                tag["start"] += count
                tag["end"] += count
            elif index <= tag["end"] + 1:
                tag["end"] += count

    def _tag_delete(self, index):
        for name, tag in list(self.tags.items()):
            if tag["start"] == tag["end"] == index:
                del self.tags[name]
            elif index < tag["start"]:
                tag["start"] -= 1
                tag["end"] -= 1
            elif index <= tag["end"]:
                tag["end"] -= 1

    def _resolve_rect(self, value=None):
        value = self.selection if value is None else value
        if value is None:
            raise PixelError("Provide rect or set a selection first")
        return self.validate_rect(self.regions[value] if isinstance(value, str) else value)

    def _clip_rect(self, rect):
        x, y, w, h = rect
        left, top = max(0, x), max(0, y)
        right, bottom = min(self.width, x + w), min(self.height, y + h)
        return [left, top, right - left, bottom - top] if right > left and bottom > top else None

    def _resize(self, width, height, anchor="top_left", scale=False):
        width, height = integer(width, "width", 1, 512), integer(height, "height", 1, 512)
        if width * height * len(self.layers) * len(self.durations) > MAX_PIXELS:
            raise PixelError("Resized canvas exceeds project memory limit")
        old_w, old_h = self.width, self.height
        dx = (width - old_w) // 2 if anchor in ("center", "bottom_center") else 0
        dy = (height - old_h) // 2 if anchor == "center" else height - old_h if anchor == "bottom_center" else 0
        for layer in self.layers:
            changed = []
            for cel in layer.cels:
                if scale:
                    changed.append(cel.resize((width, height), Image.Resampling.NEAREST))
                else:
                    canvas = Image.new("RGBA", (width, height))
                    canvas.paste(cel, (dx, dy))
                    changed.append(canvas)
            layer.cels = changed
        self.width, self.height = width, height
        def transform(rect):
            x, y, w, h = rect
            if scale:
                left, top = round(x * width / old_w), round(y * height / old_h)
                return self._clip_rect([left, top, max(1, round((x + w) * width / old_w) - left),
                                       max(1, round((y + h) * height / old_h) - top)])
            return self._clip_rect([x + dx, y + dy, w, h])
        self.regions = {name: result for name, rect in self.regions.items() if (result := transform(rect))}
        if self.selection:
            self.selection = transform(self.selection)
        if self.character:
            from .character import resized
            self.character = resized(self.character, width, height, transform, dx, dy, scale)

    def execute(self, op):
        if not isinstance(op, dict):
            raise PixelError("Operation must be an object")
        kind = op["op"]
        if kind in ("canvas_resize", "sprite_scale"):
            self._resize(op["width"], op["height"], op.get("anchor", "top_left"), scale=kind == "sprite_scale")
            return
        if kind == "selection_set":
            self.selection = list(self.validate_rect(op["rect"])) if "rect" in op else None
            return
        if kind == "layer_duplicate":
            self._capacity(layers=len(self.layers) + 1)
            source = self.layer(op.get("layer"))
            name = str(op.get("name", source.name + " copy"))[:120]
            suffix = 2
            while any(layer.name == name for layer in self.layers):
                if "name" in op:
                    raise PixelError("Layer names must be unique")
                name = source.name[:100] + f" copy {suffix}"
                suffix += 1
            layer_id = str(op.get("id", uuid.uuid4().hex[:12]))
            if any(layer.id == layer_id for layer in self.layers):
                raise PixelError("Layer id already exists")
            duplicate = Layer(layer_id, name, [cel.copy() for cel in source.cels], source.visible, False, source.opacity)
            self.layers.insert(self.layers.index(source) + 1, duplicate)
            self.active_layer = layer_id
            return
        if kind == "layer_merge_down":
            upper = self.layer(op.get("layer"))
            index = self.layers.index(upper)
            if index == 0:
                raise PixelError("No layer exists below this layer")
            lower = self.layers[index - 1]
            if upper.locked or lower.locked:
                raise PixelError("Both layers must be unlocked to merge", code="LAYER_LOCKED")
            if not upper.visible or not lower.visible:
                raise PixelError("Make both layers visible before merging")
            def bake(image, opacity):
                result = image.copy()
                result.putalpha(result.getchannel("A").point(lambda value: value * opacity // 255))
                return result
            lower.cels = [Image.alpha_composite(bake(a, lower.opacity), bake(b, upper.opacity))
                          for a, b in zip(lower.cels, upper.cels)]
            lower.opacity = 255
            self.layers.remove(upper)
            self.active_layer = lower.id
            return
        if kind == "frame_move":
            source = integer(op["frame"], "frame", 0, len(self.durations) - 1)
            target = integer(op["index"], "index", 0, len(self.durations) - 1)
            self.durations.insert(target, self.durations.pop(source))
            for layer in self.layers:
                layer.cels.insert(target, layer.cels.pop(source))
            self.active_frame = target
            return
        if kind == "frame_duplicate_range":
            start = integer(op["start"], "start", 0, len(self.durations) - 1)
            end = integer(op["end"], "end", start, len(self.durations) - 1)
            insert = integer(op["after"], "after", 0, len(self.durations) - 1) + 1
            count = end - start + 1
            self._capacity(frames=len(self.durations) + count)
            durations = self.durations[start:end + 1]
            for layer in self.layers:
                copies = [cel.copy() for cel in layer.cels[start:end + 1]]
                layer.cels[insert:insert] = copies
            self.durations[insert:insert] = durations
            self._tag_insert(insert, count)
            self.active_frame = insert
            return
        if kind == "tag_set":
            start = integer(op["start"], "start", 0, len(self.durations) - 1)
            end = integer(op["end"], "end", start, len(self.durations) - 1)
            if len(self.tags) >= 128 and op["name"] not in self.tags:
                raise PixelError("At most 128 animation tags are supported")
            self.tags[op["name"]] = {"start": start, "end": end, "direction": op.get("direction", "forward")}
            return
        if kind == "tag_delete":
            del self.tags[op["name"]]
            return
        if kind == "layer_add":
            self._capacity(layers=len(self.layers) + 1)
            name = str(op.get("name", f"图层 {len(self.layers) + 1}"))[:120]
            if any(layer.name == name for layer in self.layers):
                raise PixelError("Layer names must be unique")
            layer_id = str(op.get("id", uuid.uuid4().hex[:12]))
            if any(layer.id == layer_id for layer in self.layers):
                raise PixelError("Layer id already exists")
            self.layers.append(Layer(layer_id, name, [self.blank() for _ in self.durations]))
            self.active_layer = layer_id
            return
        if kind == "layer_set":
            layer = self.layer(op.get("layer"))
            if "name" in op:
                name = str(op["name"])[:120]
                if any(other.id != layer.id and other.name == name for other in self.layers):
                    raise PixelError("Layer names must be unique")
                layer.name = name
            for key in ("visible", "locked"):
                if key in op:
                    if not isinstance(op[key], bool):
                        raise PixelError(f"{key} must be true or false")
                    setattr(layer, key, op[key])
            if "opacity" in op:
                layer.opacity = integer(op["opacity"], "opacity", 0, 255)
            return
        if kind == "layer_move":
            layer = self.layer(op.get("layer"))
            index = integer(op["index"], "index", 0, len(self.layers) - 1)
            self.layers.remove(layer)
            self.layers.insert(index, layer)
            return
        if kind == "layer_delete":
            layer = self.layer(op.get("layer"))
            if len(self.layers) == 1 or layer.locked:
                raise PixelError("Cannot delete the final layer or a locked layer")
            self.layers.remove(layer)
            if self.active_layer == layer.id:
                self.active_layer = self.layers[-1].id
            return
        if kind == "frame_add":
            self._capacity(frames=len(self.durations) + 1)
            index = integer(op.get("after", self.active_frame), "after", 0, len(self.durations) - 1)
            source = integer(op.get("copy_from", index), "copy_from", 0, len(self.durations) - 1)
            for layer in self.layers:
                layer.cels.insert(index + 1, self.blank() if op.get("blank", False) else layer.cels[source].copy())
            self.durations.insert(index + 1, integer(op.get("duration_ms", self.durations[source]), "duration_ms", 16, 60_000))
            self._tag_insert(index + 1)
            self.active_frame = index + 1
            return
        if kind == "frame_set":
            frame = integer(op.get("frame", self.active_frame), "frame", 0, len(self.durations) - 1)
            self.durations[frame] = integer(op["duration_ms"], "duration_ms", 16, 60_000)
            return
        if kind == "frame_delete":
            if len(self.durations) == 1:
                raise PixelError("Cannot delete the final frame")
            frame = integer(op.get("frame", self.active_frame), "frame", 0, len(self.durations) - 1)
            self.durations.pop(frame)
            self._tag_delete(frame)
            for layer in self.layers:
                layer.cels.pop(frame)
            self.active_frame = min(self.active_frame, len(self.durations) - 1)
            return
        if kind == "select":
            if "layer" in op:
                self.active_layer = self.layer(op["layer"]).id
            if "frame" in op:
                self.active_frame = integer(op["frame"], "frame", 0, len(self.durations) - 1)
            return
        if kind == "palette_add":
            for value in op["colors"]:
                color = hexcolor(self.color(value) if isinstance(value, int) else rgba(value))
                if color not in self.palette:
                    if len(self.palette) == 256:
                        raise PixelError("Palette already has 256 colors")
                    self.palette.append(color)
            return
        if kind == "palette_set":
            palette = list(dict.fromkeys(hexcolor(self.color(value) if isinstance(value, int) else rgba(value)) for value in op["colors"]))
            colors = [rgba(value) for value in palette]
            existing = {pixel for layer in self.layers for cel in layer.cels for pixel in pixels(cel) if pixel[3]}
            if not op.get("remap", False) and any(hexcolor(pixel) not in palette for pixel in existing):
                raise PixelError("Artwork contains colors outside the new palette; enable remap or include those colors")
            if op.get("remap", False):
                opaque = [color for color in colors if color[3]]
                if existing and not opaque:
                    raise PixelError("The palette needs an opaque color to remap opaque artwork")
                mapping = {pixel: min(opaque, key=lambda color: sum((a - b) ** 2 for a, b in zip(pixel, color))) for pixel in existing}
                for layer in self.layers:
                    for cel in layer.cels:
                        cel.putdata([mapping.get(pixel, (0, 0, 0, 0)) for pixel in pixels(cel)])
            self.palette = palette
            return
        if kind == "palette_lock":
            if not isinstance(op["enabled"], bool):
                raise PixelError("enabled must be true or false")
            self.strict_palette = op["enabled"]
            return
        if kind == "region_define":
            name = str(op["name"])[:120]
            if len(self.regions) >= 128 and name not in self.regions:
                raise PixelError("At most 128 named regions are supported")
            self.regions[name] = list(self.validate_rect(op["rect"]))
            return
        if kind == "region_delete":
            del self.regions[op["name"]]
            return
        if kind == "stamp_define":
            stamp = {"rows": op["rows"], "colors": op["colors"]}
            self.validate_stamp(stamp)
            name = str(op["name"])[:120]
            if len(self.stamps) >= 128 and name not in self.stamps:
                raise PixelError("At most 128 stamps are supported")
            self.stamps[name] = copy.deepcopy(stamp)
            return
        if kind == "rename":
            self.name = str(op["name"])[:120]
            return
        if kind == "reference_context":
            from .reference import validate_context
            self.reference = validate_context(op["data"])
            return
        if kind == 'material_context':
            from .materials import validate_material
            self.material = validate_material(op['data'])
            if self.material is not None and len(json.dumps(self.to_dict(),ensure_ascii=False,separators=(',',':')).encode())>MAX_PROJECT_BYTES:
                raise PixelError('Embedded material would exceed the portable project limit; export maps as a bundle instead.',code='PROJECT_TOO_LARGE')
            return
        if kind == "character_profile":
            from .character import validate_profile
            self.character = validate_profile(op["data"], self.width, self.height) if op["data"] is not None else None
            return
        if kind == "quality_policy":
            from .quality import validate_policy
            self.quality_policy = validate_policy(op["data"])
            return
        layer = self.layer(op.get("layer"))
        if layer.locked:
            raise PixelError(f"Layer {layer.name!r} is locked", code="LAYER_LOCKED",
                             recovery="Choose an unlocked layer, duplicate this layer, or explicitly unlock it if intended.")
        frame = integer(op.get("frame", self.active_frame), "frame", 0, len(self.durations) - 1)
        original = layer.cels[frame]
        image = original.copy()
        if kind in ("region_transform", "region_copy"):
            x, y, w, h = self._resolve_rect(op.get("rect"))
            if kind == "region_copy":
                source_layer = self.layer(op.get("source_layer", layer.id))
                source_frame = integer(op.get("source_frame", frame), "source_frame", 0, len(self.durations) - 1)
                patch = source_layer.cels[source_frame].crop((x, y, x + w, y + h))
                if 'polygon' in op or 'holes' in op:
                    mask=Image.new('L',(w,h),0 if 'polygon' in op else 255)
                    painter=ImageDraw.Draw(mask)
                    if 'polygon' in op:painter.polygon([(a-x,b-y) for a,b in op['polygon']],fill=255)
                    for hole in op.get('holes',[]):painter.polygon([(a-x,b-y) for a,b in hole],fill=0)
                    patch.paste((0,0,0,0),mask=ImageChops.invert(mask))
                target_x, target_y = op["x"], op["y"]
            else:
                patch = image.crop((x, y, x + w, y + h))
                target_x, target_y = x, y
                transform = op["kind"]
                if transform == "translate":
                    target_x += op.get("dx", 0)
                    target_y += op.get("dy", 0)
                else:
                    method = {"flip_horizontal": Image.Transpose.FLIP_LEFT_RIGHT,
                              "flip_vertical": Image.Transpose.FLIP_TOP_BOTTOM,
                              "rotate_cw": Image.Transpose.ROTATE_270, "rotate_ccw": Image.Transpose.ROTATE_90}[transform]
                    patch = patch.transpose(method)
                if not op.get("copy", False):
                    image.paste((0, 0, 0, 0), (x, y, x + w, y + h))
                result_rect = self._clip_rect([target_x, target_y, patch.width, patch.height])
                if not op.get("copy", False) and op.get("update_region", False) and isinstance(op.get("rect"), str):
                    if result_rect:
                        self.regions[op["rect"]] = result_rect
                    else:
                        self.regions.pop(op["rect"], None)
                if self.selection == [x, y, w, h]:
                    self.selection = result_rect
            if op.get("blend") == "over":
                temporary = self.blank()
                temporary.paste(patch, (target_x, target_y))
                image = Image.alpha_composite(image, temporary)
            else:
                image.paste(patch, (target_x, target_y))
            layer.cels[frame] = image
            return
        if self.selection and "clip" not in op and kind in ("pixel", "stroke", "line", "rect", "ellipse", "polygon", "bezier", "fill", "clear", "replace", "outline", "dither", "stamp"):
            op = {**op, "clip": self.selection}
        self.draw_on(image, op)
        if "clip" in op:
            rect = self.regions[op["clip"]] if isinstance(op["clip"], str) else op["clip"]
            x, y, w, h = self.validate_rect(rect)
            result = original.copy()
            result.paste(image.crop((x, y, x + w, y + h)), (x, y))
            image = result
        layer.cels[frame] = image

    def draw_on(self, image, op):
        kind = op["op"]
        draw = ImageDraw.Draw(image)
        if kind in ("pixel", "stroke", "line", "rect", "ellipse", "polygon", "bezier", "fill", "replace", "outline", "dither"):
            color = self.color(op.get("color", 7))
        if kind == "pixel":
            x, y = integer(op["x"], "x", 0, self.width - 1), integer(op["y"], "y", 0, self.height - 1)
            image.putpixel((x, y), color)
        elif kind in ("stroke", "line"):
            points = op.get("points", []) if kind == "stroke" else [[op["x1"], op["y1"]], [op["x2"], op["y2"]]]
            if not points or len(points) > 100_000:
                raise PixelError("Stroke needs 1–100000 points")
            points = [(integer(p[0], "x", -4096, 4096), integer(p[1], "y", -4096, 4096)) for p in points]
            size = integer(op.get("size", 1), "size", 1, 32)
            if len(points) > 1:
                draw.line(points, fill=color, width=size)
            offset = (size - 1) // 2
            for x, y in points:
                draw.rectangle((x - offset, y - offset, x - offset + size - 1, y - offset + size - 1), fill=color)
        elif kind == "polygon":
            points = [(integer(point[0], "x", -4096, 4096), integer(point[1], "y", -4096, 4096)) for point in op["points"]]
            if op.get("filled", True):
                draw.polygon(points, fill=color)
            else:
                draw.line(points + points[:1], fill=color, width=integer(op.get("size", 1), "size", 1, 32))
        elif kind == "bezier":
            control = op["points"]
            steps = min(2048, max(8, sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(control, control[1:])) * 2))
            points = []
            for index in range(steps + 1):
                t = index / steps
                work = [(float(x), float(y)) for x, y in control]
                while len(work) > 1:
                    work = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(work, work[1:])]
                points.append(tuple(round(value) for value in work[0]))
            draw.line(points, fill=color, width=integer(op.get("size", 1), "size", 1, 32))
        elif kind in ("rect", "ellipse"):
            x, y = integer(op["x"], "x", -4096, 4096), integer(op["y"], "y", -4096, 4096)
            w, h = integer(op["width"], "width", 1, 4096), integer(op["height"], "height", 1, 4096)
            box = (x, y, x + w - 1, y + h - 1)
            kwargs = {"fill": color} if op.get("filled", True) else {"outline": color, "width": integer(op.get("size", 1), "size", 1, 32)}
            getattr(draw, kind if kind == "ellipse" else "rectangle")(box, **kwargs)
        elif kind == "fill":
            x, y = integer(op["x"], "x", 0, self.width - 1), integer(op["y"], "y", 0, self.height - 1)
            # Limit traversal to the clip so a fill cannot leak around its boundary.
            rect = op.get("clip", [0, 0, self.width, self.height])
            rect = self.regions[rect] if isinstance(rect, str) else rect
            rx, ry, rw, rh = self.validate_rect(rect)
            if not rx <= x < rx + rw or not ry <= y < ry + rh:
                raise PixelError("Fill seed is outside its clip")
            tile = image.crop((rx, ry, rx + rw, ry + rh))
            ImageDraw.floodfill(tile, (x - rx, y - ry), color, thresh=0)
            image.paste(tile, (rx, ry))
        elif kind == "clear":
            image.paste((0, 0, 0, 0), (0, 0, self.width, self.height))
        elif kind == "replace":
            old = self.color(op["old_color"])
            image.putdata([color if p == old else p for p in pixels(image)])
        elif kind == "translate":
            dx, dy = integer(op["dx"], "dx", -4096, 4096), integer(op["dy"], "dy", -4096, 4096)
            moved = self.blank()
            moved.paste(image, (dx, dy))
            image.paste(moved)
        elif kind == "flip":
            axis = op.get("axis", "horizontal")
            if axis not in ("horizontal", "vertical"):
                raise PixelError("axis must be horizontal or vertical")
            image.paste(image.transpose(Image.Transpose.FLIP_LEFT_RIGHT if axis == "horizontal" else Image.Transpose.FLIP_TOP_BOTTOM))
        elif kind == "outline":
            source = image.copy()
            neighbors = [(1, 0), (-1, 0), (0, 1), (0, -1)]
            if op.get("diagonal", False):
                neighbors += [(1, 1), (-1, 1), (1, -1), (-1, -1)]
            alpha = source.getchannel("A")
            for y in range(self.height):
                for x in range(self.width):
                    if not alpha.getpixel((x, y)) and any(0 <= x + dx < self.width and 0 <= y + dy < self.height and alpha.getpixel((x + dx, y + dy)) for dx, dy in neighbors):
                        image.putpixel((x, y), color)
        elif kind == "dither":
            other = self.color(op["other_color"])
            x, y, w, h = self.validate_rect(op.get("rect", [0, 0, self.width, self.height]))
            for py in range(y, y + h):
                for px in range(x, x + w):
                    image.putpixel((px, py), color if (px + py) % 2 else other)
        elif kind == "stamp":
            stamp = self.stamps[op["name"]] if "name" in op else {"rows": op["rows"], "colors": op["colors"]}
            self.validate_stamp(stamp)
            x, y = integer(op.get("x", 0), "x", -4096, 4096), integer(op.get("y", 0), "y", -4096, 4096)
            scale = integer(op.get("scale", 1), "scale", 1, 16)
            colors = {k: self.color(v) for k, v in stamp["colors"].items()}
            for sy, row in enumerate(stamp["rows"]):
                for sx, symbol in enumerate(row):
                    if symbol != ".":
                        px, py = x + sx * scale, y + sy * scale
                        draw.rectangle((px, py, px + scale - 1, py + scale - 1), fill=colors[symbol])
        else:
            raise PixelError(f"Unknown operation: {kind}")

    def inspect(self, rect=None, layer=None, frame=None, region=None):
        if region is not None:
            rect = self.regions[region]
        x, y, w, h = self.validate_rect(rect or [0, 0, self.width, self.height])
        if w > 128 or h > 128:
            raise PixelError("Text inspection is limited to 128×128; request a smaller rect or use preview")
        frame = self.active_frame if frame is None else integer(frame, "frame", 0, len(self.durations) - 1)
        image = self.layer(layer).cels[frame] if layer is not None else self.composite(frame)
        cropped = image.crop((x, y, x + w, y + h))
        colors = sorted(cropped.getcolors(w * h), key=lambda entry: -entry[0])
        symbols = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!$%&*+=?@~^:;<>/|"
        mapping = {}
        legend = {}
        for count, color in colors:
            key = "." if color[3] == 0 else (symbols[len(mapping) % len(symbols)] if len(colors) <= len(symbols) else hexcolor(color))
            mapping[color] = key
            legend[key] = {"color": hexcolor(color), "pixels": count}
        rows = [[mapping[cropped.getpixel((px, py))] for px in range(w)] for py in range(h)]
        return {"document_id": self.id, "revision": self.revision, "rect": [x, y, w, h],
                "frame": frame, "layer": layer or "composite", "legend": legend,
                "rows": ["".join(row) for row in rows] if len(colors) <= len(symbols) else rows}

    def preview(self, frame=None, scale=8, rect=None, checker=True, layers=None):
        image = self.composite(frame, layers=layers)
        if rect is not None:
            x, y, w, h = self.validate_rect(rect)
            image = image.crop((x, y, x + w, y + h))
        if checker:
            background = Image.new("RGBA", image.size, "#262a35")
            draw = ImageDraw.Draw(background)
            for y in range(0, image.height, 4):
                for x in range(0, image.width, 4):
                    if (x // 4 + y // 4) % 2:
                        draw.rectangle((x, y, x + 3, y + 3), fill="#303542")
            image = Image.alpha_composite(background, image)
        scale = integer(scale, "scale", 1, 32)
        if image.width * image.height * scale * scale > 4_194_304:
            raise PixelError("Preview exceeds 4M pixels; choose a smaller scale or crop")
        return image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)

    def frame_indices(self, tag=None, playback=False):
        if tag is None:
            return list(range(len(self.durations)))
        if tag not in self.tags:
            raise PixelError(f"Unknown animation tag {tag!r}")
        item = self.tags[tag]
        indexes = list(range(item["start"], item["end"] + 1))
        if playback and item.get("direction") == "reverse":
            indexes.reverse()
        elif playback and item.get("direction") == "pingpong" and len(indexes) > 2:
            indexes += indexes[-2:0:-1]
        return indexes

    def contact_sheet(self, frames=None, tag=None, columns=6, scale=3, labels=True):
        indexes = self.frame_indices(tag) if frames is None else [integer(i, "frame", 0, len(self.durations) - 1) for i in frames]
        if not 1 <= len(indexes) <= 64:
            raise PixelError("Contact sheets support 1–64 frames; request a smaller range")
        columns = min(integer(columns, "columns", 1, 16), len(indexes))
        scale = integer(scale, "scale", 1, 8)
        header = 20 if labels else 0
        tile_w, tile_h = self.width * scale, self.height * scale + header
        rows = math.ceil(len(indexes) / columns)
        if tile_w * columns * tile_h * rows > 4_194_304:
            raise PixelError("Contact sheet exceeds 4M output pixels; reduce scale or frame count")
        sheet = Image.new("RGBA", (tile_w * columns, tile_h * rows), "#20242d")
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default()
        for index, frame in enumerate(indexes):
            x, y = index % columns * tile_w, index // columns * tile_h
            sheet.paste(self.preview(frame, scale), (x, y + header))
            if labels:
                draw.text((x + 4, y + 4), f"#{frame}  {self.durations[frame]}ms", fill="#f4b477", font=font)
        return sheet

    def export(self, path, kind="png", scale=1, columns=None, tag=None, loop=True, sheet_format='native'):
        from .sheet_export import aseprite_data,check_sidecars,export_paths,godot_resource,write_bundle
        path = Path(path)
        outputs=export_paths(path,kind,sheet_format)
        check_sidecars(path,kind,sheet_format)
        scale = integer(scale, "scale", 1, 16)
        indexes = self.frame_indices(tag, playback=kind == "gif")
        frame_count = len(indexes) if kind in ("sheet", "gif") else 1
        if self.width * self.height * frame_count * scale * scale > 16_777_216:
            raise PixelError("Export exceeds 16M pixels; reduce scale or split the animation")
        frames = [self.composite(i) for i in indexes]
        bundle={}
        if kind == "png":
            image = self.composite(self.active_frame)
        elif kind == "sheet":
            columns = integer(columns if columns is not None else min(8, len(frames)), "columns", 1, 256)
            rows = math.ceil(len(frames) / columns)
            if self.width * self.height * columns * rows * scale * scale > 16_777_216:
                raise PixelError("Padded sheet exceeds 16M pixels; use fewer columns or a smaller scale")
            image = Image.new("RGBA", (self.width * columns, self.height * rows))
            metadata = []
            for i, cel in enumerate(frames):
                x, y = i % columns * self.width, i // columns * self.height
                image.paste(cel, (x, y))
                metadata.append({"index": i, "source_index": indexes[i], "x": x * scale, "y": y * scale,
                                 "width": self.width * scale, "height": self.height * scale,
                                 "duration_ms": self.durations[indexes[i]]})
            exported_tags = []
            for name, item in self.tags.items():
                covered = [i for i, source in enumerate(indexes) if item["start"] <= source <= item["end"]]
                if covered:
                    exported_tags.append({"name": name, "start": min(covered), "end": max(covered),
                                          "direction": item.get("direction", "forward")})
            data={"image": path.name, "frames": metadata, "tags": exported_tags,
                  "canvas": {"width": self.width, "height": self.height}}
            if sheet_format!='native':
                data=aseprite_data(self,path,metadata,exported_tags,(image.width*scale,image.height*scale),
                                   array=sheet_format=='aseprite_array',tag=tag)
            bundle[path.with_suffix('.json')]=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode('utf-8')
            if sheet_format=='godot':bundle[path.with_suffix('.tres')]=godot_resource(self,path,metadata,tag).encode('utf-8')
        elif kind == "gif":
            # Reserve palette index 0 for transparency, shared by every frame.
            rgb = sorted({p[:3] for cel in frames for p in pixels(cel) if p[3] >= 128})
            if len(rgb) > 255:
                raise PixelError("GIF supports at most 255 opaque colors plus transparency; use PNG sheets for RGBA")
            palette = [0, 0, 0] + [v for color in rgb for v in color]
            palette += [0] * (768 - len(palette))
            lookup = {color: i + 1 for i, color in enumerate(rgb)}
            indexed = []
            for cel in frames:
                p = Image.new("P", cel.size)
                p.putpalette(palette)
                p.putdata([0 if color[3] < 128 else lookup[color[:3]] for color in pixels(cel)])
                indexed.append(p.resize((self.width * scale, self.height * scale), Image.Resampling.NEAREST))
            path.parent.mkdir(parents=True,exist_ok=True)
            indexed[0].save(path, format="GIF", save_all=True, append_images=indexed[1:],
                            duration=[self.durations[index] for index in indexes], transparency=0, disposal=2, optimize=False,
                            **({'loop':0} if loop else {}))
            return {"path": str(path.resolve()), "kind": kind, "frames": len(frames)}
        else:
            raise PixelError("Export kind must be png, sheet, or gif")
        image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
        png=io.BytesIO();image.save(png,format='PNG');bundle[path]=png.getvalue()
        write_bundle(bundle)
        result={"path": str(path.resolve()), "kind": kind, "width": image.width, "height": image.height,
                "frames": len(frames) if kind == "sheet" else 1}
        if sheet_format!='native':
            result.update(sheet_format=sheet_format,metadata_path=str(path.with_suffix('.json').resolve()),
                          files=[str(p.resolve()) for p in outputs])
            if sheet_format=='godot':result['resource_path']=str(path.with_suffix('.tres').resolve())
        return result


OPERATION_GUIDE = {
    "notes": ["Every command is an atomic undoable transaction; a failing operation changes nothing.",
              "Use expected_revision and expected_document_id from state to avoid overwriting newer edits.",
              "Layer order is bottom to top. Frames and palette indexes are zero-based.",
              "All drawing uses integer pixels with no antialiasing. Transparent color is #00000000.",
              "Drawing can be constrained by clip: a named region or [x,y,width,height]. Coordinates stay absolute.",
              "All drawing commands accept layer (stable id or unique name) and frame.",
              "Colors are palette indexes or #RRGGBB[AA]. Strict palette mode rejects unknown colors."],
    "examples": [
        {"op": "layer_add", "name": "eyes", "id": "eyes"},
        {"op": "layer_set", "layer": "eyes", "locked": False, "visible": True, "opacity": 255},
        {"op": "layer_move", "layer": "eyes", "index": 0},
        {"op": "layer_delete", "layer": "eyes"},
        {"op": "select", "layer": "eyes", "frame": 0},
        {"op": "pixel", "x": 10, "y": 10, "color": 22},
        {"op": "stroke", "points": [[1, 1], [2, 2], [5, 2]], "size": 1, "color": 7},
        {"op": "line", "x1": 1, "y1": 2, "x2": 20, "y2": 2, "color": 7},
        {"op": "rect", "x": 2, "y": 2, "width": 20, "height": 10, "color": 18, "filled": True},
        {"op": "ellipse", "x": 2, "y": 2, "width": 20, "height": 10, "color": 22, "filled": False},
        {"op": "fill", "x": 4, "y": 4, "color": 22},
        {"op": "replace", "old_color": 22, "color": 18},
        {"op": "clear"},
        {"op": "translate", "dx": 1, "dy": -1},
        {"op": "flip", "axis": "horizontal"},
        {"op": "outline", "color": 1, "diagonal": False},
        {"op": "dither", "rect": [2, 2, 8, 8], "color": 18, "other_color": 17},
        {"op": "region_define", "name": "face", "rect": [8, 8, 16, 12]},
        {"op": "region_delete", "name": "face"},
        {"op": "stamp_define", "name": "spark", "rows": [".a.", "aaa", ".a."], "colors": {"a": 15}},
        {"op": "stamp", "name": "spark", "x": 2, "y": 2, "scale": 1},
        {"op": "frame_add", "copy_from": 0, "after": 0, "duration_ms": 160},
        {"op": "frame_set", "frame": 0, "duration_ms": 240},
        {"op": "frame_delete", "frame": 1},
        {"op": "palette_add", "colors": ["#f0a05aff"]},
        {"op": "palette_lock", "enabled": True},
        {"op": "rename", "name": "My sprite"},
    ],
}
