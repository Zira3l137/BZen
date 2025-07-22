import math
from dataclasses import dataclass, field
from logging import error, info, warning
from typing import Dict, Optional

import bpy
from mathutils import Euler, Matrix, Vector
from zenkit import Mat3x3, Vec3f, VirtualObject, World

from error import Err, Ok, Result
from exceptions import UnknownExtensionException, VobHasNoMeshException
from material import create_material
from utils import trim_suffix
from visual import MeshData, VisualLoader, parse_visual_data


@dataclass(frozen=True, slots=True)
class VobData:
    name: str = field(default_factory=str)
    mesh: Optional[MeshData] = None
    position: Vector = field(default_factory=Vector)
    rotation: Euler = field(default_factory=Euler)


def get_vob_euler_rotation(matrix: Mat3x3) -> Euler:
    columns = matrix.columns
    c0, c1, c2 = columns[0], columns[1], columns[2]

    a = (c0.x, c1.x, c2.x)
    b = (c0.z, c1.z, c2.z)
    c = (c0.y, c1.y, c2.y)

    euler = Matrix((a, b, c)).to_euler()
    euler.x = -euler.x + math.radians(90)

    return euler


def get_vob_position(vector: Vec3f, scale: float = 0.01) -> Vector:
    x, y, z = vector
    return Vector((x * scale, z * scale, y * scale))


def index_vobs(
    world: World, visuals_cache: Dict[str, VisualLoader], scale: float = 0.01
) -> Result[Dict[str, VobData], Exception]:
    try:
        vobs = {}

        def index_obj(obj: VirtualObject, storage: Dict[str, VobData]):
            mesh_data = parse_visual_data(obj, visuals_cache)
            if mesh_data.is_certain_err(UnknownExtensionException):
                return

            storage[f"{trim_suffix(obj.visual.name)}_{obj.id}"] = VobData(
                name=obj.name,
                mesh=mesh_data.unwrap(),
                position=get_vob_position(obj.position, scale),
                rotation=get_vob_euler_rotation(obj.rotation),
            )
            if len(obj.children):
                for child in obj.children:
                    index_obj(child, storage)

        for obj in world.root_objects:
            index_obj(obj, vobs)

    except Exception as e:
        error("Failed to index VOBs")
        return Err(e)

    info(f"Indexed {len(vobs)} VOBs")
    return Ok(vobs)


def create_obj_from_mesh(
    unique_name: str, mesh_data: MeshData, textures: Dict[str, str]
) -> Result[bpy.types.Object, Exception]:
    try:
        mesh = bpy.data.meshes.new(unique_name)
        mesh.from_pydata(mesh_data.vertices, [], mesh_data.faces)  # type: ignore
        mesh.normals_split_custom_set(mesh_data.normals)  # type: ignore

        if mesh_data.uvs:
            uv_layer = mesh.uv_layers.new(name="UVMap")
            for i in range(len(uv_layer.data)):
                uv_layer.data[i].uv = mesh_data.uvs[i]

        for material in mesh_data.materials:
            mat = bpy.data.materials.get(material.name)
            if not mat:
                mat = create_material(material, textures).unwrap()
            mesh.materials.append(mat)

        for index, polygon in enumerate(mesh.polygons):
            if not len(mesh_data.materials):
                continue
            polygon.material_index = mesh_data.material_indices[index]

        mesh.update()
        obj = bpy.data.objects.new(unique_name, mesh)
        bpy.context.collection.objects.link(obj)
    except Exception as e:
        error("Failed to create object from mesh")
        return Err(e)

    return Ok(obj)


def create_obj_from_vob_data(
    unique_name: str, vob_data: VobData, textures: Dict[str, str]
) -> Result[bpy.types.Object, Exception]:
    try:
        vob_mesh = vob_data.mesh

        if not vob_mesh:
            return Err(VobHasNoMeshException(f"no mesh for VOB {unique_name}"))

        obj = create_obj_from_mesh(unique_name, vob_mesh, textures).unwrap()
        obj.location = vob_data.position or Vector((0, 0, 0))
        obj.rotation_euler = vob_data.rotation or Euler((0, 0, 0))
    except Exception as e:
        error(f"Failed to create object {unique_name}")
        return Err(e)

    return Ok(obj)


def create_vobs(vobs: Dict[str, VobData], textures: Dict[str, str]) -> Result[None, Exception]:
    try:
        success_count = 0
        for index, (vob_name, vob_data) in enumerate(vobs.items()):
            result = create_obj_from_vob_data(vob_name, vob_data, textures)

            if result.is_certain_err(VobHasNoMeshException):
                warning(f"VOB {vob_name} has no mesh, skipping")
                continue
            else:
                result.unwrap()

            success_count += 1

    except Exception as e:
        error("Failed to create VOBs")
        return Err(e)

    bpy.context.view_layer.update()
    info(f"Created {success_count} VOBs")
    return Ok(None)
