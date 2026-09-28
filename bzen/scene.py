from dataclasses import dataclass, field
from logging import error, info, warning
from typing import Dict, List, Optional, Tuple

import bpy
import numpy as np  # numpy is bundled with Blender
from mathutils import Quaternion, Vector
from visual import MaterialData, MeshData, VisualLoader, animated_texture_frames
from zenkit import Texture


"""
Data model for Blender objects created from ZenKit VOBs.

This is a frozen dataclass with slots (memory-efficient, immutable).
Used to pass parsed VOB data through the conversion pipeline to
the Blender object creation functions.

The mesh data is computed during VOB parsing; position and
rotation are also computed at parse time so that the create_*
functions can construct Blender objects without additional
transform math.

``collection`` is the path of nested collections the object is put in,
e.g. ("VOBs", "zCVobLight"); an empty path means the context collection.
"""


@dataclass(frozen=True, slots=True)
class BlenderObjectData:
    name: str = field(default_factory=str)
    mesh: Optional[MeshData] = None
    position: Vector = field(default_factory=Vector)
    rotation: Quaternion = field(default_factory=Quaternion)
    collection: Tuple[str, ...] = ()


COLLECTION_KEY = "bzen_collection"
"""
Custom property that stores the name BZen asked for on every collection it
creates. Blender renames a new collection ("VOBs.001") when another
datablock already has the name, so lookups go by this property instead of
by the (possibly renamed) collection name.
"""


def ensure_collection(path: Tuple[str, ...]) -> bpy.types.Collection:
    """
    Return the collection at ``path`` below the scene's root collection,
    creating any missing collection along the way.

    ``path`` is a tuple of names, e.g. ("VOBs", "zCVobLight"). An empty
    path returns the scene's root collection.
    """
    collection = bpy.context.scene.collection
    for name in path:
        child = next((c for c in collection.children if c.get(COLLECTION_KEY) == name), None)
        if child is None:
            child = bpy.data.collections.new(name)
            child[COLLECTION_KEY] = name
            collection.children.link(child)
        collection = child
    return collection


MaterialKey = Tuple[str, Tuple[float, float, float, float], Optional[str], float, Tuple[float, float]]

_material_cache: Dict[MaterialKey, bpy.types.Material] = {}
"""
Blender materials created so far, keyed by everything that defines them
(name, color, texture, texture animation) rather than by name alone. Gothic meshes can use the
same material name with different textures or colors; keying by name made
all of them share whichever variant was created first. When a second variant
is created, Blender gives it a unique name ("NAME.001").
"""


def _material_key(material: MaterialData) -> MaterialKey:
    texture = material.texture.lower() if material.texture else None
    return (
        material.name,
        tuple(material.color),  # type: ignore[arg-type]
        texture,
        material.texture_anim_fps,
        tuple(material.uv_scroll),  # type: ignore[arg-type]
    )


def create_texture(name: str, texture: Texture) -> bpy.types.Image:
    """
    Convert a ZenKit Texture into a Blender image asset.

    ZenKit returns the pixels as uint8 RGBA (0-255) rows starting at the
    top-left. Blender expects float RGBA (0-1) rows starting at the
    bottom-left, as one flat array. This function:

    1. Extracts the RGBA buffer of the largest mipmap level (uint8).
    2. Converts to float32 and normalizes to [0, 1] range.
    3. Reshapes to rows and flips vertically (top-left -> bottom-left).
    4. Creates and packs the Blender image.

    Texture packing embeds the image data directly into the .blend file,
    eliminating external file dependencies at runtime.

    This is called only when a material references a texture for which no
    Blender image exists yet.
    """
    img_bytes = texture.mipmap_rgba(0)
    width, height = texture.width, texture.height

    pixels = np.frombuffer(bytes(img_bytes), dtype=np.uint8).astype(np.float32) / 255.0
    pixels = pixels.reshape((height, width, 4))
    pixels = np.flipud(pixels)  # Blender's pixel origin is bottom-left

    img = bpy.data.images.new(name, width=width, height=height, alpha=True)
    img.pixels.foreach_set(pixels.ravel())
    img.pack()

    return img


def create_material(material: MaterialData, visuals_cache: Dict[str, VisualLoader]) -> bpy.types.Material:
    """
    Create a Blender material for a VOB material definition.

    Materials are cached in _material_cache, keyed by name, color and
    texture, so meshes that use an identical material share one Blender
    material, while same-named materials that differ get their own.

    The material is built using Blender's node system: the texture color
    feeds a Diffuse BSDF, and the texture alpha drives a Mix Shader between
    a Transparent BSDF (alpha 0) and the diffuse (alpha 1), which goes to
    the Material Output. The alpha passes through an Invert node whose
    factor is 0, i.e. it is not inverted.

    If the material has no texture, a simple diffuse color material is
    created without the node graph.
    """
    key = _material_key(material)
    if (cached := _material_cache.get(key)) is not None:
        try:
            cached.name  # raises ReferenceError if the material was deleted since
            return cached
        except ReferenceError:
            del _material_cache[key]

    bmat = _build_material(material, visuals_cache)
    _material_cache[key] = bmat
    return bmat


def _build_material(material: MaterialData, visuals_cache: Dict[str, VisualLoader]) -> bpy.types.Material:
    """Create a new Blender material for ``material``; see create_material."""
    if not material.texture:
        bmat = bpy.data.materials.new(name=material.name)
        bmat.diffuse_color = material.color
        return bmat

    bmat = bpy.data.materials.new(name=material.name)
    # Before Blender 5.0 a new material has no node tree until use_nodes is
    # enabled. From 5.0 on materials always use nodes and use_nodes is
    # deprecated (to be removed in 6.0), so only touch it when needed.
    if bmat.node_tree is None:
        bmat.use_nodes = True
    bmat.use_backface_culling = True
    # Legacy EEVEE (< 4.2) settings for alpha-clipped textures. EEVEE Next
    # (4.2+) ignores them and handles transparency through the node tree
    # below; set them only while Blender still has them.
    for attribute in ("blend_method", "shadow_method"):
        if hasattr(bmat, attribute):
            setattr(bmat, attribute, "CLIP")

    nodes = bmat.node_tree.nodes
    links = bmat.node_tree.links
    nodes.clear()

    invert_node = nodes.new("ShaderNodeInvert")
    diffuse_node = nodes.new("ShaderNodeBsdfDiffuse")
    mix_shader = nodes.new("ShaderNodeMixShader")
    output_node = nodes.new("ShaderNodeOutputMaterial")

    invert_node.location = (-600, -100)
    diffuse_node.location = (-400, 0)
    mix_shader.location = (-200, 0)
    output_node.location = (200, 0)

    # A missing texture still gets an (empty) image node, as before.
    frames = animated_texture_frames(material.texture, visuals_cache) or [material.texture.lower()]
    images = [_load_texture_image(frame, material, visuals_cache) for frame in frames]
    if len(images) == 1:
        texture_node = nodes.new("ShaderNodeTexImage")
        texture_node.location = (-800, 0)
        texture_node.image = images[0]  # type: ignore
        color_socket, alpha_socket = texture_node.outputs["Color"], texture_node.outputs["Alpha"]
    else:
        color_socket, alpha_socket = _build_frame_selector(bmat.node_tree, images, material.texture_anim_fps)

    diffuse_node.inputs["Roughness"].default_value = 1.0  # type: ignore
    bmat.diffuse_color = material.color

    links.new(color_socket, diffuse_node.inputs["Color"])
    links.new(alpha_socket, invert_node.inputs["Color"])
    links.new(invert_node.outputs["Color"], mix_shader.inputs["Fac"])
    links.new(diffuse_node.outputs["BSDF"], mix_shader.inputs[2])
    links.new(mix_shader.outputs["Shader"], output_node.inputs["Surface"])

    transparent_shader = nodes.new("ShaderNodeBsdfTransparent")
    transparent_shader.location = (-400, -200)
    invert_node.inputs[0].default_value = 0.0  # type: ignore
    links.new(transparent_shader.outputs["BSDF"], mix_shader.inputs[1])

    return bmat


def _load_texture_image(
    texture_name: str, material: MaterialData, visuals_cache: Dict[str, VisualLoader]
) -> Optional[bpy.types.Image]:
    """
    Return the Blender image for ``texture_name``, creating it on first use.
    Returns None if the texture is not in the game data or cannot be read.
    """
    texture_obj = visuals_cache.get(texture_name)
    if not texture_obj:
        return None
    try:
        return bpy.data.images.get(texture_name) or create_texture(texture_name, texture_obj())  # type: ignore
    except Exception as e:
        # A texture that can't be read shouldn't abort the conversion; the
        # material is still created, just without an image.
        warning(f'Could not load texture "{texture_name}" for material "{material.name}": {e!r}')
        return None


TIME_GROUP_KEY = "bzen_time"
"""Custom property marking the shared node group that outputs scene time."""


def _time_node_group() -> bpy.types.NodeTree:
    """
    Return the shared "BZen Time" shader node group, creating it on first use.

    Its single output, Seconds, is the current scene time in seconds,
    computed by a driver from the frame number and the scene's frame rate
    (frame * fps_base / fps). Every animated material uses this one group,
    so the whole file has a single driver, and changing the scene frame
    rate keeps texture animations at their in-game speed. The expression
    is a "simple expression", which Blender evaluates without Python, so
    it works even when auto-running scripts is disabled.
    """
    for group in bpy.data.node_groups:
        if group.get(TIME_GROUP_KEY):
            return group

    group = bpy.data.node_groups.new("BZen Time", "ShaderNodeTree")
    group[TIME_GROUP_KEY] = True
    group.interface.new_socket(name="Seconds", in_out="OUTPUT", socket_type="NodeSocketFloat")
    output = group.nodes.new("NodeGroupOutput")
    value = group.nodes.new("ShaderNodeValue")
    value.label = "Scene time (s)"
    value.location, output.location = (-200, 0), (0, 0)
    group.links.new(value.outputs[0], output.inputs[0])

    driver = value.outputs[0].driver_add("default_value").driver
    driver.type = "SCRIPTED"
    for name, data_path in (("fps", "render.fps"), ("fps_base", "render.fps_base")):
        variable = driver.variables.new()
        variable.name = name
        variable.type = "SINGLE_PROP"
        variable.targets[0].id_type = "SCENE"
        variable.targets[0].id = bpy.context.scene
        variable.targets[0].data_path = data_path
    driver.expression = "frame * fps_base / fps"
    return group


def _socket(sockets, identifier: str):
    """Look a node socket up by its identifier (names repeat on Mix nodes)."""
    return next(socket for socket in sockets if socket.identifier == identifier)


def _math(nodes, links, operation: str, a, b=None, location=(0, 0)):
    """Add a Math node computing ``operation`` of a and b (sockets or numbers)."""
    node = nodes.new("ShaderNodeMath")
    node.operation = operation
    node.location = location
    for index, value in enumerate((a, b)):
        if value is None:
            continue
        if isinstance(value, (int, float)):
            node.inputs[index].default_value = value
        else:
            links.new(value, node.inputs[index])
    return node.outputs[0]


def _build_frame_selector(node_tree: bpy.types.NodeTree, images, fps: float):
    """
    Build the nodes that show one of ``images`` depending on the scene time.

    Frame index = floor(seconds * fps) mod frame count, as in the game:
    frames switch without blending. When the material's fps is 0, the game
    plays one full cycle per second, i.e. uses the frame count as fps.

    Each frame is its own packed image node (Blender cannot pack image
    sequences). Starting from frame 0, a chain of Mix nodes swaps in frame
    i once the index reaches i, separately for color and alpha.

    Returns the (color, alpha) output sockets to use instead of a single
    image node's outputs.
    """
    nodes, links = node_tree.nodes, node_tree.links
    count = len(images)
    fps = fps if fps > 0 else float(count)

    time = nodes.new("ShaderNodeGroup")
    time.node_tree = _time_node_group()
    time.location = (-1700, 300)
    scaled = _math(nodes, links, "MULTIPLY", time.outputs[0], fps, (-1500, 300))
    floored = _math(nodes, links, "FLOOR", scaled, None, (-1350, 300))
    index = _math(nodes, links, "MODULO", floored, float(count), (-1200, 300))

    color = alpha = None
    for i, image in enumerate(images):
        texture_node = nodes.new("ShaderNodeTexImage")
        texture_node.image = image
        texture_node.label = f"Frame {i}"
        texture_node.location = (-1500, -300 * i)
        if i == 0:
            color, alpha = texture_node.outputs["Color"], texture_node.outputs["Alpha"]
            continue

        use_frame = _math(nodes, links, "GREATER_THAN", index, i - 0.5, (-1200, -300 * i))
        for data_type, value_id, result_id, frame_output in (
            ("RGBA", "Color", "Result_Color", texture_node.outputs["Color"]),
            ("FLOAT", "Float", "Result_Float", texture_node.outputs["Alpha"]),
        ):
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = data_type
            mix.location = (-1000 + 150 * (data_type == "FLOAT"), -300 * i)
            links.new(use_frame, _socket(mix.inputs, "Factor_Float"))
            links.new(color if data_type == "RGBA" else alpha, _socket(mix.inputs, f"A_{value_id}"))
            links.new(frame_output, _socket(mix.inputs, f"B_{value_id}"))
            if data_type == "RGBA":
                color = _socket(mix.outputs, result_id)
            else:
                alpha = _socket(mix.outputs, result_id)

    return color, alpha


def create_obj_from_mesh(
    unique_name: str,
    mesh_data: MeshData,
    visuals_cache: Dict[str, VisualLoader],
    collection: Optional[bpy.types.Collection] = None,
) -> bpy.types.Object:
    """
    Create a Blender object from a MeshData dataclass.

    The mesh data is provided by the VOB parsing stage. This function
    creates a Blender mesh object, assigns UV data if present, and
    applies materials from the visuals cache.

    Materials come from the mesh data and are turned into Blender
    materials by create_material, which reuses identical ones and loads
    textures through the visuals_cache (name -> loader).

    The object is linked to ``collection``, or to the context collection of
    the active Blender scene if none is given.
    """
    mesh = bpy.data.meshes.new(unique_name)
    mesh.from_pydata(mesh_data.vertices, [], mesh_data.faces)  # type: ignore
    # Blender <= 4.0 ignores custom split normals unless Auto Smooth is on.
    # 4.1 removed the property and always uses custom normals when present.
    if hasattr(mesh, "use_auto_smooth"):
        mesh.use_auto_smooth = True
    mesh.normals_split_custom_set(mesh_data.normals)  # type: ignore

    if mesh_data.uvs:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        flat_uvs = [coord for uv in mesh_data.uvs for coord in uv]
        uv_layer.data.foreach_set("uv", flat_uvs)

    if not mesh_data.materials:
        warning("Mesh has no materials")
    else:
        for material in mesh_data.materials:
            mesh.materials.append(create_material(material, visuals_cache))
        mesh.polygons.foreach_set("material_index", mesh_data.material_indices)

    mesh.update()

    obj = bpy.data.objects.new(unique_name, mesh)
    obj.rotation_mode = "QUATERNION"
    (collection or bpy.context.collection).objects.link(obj)

    return obj


def create_obj_from_vob_data(
    unique_name: str,
    vob_data: BlenderObjectData,
    visuals_cache: Dict[str, VisualLoader],
    collection: Optional[bpy.types.Collection] = None,
) -> Optional[bpy.types.Object]:
    """
    Create a Blender object from BlenderObjectData.

    This is called once for each distinct VOB mesh — the mesh data
    is used to create a Blender mesh object, and the object's position
    and rotation are set from the BlenderObjectData.

    Logs an error and returns None if the VOB has no mesh data.
    """
    vob_mesh = vob_data.mesh

    if not vob_mesh:
        error(f"VOB {unique_name} has no mesh, skipping")
        return None

    obj = create_obj_from_mesh(unique_name, vob_mesh, visuals_cache, collection)
    obj.location = vob_data.position or Vector((0, 0, 0))
    obj.rotation_quaternion = vob_data.rotation or Quaternion()

    return obj


def create_instance_from_vob_data(
    unique_name: str,
    obj: bpy.types.Object,
    vob_data: BlenderObjectData,
    collection: Optional[bpy.types.Collection] = None,
) -> bpy.types.Object:
    """
    Create a Blender object instance from an existing Blender object.

    This function creates a new Blender object that shares the mesh data
    of ``obj`` (no geometry is copied) and sets its position and
    rotation. Used to instance VOBs that share the same mesh, avoiding
    the creation of duplicate mesh objects.

    The new object is linked to ``collection``, or to the context
    collection if none is given.
    """
    instance = bpy.data.objects.new(unique_name, obj.data)
    instance.rotation_mode = "QUATERNION"
    instance.location = vob_data.position or Vector((0, 0, 0))
    instance.rotation_quaternion = vob_data.rotation or Quaternion()

    (collection or bpy.context.collection).objects.link(instance)
    return instance


def create_edge_mesh_object(
    unique_name: str,
    vertices: List[Vector],
    edges: List[Tuple[int, int]],
    collection: Optional[bpy.types.Collection] = None,
) -> bpy.types.Object:
    """
    Create an object whose mesh consists only of loose edges.

    Used to draw the waynet connections. A single mesh with loose edges is
    far cheaper for Blender to evaluate and draw than a curve with one
    spline per connection (about 40x less evaluation time for a
    waynet-sized graph), and it can still be edited or converted later.

    The object is drawn in front of other geometry so the graph stays
    visible where it runs through terrain, and is linked to
    ``collection`` (or the context collection).
    """
    mesh = bpy.data.meshes.new(unique_name)
    mesh.from_pydata(vertices, edges, [])  # type: ignore
    mesh.update()

    obj = bpy.data.objects.new(unique_name, mesh)
    obj.show_in_front = True
    (collection or bpy.context.collection).objects.link(obj)
    return obj


def create_vobs(vobs: Dict[str, BlenderObjectData], visuals_cache: Dict[str, VisualLoader]):
    """
    Create Blender objects for all VOBs in a world.

    This function implements the VOB instancing optimization: VOBs that
    share the same mesh data are represented by a single Blender mesh
    object with multiple instances. This avoids creating duplicate mesh
    objects (which would be expensive in Blender and bloat .blend files).

    The instancing works by keying created objects by `id(vob_data.mesh)`
    (the Python object id of the mesh data, not the mesh content). If
    a VOB's mesh has already been seen, a new object instance is created
    for that VOB using the existing mesh object. Otherwise, the mesh
    is created fresh.

    Each object is linked to the collection given by its
    BlenderObjectData.collection path (see ensure_collection); objects
    with an empty path go to the context collection.

    After processing, the Blender view layer is updated to reflect the
    new objects.

    VOBs with no mesh data are skipped (with a warning).
    """
    success_count = 0
    obj_cache: Dict[int, bpy.types.Object] = {}  # keyed by id(mesh), not mesh content
    collections: Dict[Tuple[str, ...], bpy.types.Collection] = {}

    for vob_name, vob_data in vobs.items():
        vob_mesh = vob_data.mesh
        mesh_key = id(vob_mesh)
        result = None

        path = vob_data.collection
        if path not in collections:
            collections[path] = ensure_collection(path) if path else bpy.context.collection
        collection = collections[path]

        if mesh_key in obj_cache:
            existing_obj = obj_cache[mesh_key]
            result = create_instance_from_vob_data(vob_name, existing_obj, vob_data, collection)
        else:
            result = create_obj_from_vob_data(vob_name, vob_data, visuals_cache, collection)
            if not result:
                warning(f"VOB {vob_name} has no mesh, skipping")
                continue
            obj_cache[mesh_key] = result

        success_count += 1

    bpy.context.view_layer.update()
    info(f"Created {success_count} VOBs")
