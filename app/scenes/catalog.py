"""The list of scenes: ids, names and where their code lives.

Importing this module is cheap (no NumPy, no SDL): settings validation and
the remote control's menus use it. Scene classes are imported on first use.
To add a scene, write its module (see docs/SCENES.md) and add one line here.
"""

from __future__ import annotations

import importlib
from typing import NamedTuple


class SceneInfo(NamedTuple):
    id: str
    name: str
    description: str
    target: str            # "module:Class"


SCENES = (
    SceneInfo("galaxy", "Galaxy", "A spiral galaxy turning slowly", "app.scenes.galaxy:GalaxyScene"),
    SceneInfo("nightsky", "Night sky", "Twinkling stars over a horizon",
              "app.scenes.nightsky:NightSkyScene"),
    SceneInfo("nebula", "Nebula", "Drifting clouds of glowing gas", "app.scenes.nebula:NebulaScene"),
    SceneInfo("aurora", "Aurora", "Northern lights over mountains", "app.scenes.aurora:AuroraScene"),
    SceneInfo("solar", "Solar system", "The Sun and planets, not to scale",
              "app.scenes.solar:SolarSystemScene"),
    SceneInfo("meteors", "Meteor shower", "Meteors from one radiant",
              "app.scenes.meteors:MeteorShowerScene"),
    SceneInfo("projector", "Galaxy projector", "Turning nebula and laser stars",
              "app.scenes.projector:ProjectorScene"),
    SceneInfo("minimal", "Minimal", "Sparse dim stars for a dark room",
              "app.scenes.minimal:MinimalScene"),
)

SCENE_IDS = tuple(info.id for info in SCENES)
_BY_ID = {info.id: info for info in SCENES}


def info(scene_id: str) -> SceneInfo:
    return _BY_ID[scene_id]


def name(scene_id: str) -> str:
    found = _BY_ID.get(scene_id)
    return found.name if found else scene_id


def load(scene_id: str):
    """The scene class for ``scene_id`` (imports its module)."""
    module_name, _, class_name = _BY_ID[scene_id].target.partition(":")
    return getattr(importlib.import_module(module_name), class_name)


def neighbour(scene_id: str, step: int) -> str:
    index = SCENE_IDS.index(scene_id) if scene_id in _BY_ID else 0
    return SCENE_IDS[(index + step) % len(SCENE_IDS)]
