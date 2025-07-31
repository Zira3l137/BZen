import math
from dataclasses import dataclass, field
from logging import error, info, warning
from typing import Dict, Optional, Tuple, cast

import bpy
from material import create_material
from mathutils import Euler, Matrix, Vector
from utils import trim_suffix
from visual import (MeshData, VisualLoader, parse_decal,
                    parse_multi_resolution_mesh, parse_visual_data,
                    parse_visual_data_from_vob)
from zenkit import (DaedalusInstanceType, DaedalusVm, ItemInstance, Mat3x3,
                    MultiResolutionMesh, Vec3f, VirtualObject, VisualType,
                    VobType, World)

invisible_vob = {
    VobType.zCVobStartpoint: "invisible_zcvobstartpoint.mrm",
    VobType.zCVobSpot: "invisible_zcvobspot.mrm",
    VobType.zCTrigger: "invisible_zctrigger.mrm",
    VobType.zCTriggerList: "invisible_zctrigger.mrm",
    VobType.oCTriggerScript: "invisible_zctrigger.mrm",
    VobType.oCTriggerChangeLevel: "invisible_zctriggerchangelevel.mrm",
    VobType.zCCodeMaster: "invisible_zccodemaster.mrm",
    VobType.zCMessageFilter: "invisible_zccodemaster.mrm",
    VobType.zCMoverController: "invisible_zccodemaster.mrm",
    VobType.zCTriggerWorldStart: "invisible_zccodemaster.mrm",
    VobType.zCVobLight: "invisible_zcvoblight.mrm",
    VobType.zCVobSound: "invisible_zcvobsound.mrm",
    VobType.zCVobSoundDaytime: "invisible_zcvobsounddaytime.mrm",
    VobType.oCZoneMusic: "invisible_zczonemusic.mrm",
    VobType.oCZoneMusicDefault: "invisible_zczonemusic.mrm",
    VobType.zCZoneZFog: "invisible_zczonezfog.mrm",
    VobType.zCZoneZFogDefault: "invisible_zczonezfog.mrm",
}


class ParseMeshError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class BlenderObjectData:
    name: str = field(default_factory=str)
    mesh: Optional[MeshData] = None
    position: Vector = field(default_factory=Vector)
    rotation: Euler = field(default_factory=Euler)


def get_blender_obj_euler_rotation(matrix: Mat3x3) -> Euler:
    columns = matrix.columns
    c0, c1, c2 = columns[0], columns[1], columns[2]

    a = (c0.x, c1.x, c2.x)
    b = (c0.z, c1.z, c2.z)
    c = (c0.y, c1.y, c2.y)

    euler = Matrix((a, b, c)).to_euler()
    euler.x = -euler.x + math.radians(90)

    return euler


def get_blender_obj_position(vector: Vec3f, scale: float = 0.01) -> Vector:
    x, y, z = vector
    return Vector((x * scale, z * scale, y * scale))


def get_special_blender_obj_data(
    vob: VirtualObject,
    mesh_cache: Dict[str, MeshData],
    visuals_cache: Dict[str, VisualLoader],
    scale: float = 0.01,
) -> Tuple[str, BlenderObjectData]:
    vob_name = vob.name.lower()
    vob_type = vob.type

    if vob_type not in invisible_vob:
        raise ValueError(f"Unknown invisible vob type: {vob_type}")

    vob_visual_name = invisible_vob[vob_type]
    blender_obj_name = f"invisible:{vob_name}_{vob.id}" if vob_name else f"invisible:{vob_type.name}_{vob.id}"
    mesh_data = None

    if vob_visual_name in mesh_cache:
        mesh_data = mesh_cache[vob_visual_name]
    else:
        mrm = cast(MultiResolutionMesh, visuals_cache[vob_visual_name]())
        mesh_data = parse_multi_resolution_mesh(mrm, scale)
        if not mesh_data:
            raise ParseMeshError(f'Could not retrieve mesh data for "{vob_name}"')
        mesh_cache[vob_visual_name] = mesh_data

    return blender_obj_name, BlenderObjectData(
        name=vob_name,
        mesh=mesh_data,
        position=get_blender_obj_position(vob.position, scale),
        rotation=get_blender_obj_euler_rotation(vob.rotation),
    )


def get_decal_blender_obj_data(
    vob: VirtualObject, mesh_cache: Dict[str, MeshData], scale: float = 0.01
) -> Tuple[str, BlenderObjectData]:
    blender_obj_name = f"{trim_suffix(vob.visual.name).lower()}_{vob.id}"
    vob_visual_name = vob.visual.name
    mesh_data = None

    if vob_visual_name in mesh_cache:
        mesh_data = mesh_cache[vob_visual_name]
    else:
        mesh_data = parse_decal(vob, scale)
        if not mesh_data:
            raise ParseMeshError(f'Could not retrieve mesh data for "{blender_obj_name}"')
        mesh_cache[vob_visual_name] = mesh_data

    return blender_obj_name, BlenderObjectData(
        name=vob.name.lower(),
        mesh=mesh_data,
        position=get_blender_obj_position(vob.position, scale),
        rotation=get_blender_obj_euler_rotation(vob.rotation),
    )


def get_item_blender_obj_data(
    vob: VirtualObject,
    vm: DaedalusVm,
    mesh_cache: Dict[str, MeshData],
    visuals_cache: Dict[str, VisualLoader],
    scale: float = 0.01,
) -> Tuple[str, BlenderObjectData]:
    item_visual_name = parse_item_visual_name(vob, vm)
    if not item_visual_name:
        raise Exception(f"Item {vob.name} has no visual")
    item_visual_name = item_visual_name.lower()

    blender_obj_name = f"{trim_suffix(item_visual_name).lower()}_{vob.id}"
    vob_visual_name = vob.visual.name
    mesh_data = None

    if vob_visual_name in mesh_cache:
        mesh_data = mesh_cache[vob_visual_name]
    else:
        mesh_data = parse_visual_data(item_visual_name, visuals_cache, scale)
        if not mesh_data:
            raise ParseMeshError(f'Could not retrieve mesh data for "{blender_obj_name}"')
        mesh_cache[vob_visual_name] = mesh_data

    return blender_obj_name, BlenderObjectData(
        name=vob.name.lower(),
        mesh=mesh_data,
        position=get_blender_obj_position(vob.position, scale),
        rotation=get_blender_obj_euler_rotation(vob.rotation),
    )


def get_generic_blender_obj_data(
    vob: VirtualObject,
    mesh_cache: Dict[str, MeshData],
    visuals_cache: Dict[str, VisualLoader],
    scale: float = 0.01,
) -> Tuple[str, BlenderObjectData]:
    vob_visual_name = vob.visual.name
    blender_obj_name = f"{trim_suffix(vob_visual_name).lower()}_{vob.id}"
    mesh_data = None

    if vob_visual_name in mesh_cache:
        mesh_data = mesh_cache[vob_visual_name]
    else:
        mesh_data = parse_visual_data_from_vob(vob, visuals_cache, scale)
        if not mesh_data:
            raise ParseMeshError(f'Could not retrieve mesh data for "{blender_obj_name}"')
        mesh_cache[vob_visual_name] = mesh_data

    return blender_obj_name, BlenderObjectData(
        name=vob.name.lower(),
        mesh=mesh_data,
        position=get_blender_obj_position(vob.position, scale),
        rotation=get_blender_obj_euler_rotation(vob.rotation),
    )


def parse_blender_obj_data_from_world(
    world: World,
    vm: DaedalusVm,
    visuals_cache: Dict[str, VisualLoader],
    scale: float = 0.01,
) -> Dict[str, BlenderObjectData]:
    try:
        blender_objects: Dict[str, BlenderObjectData] = {}
        mesh_cache: Dict[str, MeshData] = {}
        stack = world.root_objects
        count = 0

        while stack:
            vob = stack.pop()
            vob_type = vob.type
            vob_visual_type = vob.visual.type

            try:
                # Skip level mesh
                if vob_type is VobType.zCVobLevelCompo or vob_visual_type is VisualType.PARTICLE_EFFECT:
                    stack.extend(vob.children)
                    continue

                # Invisible VOBs
                if vob_type in invisible_vob:
                    bobj_name, bobj_data = get_special_blender_obj_data(vob, mesh_cache, visuals_cache, scale)
                    blender_objects[bobj_name] = bobj_data

                # Decals
                elif vob_visual_type is VisualType.DECAL:
                    bobj_name, bobj_data = get_decal_blender_obj_data(vob, mesh_cache, scale)
                    blender_objects[bobj_name] = bobj_data

                # Items
                elif vob_type is VobType.oCItem:
                    bobj_name, bobj_data = get_item_blender_obj_data(vob, vm, mesh_cache, visuals_cache, scale)
                    blender_objects[bobj_name] = bobj_data

                # Generic VOBs with standard visuals
                else:
                    bobj_name, bobj_data = get_generic_blender_obj_data(vob, mesh_cache, visuals_cache, scale)
                    blender_objects[bobj_name] = bobj_data

            except ParseMeshError as e:
                error(f"Failed to index VOB {vob.name}: {e.__repr__()}")

            # Traverse children
            if vob.children:
                stack.extend(vob.children)

            count += 1

    except Exception as e:
        error("Failed to index VOBs")
        raise e

    info(f"Indexed {len(blender_objects)} VOBs")
    return blender_objects


def parse_waynet(
    world: World, visuals_cache: Dict[str, VisualLoader], scale: float = 0.01
) -> Dict[str, BlenderObjectData]:
    try:
        vobs = {}
        waynet = world.way_net
        waypoints = waynet.points

        wp_mrm = cast(MultiResolutionMesh, visuals_cache["invisible_zcvobwaypoint.mrm"]())
        wp_mesh = parse_multi_resolution_mesh(wp_mrm, scale)

        for waypoint in waypoints:
            position = waypoint.position
            direction = waypoint.direction

            target_direction = Vector((direction.x, direction.z, direction.y))
            quat = target_direction.to_track_quat("Y", "Z")
            vob_rotation = quat.to_euler()

            vob_position = get_blender_obj_position(position, scale)
            vob_name = waypoint.name.lower()

            vobs[vob_name] = BlenderObjectData(
                name=vob_name,
                mesh=wp_mesh,
                position=vob_position,
                rotation=vob_rotation,
            )

    except Exception as e:
        error("Failed to index Waynet")
        raise e

    return vobs


def parse_item_visual_name(obj: VirtualObject, vm: DaedalusVm) -> Optional[str]:
    try:
        item: ItemInstance = vm.init_instance(obj.name, DaedalusInstanceType.ITEM)  # type: ignore

        item_visual = item.visual
        if not item_visual:
            error(f"Item {obj.name} has no visual")
            return None

    except Exception as e:
        error("Failed to parse item visual")
        raise e

    return item_visual


def create_obj_from_mesh(unique_name: str, mesh_data: MeshData, textures: Dict[str, str]) -> bpy.types.Object:
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
                mat = create_material(material, textures)
            mesh.materials.append(mat)

        for index, polygon in enumerate(mesh.polygons):
            if not len(mesh_data.materials):
                warning("Mesh has no materials")
                continue

            polygon.material_index = mesh_data.material_indices[index]

        mesh.update()

        obj = bpy.data.objects.new(unique_name, mesh)
        bpy.context.collection.objects.link(obj)
    except Exception as e:
        error("Failed to create object from mesh")
        raise e

    return obj


def create_obj_from_vob_data(
    unique_name: str, vob_data: BlenderObjectData, textures: Dict[str, str]
) -> Optional[bpy.types.Object]:
    try:
        vob_mesh = vob_data.mesh

        if not vob_mesh:
            error(f"VOB {unique_name} has no mesh, skipping")
            return None

        obj = create_obj_from_mesh(unique_name, vob_mesh, textures)
        obj.location = vob_data.position or Vector((0, 0, 0))
        obj.rotation_euler = vob_data.rotation or Euler((0, 0, 0))
    except Exception as e:
        error(f"Failed to create object {unique_name}")
        raise e

    return obj


def create_instance_from_vob_data(
    unique_name: str, obj: bpy.types.Object, vob_data: BlenderObjectData
) -> bpy.types.Object:
    try:
        instance = bpy.data.objects.new(unique_name, obj.data)
        instance.location = vob_data.position or Vector((0, 0, 0))
        instance.rotation_euler = vob_data.rotation or Euler((0, 0, 0))

        bpy.context.collection.objects.link(instance)
    except Exception as e:
        error(f"Failed to create instance {unique_name}")
        raise e

    return instance


def create_vobs(vobs: Dict[str, BlenderObjectData], textures: Dict[str, str]):
    try:
        success_count = 0
        mesh_cache = set()
        obj_cache = {}

        for vob_name, vob_data in vobs.items():
            mesh_hash = hash(vob_data.mesh)
            result = None

            if mesh_hash in mesh_cache:
                existing_obj = obj_cache[mesh_hash]
                result = create_instance_from_vob_data(vob_name, existing_obj, vob_data)
            else:
                result = create_obj_from_vob_data(vob_name, vob_data, textures)
                if not result:
                    warning(f"VOB {vob_name} has no mesh, skipping")
                    continue

                mesh_cache.add(mesh_hash)
                obj_cache[mesh_hash] = result

            success_count += 1

    except Exception as e:
        error("Failed to create VOBs")
        raise e

    bpy.context.view_layer.update()
    info(f"Created {success_count} VOBs")
