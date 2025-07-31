import math
from logging import error, info
from typing import Dict, Optional, Tuple, cast

from mathutils import Euler, Matrix, Vector
from scene import BlenderObjectData
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
