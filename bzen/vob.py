from logging import debug, error, info, warning
from typing import Dict, List, Optional, Set, Tuple, cast

from mathutils import Quaternion, Vector
from scene import BlenderObjectData
from utils import insert_unique, trim_suffix
from visual import (MeshData, MissingVisualError, VisualLoader,
                    load_indexed_visual, parse_decal_mesh,
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

VOB_COLLECTION = "VOBs"
"""Top-level collection holding one child collection per VOB type."""

WAYNET_COLLECTION = "Waynet"
WAYPOINTS_COLLECTION = (WAYNET_COLLECTION, "Waypoints")
"""Collection path for waypoints."""

WAYNET_EDGES_COLLECTION = (WAYNET_COLLECTION, "Waynet Edges")
"""Collection path for the mesh that draws the connections between waypoints."""


def vob_collection_path(vob: VirtualObject) -> Tuple[str, ...]:
    """Collection path for a VOB: ("VOBs", "<VOB type name>"), e.g. ("VOBs", "zCVobLight")."""
    return (VOB_COLLECTION, vob.type.name)


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
    Convert a VOB's rotation matrix to a Blender Quaternion.

    The matrix is converted to a quaternion by ZenKit, and its y and z
    components are then swapped, matching the Y/Z swap applied to
    positions: Gothic's coordinate system is left-handed with Y up,
    Blender's is right-handed with Z up. Blender quaternions are ordered
    (w, x, y, z).
    """
    quat = matrix.to_quaternion()
    quat = Quaternion((quat.w, quat.x, quat.z, quat.y))
    return quat


def get_blender_obj_position(vector: Vec3f, scale: float = 0.01) -> Vector:
    """
    Convert a VOB position vector to a Blender position.

    Gothic's coordinate system is left-handed with Y as the vertical axis;
    Blender's is right-handed with Z as the vertical axis. Swapping the Y
    and Z components converts between the two (the swap is also what
    turns left-handed into right-handed).

    This function:
    1. Extracts the x, y, z components from the Vec3f vector.
    2. Swaps the Y and Z components.
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
    get_blender_obj_position (which swaps the Y/Z axes and applies the scale
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
        mrm = cast(MultiResolutionMesh, load_indexed_visual(visuals_cache, vob_visual_name))
        mesh_data = parse_multi_resolution_mesh(mrm, scale)
        if not mesh_data:
            raise ParseMeshError(f'Could not retrieve mesh data for "{vob_name}"')
        mesh_cache[vob_visual_name] = mesh_data

    return blender_obj_name, BlenderObjectData(
        name=vob_name,
        mesh=mesh_data,
        position=get_blender_obj_position(vob.position, scale),
        rotation=get_blender_obj_quaternion_rotation(vob.rotation),
        collection=vob_collection_path(vob),
    )


def get_decal_blender_obj_data(
    vob: VirtualObject, mesh_cache: Dict[str, MeshData], scale: float = 0.01
) -> Tuple[str, BlenderObjectData]:
    """
    Create BlenderObjectData for a decal VOB.

    Decals are textures drawn on a flat quad (blood stains, signs and
    the like). Their visual is a texture, not a mesh, so parse_decal_mesh
    generates the quad from the decal's dimensions.

    The BlenderObjectData's name is a string that identifies the VOB in the
    Blender scene. The format is "{trimmed_visual_name}_{vob.id}" where the
    visual name is trimmed (suffix removed) and lowercased.

    The mesh data is looked up in the mesh_cache (which is built by
    parse_blender_obj_data_from_world and caches mesh data). If the mesh
    is not in the cache, it is parsed using parse_decal_mesh and added to
    the mesh_cache.

    The position is converted from Gothic's coordinate system using
    get_blender_obj_position (which swaps the Y/Z axes and applies the scale
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
        collection=vob_collection_path(vob),
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
    get_blender_obj_position (which swaps the Y/Z axes and applies the scale
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
        collection=vob_collection_path(vob),
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
    get_blender_obj_position (which swaps the Y/Z axes and applies the scale
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
        collection=vob_collection_path(vob),
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

    Any error while parsing a single VOB is logged and that VOB is skipped
    (no BlenderObjectData is created for it); its children are still
    parsed. A missing asset is logged as an error once and at debug level
    for further VOBs needing it. VOBs without a visual are skipped at
    debug level.

    The position is converted from Gothic's coordinate system (left-handed,
    Y up) to Blender's (right-handed, Z up) using get_blender_obj_position
    (which swaps the Y/Z axes and applies the scale factor). The scale
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
    reported_missing: Set[str] = set()
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

            # VOBs without any visual (plain zCVob used as a parent, marker,
            # etc.): nothing to draw. Routine, so only reported at debug level.
            elif vob_visual is None or not vob_visual.name:
                debug(f'VOB "{vob.name}" has no visual, skipping it')

            # Generic VOBs with standard visuals
            else:
                bobj_name, bobj_data = get_generic_blender_obj_data(vob, mesh_cache, visuals_cache, scale)
                blender_objects[bobj_name] = bobj_data

        except ParseMeshError as e:
            error(f"Failed to index VOB {vob.name}: {e.__repr__()}")
        except ParseItemVisualError as e:
            error(f"Failed to index VOB {vob.name}: {e.__repr__()}")
        except MissingVisualError as e:
            # One missing file typically affects many VOBs (e.g. every light when
            # its placeholder mesh is absent); report it once, the rest at debug.
            if e.name not in reported_missing:
                reported_missing.add(e.name)
                error(f'Missing asset "{e.name}": skipping VOB "{vob.name}" and every other VOB that needs it')
            else:
                debug(f'Skipping VOB "{vob.name}": missing asset "{e.name}"')
        except Exception as e:
            # Anything else (e.g. a corrupt file ZenKit cannot read) should cost
            # this one VOB, not the whole conversion. Traceback at -v 3.
            error(f'Unexpected error while indexing VOB "{vob.name}", skipping it: {e!r}')
            debug("Traceback:", exc_info=True)

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
    (which swaps the Y/Z axes and applies the scale factor). The rotation
    is computed from the waypoint's direction vector: the direction is
    converted to a Vector (x, z, y), swapping Y and Z because Gothic's
    vertical axis is Y and Blender's is Z, and then turned into a
    quaternion with to_track_quat("Y", "Z"), which points the object's +Y
    axis along the direction while keeping its +Z axis up.

    The waypoints are named using the waypoint's name (lowercased);
    duplicate names get a ".001"-style suffix (see utils.insert_unique).

    Returns a dictionary mapping waypoint names to BlenderObjectData
    objects. Each BlenderObjectData has the waypoint's position and
    rotation, with the invisible waypoint mesh.

    If the "invisible_zcvobwaypoint.mrm" placeholder mesh is not in the
    visuals cache, an error is logged and an empty dictionary is returned.
    """
    vobs = {}
    waynet = world.way_net
    waypoints = waynet.points

    try:
        wp_mrm = cast(MultiResolutionMesh, load_indexed_visual(visuals_cache, "invisible_zcvobwaypoint.mrm"))
    except MissingVisualError as e:
        error(f"Cannot place waypoints, skipping the waynet: {e}")
        return vobs
    wp_mesh = parse_multi_resolution_mesh(wp_mrm, scale)

    for waypoint in waypoints:
        position = waypoint.position
        direction = waypoint.direction

        target_direction = Vector((direction.x, direction.z, direction.y))
        vob_rotation = target_direction.to_track_quat("Y", "Z")

        vob_position = get_blender_obj_position(position, scale)
        vob_name = waypoint.name.lower()

        insert_unique(
            vobs,
            vob_name,
            BlenderObjectData(
                name=vob_name,
                mesh=wp_mesh,
                position=vob_position,
                rotation=vob_rotation,
                collection=WAYPOINTS_COLLECTION,
            ),
        )

    return vobs


def parse_waynet_edges(world: World, scale: float = 0.01) -> Tuple[List[Vector], List[Tuple[int, int]]]:
    """
    Parse the connections between waypoints of the world's waynet.

    Returns the waypoint positions (converted like the waypoints themselves,
    see get_blender_obj_position) and the edges as index pairs into that
    list, ready to be built into a mesh of loose edges.

    Edges that reference a waypoint that doesn't exist, or connect a
    waypoint to itself, are skipped and counted in a warning.
    """
    waynet = world.way_net
    vertices = [get_blender_obj_position(point.position, scale) for point in waynet.points]
    point_count = len(vertices)

    edges, skipped = [], 0
    for edge in waynet.edges:
        a, b = edge.a, edge.b
        if a == b or not (0 <= a < point_count and 0 <= b < point_count):
            skipped += 1
            continue
        edges.append((a, b))

    if skipped:
        warning(f"Skipped {skipped} invalid waynet edge(s)")
    return vertices, edges


def parse_item_visual_name(obj: VirtualObject, vm: DaedalusVm) -> Optional[str]:
    """
    Resolve the visual name for an item VOB.

    Items are VOBs that reference item visuals from the Daedalus virtual
    machine (the item database in the game). This function resolves the
    visual name from the virtual machine.

    If the item has no visual, the function logs an error and returns
    None. If the item cannot be instantiated (e.g., the item does not
    exist in the item database, so the symbol lookup returns None), the
    resulting AttributeError is caught here and re-raised as a
    ParseItemVisualError.

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
