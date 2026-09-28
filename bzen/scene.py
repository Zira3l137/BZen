from dataclasses import dataclass, field
from logging import error, info, warning
from typing import Dict, List, Optional, Tuple

import bpy
import numpy as np  # numpy is bundled with Blender
from mathutils import Quaternion, Vector
from visual import MaterialData, MeshData, VisualLoader
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

    texture_node = nodes.new("ShaderNodeTexImage")
    invert_node = nodes.new("ShaderNodeInvert")
    diffuse_node = nodes.new("ShaderNodeBsdfDiffuse")
    mix_shader = nodes.new("ShaderNodeMixShader")
    output_node = nodes.new("ShaderNodeOutputMaterial")

    texture_node.location = (-800, 0)
    invert_node.location = (-600, -100)
    diffuse_node.location = (-400, 0)
    mix_shader.location = (-200, 0)
    output_node.location = (200, 0)

    texture_name = material.texture.lower()
    texture_obj = visuals_cache.get(texture_name)  # type: ignore
    image = None
    if texture_obj:
        try:
            image = bpy.data.images.get(texture_name) or create_texture(texture_name, texture_obj())  # type: ignore
        except Exception as e:
            # A texture that can't be read shouldn't abort the conversion; the
            # material is still created, just without an image.
            warning(f'Could not load texture "{texture_name}" for material "{material.name}": {e!r}')
    texture_node.image = image  # type: ignore

    diffuse_node.inputs["Roughness"].default_value = 1.0  # type: ignore
    bmat.diffuse_color = material.color

    links.new(texture_node.outputs["Color"], diffuse_node.inputs["Color"])
    links.new(texture_node.outputs["Alpha"], invert_node.inputs["Color"])
    links.new(invert_node.outputs["Color"], mix_shader.inputs["Fac"])
    links.new(diffuse_node.outputs["BSDF"], mix_shader.inputs[2])
    links.new(mix_shader.outputs["Shader"], output_node.inputs["Surface"])

    transparent_shader = nodes.new("ShaderNodeBsdfTransparent")
    transparent_shader.location = (-400, -200)
    invert_node.inputs[0].default_value = 0.0  # type: ignore
    links.new(transparent_shader.outputs["BSDF"], mix_shader.inputs[1])

    return bmat


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
