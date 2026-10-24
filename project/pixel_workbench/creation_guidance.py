"""Task-independent creation guidance served through MCP, without artwork presets."""
from pathlib import Path

from . import __version__
from .workflow import route, WORKFLOW_REVISION

GUIDE_DIR = Path(__file__).with_name("resources")
TOPICS = {
    "workflow": ("CREATION_WORKFLOW.md", "Design, native drawing and iteration"),
    "text_workflow": ("TEXT_WORKFLOW.md", "Description to editable static art"),
    "image_workflow": ("IMAGE_WORKFLOW.md", "Faithful pixel draft and visible-object layers"),
    "completion_workflow": ("COMPLETION_WORKFLOW.md", "Requested hidden-area completion in the original style"),
    "decomposition_workflow": ("DECOMPOSITION_WORKFLOW.md", "Analyze a flattened image before separating and animating it"),
    "animation_workflow": ("ANIMATION_WORKFLOW.md", "Layers, motion planning and clean frames"),
    "inspection_workflow": ("INSPECTION_WORKFLOW.md", "Visual evidence, repairs and delivery"),
    'export':('EXPORT_GUIDE.md','Native/Aseprite sheets and Godot 4 SpriteFrames'),
    'art_direction':('ART_DIRECTION.md','Whole/detail coordination and optional host-generation handoff'),
    'material_workflow':('MATERIAL_WORKFLOW.md','Optional normal editing, local lighting and material previews'),
}
RELATED = {
    'workflow': ('text_workflow', 'image_workflow', 'art_direction'),
    'text_workflow': ('art_direction', 'inspection_workflow'),
    'image_workflow': ('decomposition_workflow', 'inspection_workflow'),
    'decomposition_workflow': ('completion_workflow', 'animation_workflow', 'inspection_workflow'),
    'completion_workflow': ('decomposition_workflow', 'inspection_workflow'),
    'animation_workflow': ('decomposition_workflow', 'inspection_workflow', 'export'),
    'inspection_workflow': ('export',),
    'export': ('inspection_workflow',),
    'art_direction': ('image_workflow', 'material_workflow', 'inspection_workflow'),
    'material_workflow': ('art_direction','inspection_workflow','export'),
}


def workflow_entry(task=None):
    """Keep discovery compact; detailed guidance is fetched explicitly via tools."""
    return {
        "read_next": route(task)['read_next'],
        "routing":route(task),
        "details": [{"tool": "pixel_help", "arguments": {"topic": topic}} for topic in TOPICS if topic != "workflow"],
        "resource": "pixel-loom://workflow",
        "single_image_animation": {
            "when": "Animating a flattened image or an automatic pixel draft with merged body/material parts",
            "read_next": {"tool": "pixel_help", "arguments": {"topic": "decomposition_workflow"}},
            "before_animation": ["inspect source and explain structure/occlusion", "separate visible semantic parts; hidden completion requires a human request",
                                 "inspect each isolated layer", "check restored composite AND trial joint poses"],
            "rule": "Layer count and composite pixel equality do not prove correct decomposition. Repair mixed parts or gaps before building the animation.",
        },
        "stages": [
            "Read current art and the human's task; preserve existing projects.",
            "Select static text/image, local edit, requested completion or requested animation from the human's task.",
            "Static first; check an identity baseline and editable object layers; choose dimensions/colors for the source, not a fixed recipe.",
            "Keep bounded pixel_task progress; read only the relevant guide and changed evidence.",
            "Draw native operations in coherent batches and inspect actual previews.",
            "Only requested animation: check key poses, then transitions/timing; build clean local motion from the retained baseline.",
            "Inspect frames/details/timing/seams; repeated defects need structural diagnosis and fresh evidence, not repeated patches.",
            "Submit specific visual findings, save the editable project and verify final exports.",
        ],
        "capabilities": {
            "vision": "The host AI must actually view returned images to judge appearance. Text metrics alone are insufficient.",
            "computation": "Optional host-side Python/JavaScript can calculate coordinates and native ops. Pixel Loom does not execute arbitrary host code.",
        },
        "scope": "General methods, not finished-art presets. The connected AI designs each task; documentation cannot guarantee every model's artistic quality.",
    }


def workflow_help(topic="workflow"):
    if topic not in TOPICS:
        raise ValueError(f"Unknown creation guide topic: {topic}")
    filename, title = TOPICS[topic]
    return {
        "topic": topic,
        "application_version": __version__,
        "workflow_revision":WORKFLOW_REVISION,
        "title": title,
        "guide": (GUIDE_DIR / filename).read_text(encoding="utf-8"),
        "related": [{"tool": "pixel_help", "arguments": {"topic": other}} for other in RELATED[topic]],
        "operation_help": "pixel_help(operation='<observed operation name>') returns exact current schemas.",
    }


def workflow_resource():
    return {topic: workflow_help(topic) for topic in TOPICS}
