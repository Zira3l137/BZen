from dataclasses import dataclass, field
from logging import error, info
from typing import Dict, Optional

from mathutils import Matrix, Vector
from zenkit import VirtualObject, World

from error import Err, Ok, Result
from visual import MeshData, VisualLoader, parse_visual_data


@dataclass(frozen=True, slots=True)
class VobData:
    name: str = field(default_factory=str)
    mesh: Optional[MeshData] = None
    position: Vector = field(default_factory=Vector)
    rotation: Matrix = field(default_factory=Matrix)


def index_vobs(world: World, visuals_cache: Dict[str, VisualLoader]) -> Result[Dict[str, VobData], Exception]:
    try:
        vobs = {}

        def index_obj(obj: VirtualObject, storage: Dict[str, VobData]):
            if len(obj.children):
                for child in obj.children:
                    index_obj(child, storage)
            else:
                storage[obj.name] = VobData(
                    name=obj.name,
                    mesh=parse_visual_data(obj, visuals_cache).unwrap_or_none(),
                    position=Vector([obj.position[i] for i in range(3)]),
                    rotation=Matrix([[column[j] for j in range(3)] for column in obj.rotation.matrix_columns()]),
                )

        for obj in world.root_objects:
            index_obj(obj, vobs)

    except Exception as e:
        error("Failed to index VOBs")
        return Err(e)

    info(f"Indexed {len(vobs)} VOBs")
    return Ok(vobs)
