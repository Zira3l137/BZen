from logging import error, info
from typing import Dict, Optional, Tuple, cast

from mathutils import Quaternion, Vector
from scene import BlenderObjectData
from utils import trim_suffix
from visual import (MeshData, VisualLoader, parse_decal_mesh,
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

"""
Mapping of VOB types to the name of the invisible placeholder mesh used for
that VOB type.

Invisible VOBs (triggers, lights, sounds, zones, etc.) have no actual
mesh in the .zen file. This dictionary maps the VOB type to the name of
an MRM file that provides a mesh for these VOBs. The mesh is loaded
from the visuals cache during VOB parsing.

The mesh name is used to look up the mesh data in the mesh_cache in
parse_blender_obj_data_from_world.
"""


class ParseMeshError(Exception):
    """
    Raised when mesh parsing fails.

    This exception is caught during VOB iteration in
    parse_blender_obj_data_from_world and logged with the VOB name.
    It should only be raised by the mesh parsing functions in this
    module (get_special_blender_obj_data, get_decal_blender_obj_data,
    etc.).
    """
    def __init__(self, message: str):
        super().__init__(message)


class ParseItemVisualError(Exception):
    """
    Raised when an item VOB cannot be resolved to a visual.

    This exception is caught during VOB iteration in
    parse_blender_obj_data_from_world and logged with the VOB name.
    It is raised by get_item_blender_obj_data when the item has no
    visual, or when the visual name cannot be parsed.
    """
    def __init__(self, message: str):
        super().__init__(message)


def get_blender_obj_quaternion_rotation(matrix: Mat3x3) -> Quaternion:
    """
    Convert a Mat3x3 rotation matrix to a Blender Quaternion.

    Mat3x3 uses standard quaternion (x, y, z, w) convention. Blender's
    Quaternion uses (w, x, z, y) — the y and z axes are swapped because
    the VOB rotation is in a different coordinate system than the Blender
    object coordinate system (Y is Y, Z is X, X is Z in the Gothic
    coordinate system, which is right-handed with Y as vertical axis).

    The conversion swaps the y and z components and returns the result.

    The matrix comes from a VOB's rotation field, which represents the
    rotation applied to the VOB's position.
    """
    quat = matrix.to_quaternion()
    quat = Quaternion((quat.w, quat.x, quat.z, quat.y))
    return quat


def get_blender_obj_position(vector: Vec3f, scale: float = 0.01) -> Vector:
    """
    Convert a VOB position vector to a Blender position.

    Gothic's coordinate system (used by Daedalus/VirtualObject) has:
    - Y axis as the vertical axis (up/down)
    - X and Z axes swapped relative to Blender's

    Blender's coordinate system has:
    - Y axis as the vertical axis (up/down)
    - X and Z axes as the horizontal axes (X = left/right, Z = back/front)

    This function:
    1. Extracts the x, y, z components from the Vec3f vector.
    2. Swaps the X and Z components (Blender uses X = horizontal, Z = depth).
    3. Applies the scale factor to convert from centimeters to meters.

    The scale factor (default 0.01) is a hard requirement of the format:
    Gothic stores all linear dimensions in centimeters. Blender uses meters
    by default. The 0.01 factor converts cm to m.

    Returns a Blender Vector (x, y, z) with the converted position.
    """
    x, y, z = vector
    return Vector((x * scale, z * scale, y * scale))


def get_special_blender_obj_data(
    vob: VirtualObject,
    mesh_cache: Dict[str, MeshData],
    visuals_cache: Dict[str, VisualLoader],
    scale: float = 0.01,
) -> Tuple[str, BlenderObjectData]:
    """
    Create BlenderObjectData for an invisible VOB.

    Invisible VOBs (triggers, lights, sounds, zones, etc.) have no actual
    mesh in the .zen file. This function creates a BlenderObjectData with
    a mesh from the visuals cache.

    The mesh is looked up in the mesh_cache (which is built by
    parse_blender_obj_data_from_world and caches mesh data). If the mesh
    is not in the cache, it is loaded from the visuals cache and added to
    the mesh_cache.

    The BlenderObjectData's name is a string that identifies the VOB in the
    Blender scene. The name format depends on the VOB:
    - For named VOBs: "invisible:{vob_name}_{vob.id}"
    - For unnamed VOBs: "invisible:{vob_type.name}_{vob.id}"

    The position is converted from Gothic's coordinate system using
    get_blender_obj_position (which swaps X/Z axes and applies the scale
    factor). The rotation is converted from a Mat3x3 matrix to a Quaternion
    using get_blender_obj_quaternion_rotation (which swaps Y/Z axes).

    Returns a tuple of (blender_obj_name, BlenderObjectData).
    """
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
        rotation=get_blender_obj_quaternion_rotation(vob.rotation),
    )


def get_decal_blender_obj_data(
    vob: VirtualObject, mesh_cache: Dict[str, MeshData], scale: float = 0.01
) -> Tuple[str, BlenderObjectData]:
    """
    Create BlenderObjectData for a decal VOB.

    Decals are decorative objects (e.g., decorative images, textures).
    They have a special visual format (.mdh files) that is parsed using
    parse_decal_mesh, which creates a rectangular mesh from the decal's
    dimensions.

    The BlenderObjectData's name is a string that identifies the VOB in the
    Blender scene. The format is "{trimmed_visual_name}_{vob.id}" where the
    visual name is trimmed (suffix removed) and lowercased.

    The mesh data is looked up in the mesh_cache (which is built by
    parse_blender_obj_data_from_world and caches mesh data). If the mesh
    is not in the cache, it is parsed using parse_decal_mesh and added to
    the mesh_cache.

    The position is converted from Gothic's coordinate system using
    get_blender_obj_position (which swaps X/Z axes and applies the scale
    factor). The rotation is converted from a Mat3x3 matrix to a Quaternion
    using get_blender_obj_quaternion_rotation (which swaps Y/Z axes).

    Returns a tuple of (blender_obj_name, BlenderObjectData).
    """
    blender_obj_name = f"{trim_suffix(vob.visual.name).lower()}_{vob.id}"
    vob_visual_name = vob.visual.name
    mesh_data = None

    if vob_visual_name in mesh_cache:
        mesh_data = mesh_cache[vob_visual_name]
    else:
        mesh_data = parse_decal_mesh(vob, scale)
        if not mesh_data:
            raise ParseMeshError(f'Could not retrieve mesh data for "{blender_obj_name}"')
        mesh_cache[vob_visual_name] = mesh_data

    return blender_obj_name, BlenderObjectData(
        name=vob.name.lower(),
        mesh=mesh_data,
        position=get_blender_obj_position(vob.position, scale),
        rotation=get_blender_obj_quaternion_rotation(vob.rotation),
    )


def get_item_blender_obj_data(
    vob: VirtualObject,
    vm: DaedalusVm,
    mesh_cache: Dict[str, MeshData],
    visuals_cache: Dict[str, VisualLoader],
    scale: float = 0.01,
) -> Tuple[str, BlenderObjectData]:
    """
    Create BlenderObjectData for an item VOB.

    Items are VOBs that reference item visuals from the Daedalus virtual
    machine (the item database in the game). This function:
    1. Resolves the item's visual name from the Daedalus virtual machine
       using the item's name and type.
    2. Parses the visual using parse_visual_data (which handles the
       compiled format).
    3. Creates a BlenderObjectData with the mesh data.

    The BlenderObjectData's name is a string that identifies the VOB in the
    Blender scene. The format is "{trimmed_visual_name}_{vob.id}" where the
    visual name is trimmed (suffix removed) and lowercased.

    The mesh data is looked up in the mesh_cache (which is built by
    parse_blender_obj_data_from_world and caches mesh data). If the mesh
    is not in the cache, it is parsed using parse_visual_data and added to
    the mesh_cache.

    The position is converted from Gothic's coordinate system using
    get_blender_obj_position (which swaps X/Z axes and applies the scale
    factor). The rotation is converted from a Mat3x3 matrix to a Quaternion
    using get_blender_obj_quaternion_rotation (which swaps Y/Z axes).

    Returns a tuple of (blender_obj_name, BlenderObjectData). Raises
    ParseItemVisualError if the item has no visual or the visual name
    cannot be resolved.
    """
    item_visual_name = parse_item_visual_name(vob, vm)
    if not item_visual_name:
        raise ParseItemVisualError(f"Item {vob.name} has no visual")

    blender_obj_name = f"{trim_suffix(item_visual_name).lower()}_{vob.id}"
    mesh_data = None

    if item_visual_name in mesh_cache:
        mesh_data = mesh_cache[item_visual_name]
    else:
        mesh_data = parse_visual_data(item_visual_name, visuals_cache, scale)
        if not mesh_data:
            raise ParseMeshError(f'Could not retrieve mesh data for "{blender_obj_name}"')
        mesh_cache[item_visual_name] = mesh_data

    return blender_obj_name, BlenderObjectData(
        name=vob.name.lower(),
        mesh=mesh_data,
        position=get_blender_obj_position(vob.position, scale),
        rotation=get_blender_obj_quaternion_rotation(vob.rotation),
    )


def get_generic_blender_obj_data(
    vob: VirtualObject,
    mesh_cache: Dict[str, MeshData],
    visuals_cache: Dict[str, VisualLoader],
    scale: float = 0.01,
) -> Tuple[str, BlenderObjectData]:
    """
    Create BlenderObjectData for a generic VOB.

    Generic VOBs are VOBs that don't fall into any of the other categories
    (invisible, decal, item) but still have visuals. This function
    parses the visual using parse_visual_data_from_vob (which handles
    the compiled format) and creates a BlenderObjectData.

    The BlenderObjectData's name is a string that identifies the VOB in the
    Blender scene. The format is "{trimmed_visual_name}_{vob.id}" where the
    visual name is trimmed (suffix removed) and lowercased.

    The mesh data is looked up in the mesh_cache (which is built by
    parse_blender_obj_data_from_world and caches mesh data). If the mesh
    is not in the cache, it is parsed using parse_visual_data_from_vob
    and added to the mesh_cache.

    The position is converted from Gothic's coordinate system using
    get_blender_obj_position (which swaps X/Z axes and applies the scale
    factor). The rotation is converted from a Mat3x3 matrix to a Quaternion
    using get_blender_obj_quaternion_rotation (which swaps Y/Z axes).

    Returns a tuple of (blender_obj_name, BlenderObjectData).
    """
    if vob.visual is None:
        raise ParseMeshError(f'VOB "{vob.name}" has no visual')

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
        rotation=get_blender_obj_quaternion_rotation(vob.rotation),
    )


def parse_blender_obj_data_from_world(
    world: World,
    vm: DaedalusVm,
    visuals_cache: Dict[str, VisualLoader],
    scale: float = 0.01,
) -> Dict[str, BlenderObjectData]:
    """
    Parse BlenderObjectData for all VOBs in a world.

    This function is the entry point for VOB parsing. It iterates all
    VOBs in the world tree (recursively) and creates BlenderObjectData
    for each one. The BlenderObjectData contains the VOB's name, mesh
    data, position, and rotation.

    The function uses a stack to iterate VOBs recursively. For each VOB:
    1. The VOB type determines how it is parsed (invisible, decal, item,
       or generic).
    2. The mesh data is looked up in the mesh_cache (which is shared
       across VOBs to cache parsed mesh data).
    3. If the mesh is not in the cache, the VOB's visual is parsed
       (depending on the VOB type) and added to the mesh_cache.

    The function catches ParseMeshError and ParseItemVisualError
    exceptions and logs the error. If an error is caught, the VOB is
    skipped (no BlenderObjectData is created for it).

    The position is converted from Gothic's coordinate system (which
    has Y as the vertical axis and X/Z swapped) to Blender's coordinate
    system (which has Y as the vertical axis and X/Z as the horizontal
    axes). The conversion is done using get_blender_obj_position
    (which swaps X/Z axes and applies the scale factor). The scale
    factor (default 0.01) is a hard requirement of the format: Gothic
    stores all linear dimensions in centimeters.

    The rotation is converted from a Mat3x3 matrix to a Quaternion using
    get_blender_obj_quaternion_rotation (which swaps Y/Z axes).

    Returns a dictionary mapping BlenderObjectData names to
    BlenderObjectData objects. The dictionary keys are the names used
    to identify the Blender objects in the Blender scene.
    """
    blender_objects: Dict[str, BlenderObjectData] = {}
    mesh_cache: Dict[str, MeshData] = {}
    stack = world.root_objects

    while stack:
        vob = stack.pop()
        vob_type = vob.type
        vob_visual = vob.visual  # ZenKit returns None for VOBs without a visual
        vob_visual_type = vob_visual.type if vob_visual is not None else None

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
        except ParseItemVisualError as e:
            error(f"Failed to index VOB {vob.name}: {e.__repr__()}")

        # Traverse children
        if vob.children:
            stack.extend(vob.children)

    info(f"Indexed {len(blender_objects)} VOBs")
    return blender_objects


def parse_waynet(
    world: World, visuals_cache: Dict[str, VisualLoader], scale: float = 0.01
) -> Dict[str, BlenderObjectData]:
    """
    Parse the waynet for the given world.

    The waynet is a graph of waypoints used by NPCs to navigate the
    world. This function creates BlenderObjectData for each waypoint
    in the waynet, using the invisible waypoint mesh from the visuals
    cache.

    For each waypoint, the position is converted from Gothic's coordinate
    system to Blender's coordinate system using get_blender_obj_position
    (which swaps X/Z axes and applies the scale factor). The rotation is
    computed from the waypoint's direction vector: the direction is
    converted to a Vector (x, z, y) — swapping the Y and Z axes because
    Gothic's Y is the vertical axis and Blender's Y is the vertical
    axis — and then converted to a quaternion using the to_track_quat
    method with "Y" and "Z" axes (which creates a quaternion that rotates
    around the Y axis to reach the direction, in the Z plane).

    The waypoints are named using the waypoint's name (lowercased).

    Returns a dictionary mapping waypoint names to BlenderObjectData
    objects. Each BlenderObjectData has the waypoint's position and
    rotation, with the invisible waypoint mesh.

    Raises KeyError if the "invisible_zcvobwaypoint.mrm" file does not
    exist in the visuals cache.
    """
    vobs = {}
    waynet = world.way_net
    waypoints = waynet.points

    wp_mrm = cast(MultiResolutionMesh, visuals_cache["invisible_zcvobwaypoint.mrm"]())
    wp_mesh = parse_multi_resolution_mesh(wp_mrm, scale)

    for waypoint in waypoints:
        position = waypoint.position
        direction = waypoint.direction

        target_direction = Vector((direction.x, direction.z, direction.y))
        vob_rotation = target_direction.to_track_quat("Y", "Z")

        vob_position = get_blender_obj_position(position, scale)
        vob_name = waypoint.name.lower()

        vobs[vob_name] = BlenderObjectData(
            name=vob_name,
            mesh=wp_mesh,
            position=vob_position,
            rotation=vob_rotation,
        )

    return vobs


def parse_item_visual_name(obj: VirtualObject, vm: DaedalusVm) -> Optional[str]:
    """
    Resolve the visual name for an item VOB.

    Items are VOBs that reference item visuals from the Daedalus virtual
    machine (the item database in the game). This function resolves the
    visual name from the virtual machine.

    If the item has no visual, the function logs an error and returns
    None. If the item cannot be instantiated (e.g., the item does not
    exist in the item database), an AttributeError is raised, which
    is caught by the caller and re-raised as a ParseItemVisualError.

    Returns the visual name (a string) or None if the item has no
    visual.
    """
    try:
        item: ItemInstance = vm.init_instance(obj.name, DaedalusInstanceType.ITEM)  # type: ignore

        item_visual = item.visual
        if not item_visual:
            error(f"Item {obj.name} has no visual")
            return None

    except AttributeError as e:
        raise ParseItemVisualError(f"Failed to get visual for {obj.name}: {e.__repr__()}")

    return item_visual
