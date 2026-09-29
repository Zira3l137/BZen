import math
from dataclasses import dataclass, field
from enum import Enum
from logging import error, info
from os import scandir
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TypeAlias

from mathutils import Matrix, Vector
from utils import canonical_case_path, suffix, trim_suffix, with_suffix
from zenkit import (
    AnimationMapping,
    Model,
    ModelHierarchy,
    ModelMesh,
    MorphMesh,
    MultiResolutionMesh,
    Texture,
    Vfs,
    VfsNode,
    VirtualObject,
    VisualDecal,
    World,
)

"""
Visual data model definitions for the VOB parsing pipeline.

These dataclasses are used to carry parsed mesh and material data between
the VOB parsing stage (vob.py) and the Blender object creation stage
(scene.py). They are frozen with slots for immutability and memory
efficiency.

Deduplication does not rely on hashing MeshData: parsed meshes are cached
by visual name in vob.py, and scene.create_vobs instances Blender objects
by the identity (id()) of the shared MeshData object.
"""


VobVisual: TypeAlias = MultiResolutionMesh | ModelMesh | Model | MorphMesh | ModelHierarchy | Texture
VisualLoader: TypeAlias = Callable[[], Optional[VobVisual]]


class VisualExtension(str, Enum):
    """Enum of supported visual file extensions.

    Deliberately ``(str, Enum)`` rather than ``enum.StrEnum``: StrEnum needs
    Python 3.11, but Blender 4.0 bundles Python 3.10. ``__str__`` is
    overridden so that str() and f-strings yield the bare value ("mrm") on
    every Python version, exactly like StrEnum did; with_suffix() relies on it.
    """

    def __str__(self) -> str:
        return str(self.value)
    MRM = "mrm"
    MDL = "mdl"
    MDM = "mdm"
    MMB = "mmb"
    MDH = "mdh"
    TEX = "tex"


"""
Mapping from the source file extension a VOB's visual refers to (e.g.
"TREE.3DS") to the extension of the compiled file the game actually
ships (e.g. "tree.mrm"). parse_visual_data uses it to find the compiled
file for a visual name.
"""

_compiled_extension = {
    "3ds": VisualExtension.MRM,
    "asc": VisualExtension.MDL,
    "mds": VisualExtension.MDM,
    "mms": VisualExtension.MMB,
    "tga": VisualExtension.TEX,
}

"""
Mapping from compiled file extension (VisualExtension) to the ZenKit
loader for that file type. Each loader takes a path (str, Path, or
VfsNode) and returns the loaded ZenKit object.

Used by load_visual, which the lazy loaders created during indexing call,
so visuals from disk and from VFS archives are loaded the same way.
"""

_load_visual = {
    VisualExtension.MRM: MultiResolutionMesh.load,
    VisualExtension.MDL: Model.load,
    VisualExtension.MDM: ModelMesh.load,
    VisualExtension.MMB: MorphMesh.load,
    VisualExtension.MDH: ModelHierarchy.load,
    VisualExtension.TEX: Texture.load,
}

"""
Mapping from source file extension (3ds, asc, mds, mms) to the parser for
that visual type. Each parser takes the compiled file name (with .mrm,
.mdl, .mdm, or .mmb extension), the visuals cache (to load that file and
any files it depends on), and a scale factor.

This is used by parse_visual_data to dispatch to the correct parser.
For .mds visuals, the parser also loads the matching .mdh hierarchy.
"""

_parse_visual_data = {
    "3ds": lambda name, cache, scale: parse_multi_resolution_mesh(load_indexed_visual(cache, name), scale),
    "asc": lambda name, cache, scale: parse_model(load_indexed_visual(cache, name), scale),
    "mds": lambda name, cache, scale: parse_model_mesh(
        load_indexed_visual(cache, name),
        load_indexed_visual(cache, with_suffix(name, "mdh", True).lower()),
        scale,
    ),
    "mms": lambda name, cache, scale: parse_morph_mesh(load_indexed_visual(cache, name), scale),
}

"""
Base matrices for converting model hierarchy (node) transforms from
Gothic's coordinate system (left-handed, Y up) to Blender's (right-handed,
Z up):

- BASE_SCALE_MATRIX mirrors the Y axis (scale by -1 along Y).
- BASE_ROTATION_MATRIX rotates -90 degrees about the X axis.

They are used by parse_mesh_attachments. VOB positions and rotations are
converted separately in vob.py by swapping the Y and Z components.
"""

BASE_SCALE_MATRIX = Matrix().Scale(-1, 4, Vector((0, 1, 0)))
BASE_ROTATION_MATRIX = Matrix().Rotation(math.radians(-90), 4, Vector((1, 0, 0)))

"""
Categories of visual assets indexed by index_visuals. Each category
corresponds to a subdirectory in the game's _work/data or data
directories that contains compiled visual files.
"""

VISUAL_CATEGORIES = ["anims", "textures", "meshes"]

"""
Names of the archive files that contain visual assets. The naming
pattern alternates between <category>.vdf and <category>_addon.vdf.

These files are mounted as VFS archives by the Vfs class during
indexing.
"""

VISUAL_ARCHIVES = [
    f"{category}.vdf" if not addon else f"{category}_addon.vdf"
    for category in VISUAL_CATEGORIES
    for addon in (False, True)
]


@dataclass(frozen=True, slots=True)
class MaterialData:
    """
    Material definition parsed from a mesh.

    A material consists of a name, a diffuse color (RGBA with values
    0-1), and an optional texture name. Materials are used to create
    Blender materials when mesh objects are created.

    Materials with the same name, color, texture and texture animation
    are considered identical; scene.create_material shares one Blender
    material between them.
    """
    name: str
    color: Tuple[float, float, float, float]
    texture: Optional[str] = field(default=None)
    # Frame rate of a frame-sequence texture animation (texture names with
    # "_A0", see animated_texture_frames); 0 means the game's default.
    texture_anim_fps: float = field(default=0.0)
    # UV scrolling speed in UV units per millisecond, in Gothic's UV space;
    # (0, 0) when the material does not scroll.
    uv_scroll: Tuple[float, float] = field(default=(0.0, 0.0))

    def __hash__(self):
        return hash(self.name) + hash(self.color) + hash(self.texture)


@dataclass(frozen=True, slots=True)
class MeshData:
    """
    Mesh data parsed from a compiled visual file.

    This dataclass holds the raw mesh data (vertices, faces, normals,
    UV data) and material assignments. It is used to create Blender
    mesh objects in scene.py.

    Normals and UVs are stored per face corner (three per triangle, in
    face order), while vertices are shared between faces.

    The is_empty method (no vertices) is used by zen_to_blend to report
    an empty level mesh.

    The __hash__ method is a cheap size-based hash; it is not used for
    deduplication (see the module notes above).
    """
    vertices: List[Vector] = field(default_factory=list)
    faces: List[Tuple[int, int, int]] = field(default_factory=list)
    normals: List[Vector] = field(default_factory=list)
    uvs: List[Tuple[float, float]] = field(default_factory=list)
    materials: List[MaterialData] = field(default_factory=list)
    material_indices: List[int] = field(default_factory=list)

    def is_empty(self) -> bool:
        return len(self.vertices) == 0

    def __hash__(self) -> int:
        return (
            len(self.vertices)
            + len(self.faces)
            + len(self.material_indices)
            + len(self.normals)
            + len(self.uvs)
            + sum(hash(m) for m in self.materials)
        )


def drop_degenerate_faces(mesh_data: MeshData) -> Tuple[MeshData, int]:
    """
    Return ``mesh_data`` without triangles that use the same vertex more than
    once, together with the number of triangles dropped.

    The parsers merge vertices by position, so a triangle whose corners
    have different position indices but identical coordinates ends up with
    a repeated vertex index, e.g. (5, 5, 9). Blender 4.5 and older silently
    skipped the zero-length edge such a face implies; from 5.1 on,
    Mesh.from_pydata keeps it as an edge from a vertex to itself, and
    entering Edit Mode on the mesh then hangs (and on 5.2
    normals_split_custom_set can crash). These triangles have no area, so
    dropping them changes nothing visible.

    Normals and UVs are stored per face corner (three per triangle, in face
    order) and are filtered along with the faces so they stay aligned.
    Returns the original object unchanged if nothing had to be dropped.
    """
    keep = [len(set(face)) == 3 for face in mesh_data.faces]
    dropped = keep.count(False)
    if not dropped:
        return mesh_data, 0

    def corners(values: list) -> list:
        return [value for index, value in enumerate(values) if keep[index // 3]] if values else values

    return (
        MeshData(
            vertices=mesh_data.vertices,
            faces=[face for face, k in zip(mesh_data.faces, keep) if k],
            normals=corners(mesh_data.normals),
            uvs=corners(mesh_data.uvs),
            materials=mesh_data.materials,
            material_indices=[index for index, k in zip(mesh_data.material_indices, keep) if k],
        ),
        dropped,
    )


class MissingVisualError(Exception):
    """
    Raised when a visual needed to build a mesh is not in the visuals index,
    i.e. the file exists neither on disk nor in any of the mounted archives.

    The missing (lowercased, compiled) file name is available as ``name`` so
    callers can report each missing file once instead of once per VOB.
    """

    def __init__(self, name: str):
        super().__init__(f'"{name}" was not found in the game files')
        self.name = name


def load_indexed_visual(cache: Dict[str, VisualLoader], name: str) -> Optional[VobVisual]:
    """
    Load the visual indexed under ``name``.

    Raises MissingVisualError if nothing was indexed under that name, instead
    of the bare KeyError a plain ``cache[name]`` lookup would raise.
    """
    loader = cache.get(name)
    if loader is None:
        raise MissingVisualError(name)
    return loader()


def material_data_from_zenkit(mat) -> MaterialData:
    """
    Convert a ZenKit material (of the level mesh or of an MRM) to MaterialData.

    The color is converted from 0-255 to 0-1 RGBA. Texture animation
    settings are carried over: the frame rate for frame-sequence textures
    and, for materials with LINEAR animation mapping, the UV scrolling
    direction.
    """
    mat_color = mat.color
    inv255 = 1.0 / 255.0
    color = (mat_color.r * inv255, mat_color.g * inv255, mat_color.b * inv255, mat_color.a * inv255)

    uv_scroll = (0.0, 0.0)
    if mat.texture_animation_mapping == AnimationMapping.LINEAR:
        direction = mat.texture_animation_mapping_direction
        uv_scroll = (direction.x, direction.y)

    return MaterialData(mat.name, color, mat.texture, mat.texture_animation_fps, uv_scroll)


def animated_texture_frames(texture: str, visuals_cache: Dict[str, VisualLoader]) -> List[str]:
    """
    Return the (lowercased) texture names making up an animated texture.

    Gothic animates a texture whose name contains "_A0" by cycling through
    "_A1", "_A2", ... for as long as those textures exist; every "_A0" in
    the name is replaced by the frame's number. This follows OpenGothic
    (Resources::loadTextureAnim).

    Returns just the texture itself for a non-animated texture, and an
    empty list if even the first frame is not in the visuals cache.
    """
    name = texture.lower()
    if "_a0" not in name:
        return [name] if name in visuals_cache else []

    frames: List[str] = []
    while (frame := name.replace("_a0", f"_a{len(frames)}")) in visuals_cache:
        frames.append(frame)
    return frames


def _make_loader(path: str | Path | VfsNode, extension: VisualExtension) -> VisualLoader:
    """
    Factory function that returns a no-argument callable to load a visual.

    This is used by index_visuals to create VisualLoaders that close over
    the file path and extension. The loader is called later during VOB
    parsing to actually load the visual.

    The path is stored directly (not evaluated) so that the loader can
    handle both disk paths and VfsNode objects.
    """
    return lambda: load_visual(path, extension)


def index_visuals(game_directory: Path) -> Dict[str, VisualLoader]:
    """
    Index all available visuals for the given game directory.

    This function indexes visuals from two sources:
    1. Disk files in <game_directory>/_work/data/<category>/_compiled/
       (anims, textures, meshes subdirectories).
    2. VFS archives <game_directory>/data/<category>.vdf and
       <category>_addon.vdf.

    The indexing returns a dictionary mapping lowercased visual names
    (e.g., "texture.tga", "mesh.mrm") to VisualLoaders. The dictionary
    is built in memory; the actual loading of visuals happens lazily
    when a VisualLoader is called.

    Archives are indexed after disk files, so when both contain a file
    with the same name, the archive's copy is used.

    If indexing fails, "Failed to index visuals" is logged and the
    original exception is re-raised.
    """
    try:
        visuals = {}
        index_visuals_from_disk(game_directory, visuals)
        index_visuals_from_archives(game_directory, visuals)

    except Exception as e:
        error("Failed to index visuals")
        raise e

    info(f"Indexed {len(visuals)} visuals")
    return visuals


def index_visuals_from_disk(game_directory: Path, visuals: Dict[str, VisualLoader]):
    """
    Index visuals from the game directory's _work/data/_compiled/ subdirectories.

    This function walks the specified directories (anims, textures, meshes)
    and indexes any files with extensions matching VisualExtension values.

    Compiled textures (.tex) are indexed under their source name: the
    compiled name (e.g., "STONE-C.TEX") becomes "stone.tga", which is how
    materials refer to them.

    Indexed visuals are added to the `visuals` dictionary (passed by
    reference). An existing entry with the same name is overwritten.
    Missing _compiled directories are skipped.
    """
    paths = []
    for category in VISUAL_CATEGORIES:
        try:
            paths.append(canonical_case_path(game_directory / "_work" / "data" / category / "_compiled"))
        except FileNotFoundError:
            # Common on installs without loose compiled files; the archives
            # indexed afterwards still provide the game's assets.
            info(f'No "_work/data/{category}/_compiled" directory, skipping it')

    stack = [entry for path in paths for entry in scandir(path)]
    while stack:
        entry = stack.pop()
        if entry.is_dir():
            stack.extend([entry for entry in scandir(entry.path)])
            continue

        entry_ext = suffix(entry.name).lower()

        if entry_ext in [ve.value for ve in VisualExtension]:
            extension = VisualExtension(entry_ext)
            name = entry.name.lower()

            if extension is VisualExtension.TEX:
                name = with_suffix(name.replace("-c.", "."), "tga", True)

            visuals[name] = _make_loader(entry.path, extension)

    info(f"Indexed from disk: {len(visuals)}")


def index_visuals_from_archives(game_directory: Path, visuals: Dict[str, VisualLoader]):
    """
    Index visuals from the game directory's VFS archives.

    This function mounts each archive file (specified in VISUAL_ARCHIVES)
    as a VFS virtual filesystem and indexes any files with extensions
    matching VisualExtension values.

    Compiled textures (.tex) are indexed under their source name: the
    compiled name (e.g., "STONE-C.TEX") becomes "stone.tga", which is how
    materials refer to them.

    Indexed visuals are added to the `visuals` dictionary (passed by
    reference). An existing entry with the same name is overwritten, so
    archives take precedence over disk files, and later archives in
    VISUAL_ARCHIVES over earlier ones.

    If an archive file does not exist, the function silently skips it.
    """
    path = None
    for archive_path in VISUAL_ARCHIVES:
        try:
            path = canonical_case_path(game_directory / "data" / archive_path)
        except FileNotFoundError:
            continue

        vfs = Vfs()
        vfs.mount_disk(str(path))
        stack = [vfs.root]
        while stack:
            node = stack.pop()
            extension = suffix(node.name).lower()

            if extension in [ve.value for ve in VisualExtension]:
                name = node.name.lower()

                if extension == "tex":
                    name = with_suffix(name.replace("-c.", "."), "tga", True)
                visuals[name] = _make_loader(node, VisualExtension(extension))

            if node.is_dir():
                stack.extend(node.children)

    info(f"Indexed from archives: {len(visuals)}")


def load_visual(path: str | Path | VfsNode, extension: VisualExtension) -> Optional[VobVisual]:
    """
    Load a visual file from the given path.

    This is the dispatch function for loading compiled visual files.
    The actual loading is done by the loader function in the
    _load_visual mapping, which is selected based on the extension.

    Returns whatever the ZenKit loader returns; ZenKit does not report
    failures consistently, so callers treat any exception as a failed
    load. Visuals that are not indexed at all never reach this function
    (see load_indexed_visual).
    """
    return _load_visual[extension](path)


def parse_visual_data(name: str, cache: Dict[str, VisualLoader], scale: float = 0.01) -> Optional[MeshData]:
    """
    Parse mesh data from a compiled visual file.

    This function is the entry point for parsing visuals. ``name`` is the
    source name a VOB refers to (e.g., "tree.3ds", "hero.mds"); its
    extension selects the parser and the compiled file (.mrm, .mdm/.mdh,
    .mdl, .mmb) that is actually loaded.

    The cache is used for cross-reference lookups during parsing (e.g.,
    .mds files may reference .mdh files). The scale factor (default
    0.01) is applied to all mesh vertices during parsing.

    Returns None if the name has no extension or the extension is not in
    the _compiled_extension mapping. Raises MissingVisualError if the
    compiled file (or a file it depends on) is not in the cache.
    """
    extension = suffix(name).lower()
    if extension == "" or extension not in _compiled_extension:
        return None

    compiled_name = with_suffix(name, _compiled_extension[extension], True).lower()
    return _parse_visual_data[extension](compiled_name, cache, scale)


def parse_visual_data_from_vob(
    vob: VirtualObject, cache: Dict[str, VisualLoader], scale: float = 0.01
) -> Optional[MeshData]:
    """
    Parse mesh data from a VOB's visual.

    This function extracts the visual name from the VOB (if it exists)
    and calls parse_visual_data with that name. The scale factor
    (default 0.01) is applied to all mesh vertices during parsing.

    Returns None if the VOB has no visual, if the visual name has no
    extension, or if the extension is not in the _compiled_extension
    mapping.
    """
    if vob.visual is None:
        return None

    name = vob.visual.name.lower()
    return parse_visual_data(name, cache, scale)


def parse_world_mesh(wrld: World, scale: float = 0.01) -> MeshData:
    """
    Parse the static world mesh from a World object.

    The world mesh is the terrain/ground of a Gothic world. This function
    extracts vertices, faces, normals, UV data, and material assignments
    from the BSP tree and mesh data in the World object.

    The scale factor (default 0.01) converts positions from Gothic's
    centimeter units to Blender's meter units. This is a hard requirement
    of the format: Gothic stores all linear dimensions in centimeters.

    Vertices are deduplicated by position during parsing to minimize
    memory and file size; polygons referenced by several BSP leaves are
    emitted once. Portal and ghost occluder polygons are skipped.

    Returns an empty MeshData if the world has no mesh.
    """
    bsp, mesh = wrld.bsp_tree, wrld.mesh
    vertices, uvs, faces = [], [], []
    normals, materials, material_indices = [], [], []
    append_vertex, append_face = vertices.append, faces.append
    append_material_index, append_material = material_indices.append, materials.append
    extend_normals, extend_uvs = normals.extend, uvs.extend

    for mat in mesh.materials:
        append_material(material_data_from_zenkit(mat))

    vertex_cache, normal_cache, position_cache, seen_leaf_indices = {}, {}, {}, set()
    positions, features, polygons, leaf_polygon_indices = (
        mesh.positions,
        mesh.features,
        mesh.polygons,
        bsp.leaf_polygon_indices,
    )

    for leaf_index in leaf_polygon_indices:
        # Dedupe by the plain int leaf/polygon index rather than by Polygon
        # object equality: this is O(1) hash+compare regardless of how the
        # FFI binding implements Polygon.__eq__/__hash__, and sidesteps any
        # risk of a deep/content comparison firing on hash collisions.
        if leaf_index in seen_leaf_indices:
            continue
        seen_leaf_indices.add(leaf_index)

        polygon = polygons[leaf_index]
        position_indices, feature_indices = (
            polygon.position_indices,
            polygon.feature_indices,
        )

        if polygon.is_portal or polygon.is_ghost_occluder:
            continue

        for index in range(1, len(position_indices) - 1):
            face = []
            face_normals, face_uvs = [], []

            for vertex_index in [0, index, index + 1]:

                position_index = position_indices[vertex_index]
                feature_index = feature_indices[vertex_index]

                if position_index not in position_cache:
                    raw_position = positions[position_index] * scale
                    position_cache[position_index] = (raw_position.x, raw_position.z, raw_position.y)
                position = position_cache[position_index]

                if position not in vertex_cache:
                    vertex_cache[position] = len(vertices)
                    append_vertex(position)

                face.append(vertex_cache[position])

                vertex_feature = features[feature_index]
                uv = vertex_feature.texture

                # Normals repeat heavily across triangle-fan corners and
                # shared BSP-leaf boundaries; building a fresh mathutils.Vector
                # per corner (as before) redoes the same construction for the
                # same feature_index over and over. Cache by feature_index.
                if feature_index not in normal_cache:
                    normal = vertex_feature.normal
                    # Same Y/Z swap as the positions above (Gothic is Y-up,
                    # Blender is Z-up).
                    normal_cache[feature_index] = Vector((normal.x, normal.z, normal.y))

                face_uvs.append((uv.x, -uv.y))
                face_normals.append(normal_cache[feature_index])

            extend_uvs(face_uvs)
            extend_normals(face_normals)
            append_face(face)
            append_material_index(polygon.material_index)

    return MeshData(vertices, faces, normals, uvs, materials, material_indices)


def parse_multi_resolution_mesh(mrm: MultiResolutionMesh, scale: float = 0.01) -> MeshData:
    """
    Parse a compiled MRM (multi-resolution mesh) file.

    MRM files are the primary compiled visual format in Gothic. They contain
    mesh vertices, faces, normals, UV data, and material definitions.

    The scale factor (default 0.01) is applied to all positions during
    parsing, converting from Gothic's centimeter units to Blender's meter
    units.

    Positions are deduplicated during parsing to minimize memory and file
    size. The function returns a MeshData object with all parsed mesh data.

    The vertex cache (vertex_cache) maps positions to vertex indices to
    avoid creating duplicate vertex entries.
    """
    vertices, uvs, faces = [], [], []
    normals, materials, material_indices = [], [], []
    append_vertex, append_face = vertices.append, faces.append
    append_material_index = material_indices.append
    extend_normals, extend_uvs = normals.extend, uvs.extend

    for mat in mrm.material:
        materials.append(material_data_from_zenkit(mat))

    positions, vertex_cache = [Vector((pos.x, pos.y, pos.z)) for pos in mrm.positions], {}
    for submesh_index, submesh in enumerate(mrm.submeshes):
        wedges = submesh.wedges
        triangles = submesh.triangles

        for triangle in triangles:
            triangle_wedges = triangle.wedges
            face, face_normals, face_uvs = [], [], []

            for i in range(3):
                wedge = wedges[triangle_wedges[i]]
                face_normals.append(Vector((wedge.normal.x, wedge.normal.z, wedge.normal.y)))
                position = positions[wedge.index] * scale
                position = (position.x, position.z, position.y)

                if position not in vertex_cache:
                    face_index = len(vertices)
                    face.append(face_index)

                    append_vertex(Vector(position))
                    vertex_cache[position] = face_index
                else:
                    face.append(vertex_cache[position])

                face_uvs.append((wedge.texture.x, -wedge.texture.y))

            extend_uvs(face_uvs)
            extend_normals(face_normals)
            append_material_index(submesh_index)
            append_face(face)

    return MeshData(vertices, faces, normals, uvs, materials, material_indices)


def parse_decal_mesh(vob: VirtualObject, scale: float = 0.01) -> Optional[MeshData]:
    """
    Build the mesh for a decal VOB.

    A decal's visual is a texture (e.g. "BLOOD.TGA") drawn on a flat quad
    rather than a mesh file, so the quad is generated here: 4 vertices for
    the front and 4 for the back, so the decal is visible from both sides,
    with a single material using the decal's texture. The quad spans
    -dimension..+dimension on both axes.

    The scale factor (default 0.01) is applied to the decal's dimensions to
    convert from Gothic's centimeter units to Blender's meter units.

    The VOB must have a decal visual; callers check this beforehand.
    """
    visual_name = vob.visual.name.lower()
    visual: VisualDecal = vob.visual  # type: ignore
    material = MaterialData(
        trim_suffix(visual_name), (1.0, 1.0, 1.0, 1.0), visual_name, texture_anim_fps=visual.texture_anim_fps
    )
    dimension_x, dimension_y = (
        visual.dimension.x * scale,
        visual.dimension.y * scale,
    )

    v0 = Vector((-dimension_x, 0, -dimension_y))  # Bottom-left
    v1 = Vector((dimension_x, 0, -dimension_y))  # Bottom-right
    v2 = Vector((dimension_x, 0, dimension_y))  # Top-right
    v3 = Vector((-dimension_x, 0, dimension_y))  # Top-left

    vertices = [v0, v1, v2, v3]
    vertices += [v0.copy(), v1.copy(), v2.copy(), v3.copy()]

    faces = [
        (0, 1, 2),
        (0, 2, 3),
        (6, 5, 4),  # Flipped winding
        (7, 6, 4),  # Flipped winding
    ]

    # The quad lies in the XZ plane, so its normals point along Y: the front
    # triangles (0, 1, 2) and (0, 2, 3) wind towards -Y, the flipped back
    # triangles towards +Y. 3 loop normals per triangle, 2 triangles per side.
    normals = [Vector((0, -1, 0))] * 3 * 2
    normals += [Vector((0, 1, 0))] * 3 * 2

    uvs = [
        # Front face
        (0.0, 0.0),  # v0
        (1.0, 0.0),  # v1
        (1.0, 1.0),  # v2
        (0.0, 0.0),  # v0
        (1.0, 1.0),  # v2
        (0.0, 1.0),  # v3
        # Back face (can be same UVs since it's a decal)
        (1.0, 1.0),  # v2
        (1.0, 0.0),  # v1
        (0.0, 0.0),  # v0
        (0.0, 1.0),  # v3
        (1.0, 1.0),  # v2
        (0.0, 0.0),  # v0
    ]

    materials = [material]
    material_indices = [0, 0, 0, 0]

    return MeshData(
        vertices=vertices,
        faces=faces,
        normals=normals,
        uvs=uvs,
        materials=materials,
        material_indices=material_indices,
    )


def parse_mesh_attachments(
    mdm: ModelMesh, mdh: ModelHierarchy, scale: float = 0.01
) -> Tuple[MeshData, Tuple[int, int]]:
    """
    Parse mesh attachments from a model mesh.

    Besides soft-skinned meshes, a model mesh (.mdm) can contain
    attachments: rigid meshes attached to named nodes of the model
    hierarchy (.mdh), e.g. the parts of a chest or a door.

    For each attachment, the function:
    1. Parses the attached mesh data using parse_multi_resolution_mesh.
    2. Computes the transformation matrix for the attachment node.
    3. Applies the node's transform (scale + rotation) to convert the
       mesh vertices to world coordinates.
    4. Accumulates the mesh data, vertex offsets, and material offsets.

    The transformation matrices use BASE_ROTATION_MATRIX and BASE_SCALE_MATRIX
    to convert from Gothic's coordinate system to Blender's coordinate
    system. The accumulated buffer (buffer) maps node indices to their
    world matrices for parent lookups during transform accumulation.

    Returns a tuple of (parsed MeshData, (total_vertex_offset,
    total_material_offset)).
    """
    nodes = mdh.nodes
    attachments = mdm.attachments
    vertices, faces, normals = [], [], []
    uvs, materials, material_indices = [], [], []
    vertex_offset, material_offset = 0, 0
    buffer = {}

    for index, node in enumerate(nodes):
        if node.name not in attachments:
            continue

        attachment = attachments[node.name]
        mesh = parse_multi_resolution_mesh(attachment, scale)

        node_transform = node.transform
        node_matrix = Matrix(
            [
                [col.x for col in node_transform.columns[:3]],
                [col.y for col in node_transform.columns[:3]],
                [col.z for col in node_transform.columns[:3]],
            ]
        ).to_4x4()

        translation = (
            Vector(
                (
                    node_transform.columns[3].x,
                    node_transform.columns[3].y,
                    node_transform.columns[3].z,
                )
            )
            * scale
        )
        node_matrix.translation = translation
        world_matrix = Matrix()

        if node.parent != -1 and node.parent in buffer:
            parent_transform = buffer[node.parent]
            world_matrix = parent_transform @ node_matrix
        else:
            world_matrix = BASE_ROTATION_MATRIX @ BASE_SCALE_MATRIX @ node_matrix

        buffer[index] = world_matrix
        world_matrix = world_matrix @ BASE_ROTATION_MATRIX @ BASE_SCALE_MATRIX

        vertices_relative_to_parent = [world_matrix @ vertex for vertex in mesh.vertices]
        # Normals must be rotated along with the vertices. The inverse
        # transpose of the linear part keeps them perpendicular to their
        # faces even if a node transform is not a pure rotation.
        normal_matrix = world_matrix.to_3x3().inverted_safe().transposed()
        rotated_normals = [(normal_matrix @ normal).normalized() for normal in mesh.normals]

        faces.extend(tuple(idx + vertex_offset for idx in face) for face in mesh.faces)
        material_indices.extend(idx + material_offset for idx in mesh.material_indices)
        materials.extend(mesh.materials)
        vertices.extend(vertices_relative_to_parent)
        normals.extend(rotated_normals)
        uvs.extend(mesh.uvs)

        vertex_offset += len(mesh.vertices)
        material_offset += len(mesh.materials)

    return MeshData(vertices, faces, normals, uvs, materials, material_indices), (
        vertex_offset,
        material_offset,
    )


def parse_model_mesh(mdm: ModelMesh, mdh: ModelHierarchy, scale: float = 0.01) -> MeshData:
    """
    Parse a model mesh (.mdm, compiled from .mds) with its hierarchy (.mdh).

    Model meshes consist of soft skin meshes (parsed as multi-resolution
    meshes) and attachments (parsed as meshes with node transforms).

    This function:
    1. Parses mesh attachments from the model hierarchy (via
       parse_mesh_attachments).
    2. Parses soft skin meshes from the model mesh.
    3. Applies the root translation to soft skin meshes.
    4. Combines all parsed data into a single MeshData.

    The scale factor (default 0.01) is applied during parsing to convert
    from Gothic's centimeter units to Blender's meter units.
    """
    soft_skin_meshes = mdm.meshes
    root_translation = mdh.root_translation
    root_translation = Vector((root_translation.x, root_translation.z, root_translation.y)) * scale
    parsed_attachments, (vertex_offset, material_offset) = parse_mesh_attachments(mdm, mdh, scale)
    vertices, faces, normals, uvs, materials, material_indices = (
        parsed_attachments.vertices,
        parsed_attachments.faces,
        parsed_attachments.normals,
        parsed_attachments.uvs,
        parsed_attachments.materials,
        parsed_attachments.material_indices,
    )

    for soft_skin_mesh in soft_skin_meshes:
        mesh = parse_multi_resolution_mesh(soft_skin_mesh.mesh, scale)

        vertices_relative_to_root = [vertex - root_translation for vertex in mesh.vertices]
        vertices.extend(vertices_relative_to_root)

        faces.extend(tuple(idx + vertex_offset for idx in face) for face in mesh.faces)  # type: ignore
        material_indices.extend(idx + material_offset for idx in mesh.material_indices)
        materials.extend(mesh.materials)
        normals.extend(mesh.normals)
        uvs.extend(mesh.uvs)

        vertex_offset += len(mesh.vertices)
        material_offset += len(mesh.materials)

    return MeshData(vertices, faces, normals, uvs, materials, material_indices)


def parse_morph_mesh(mmb: MorphMesh, scale: float = 0.01) -> MeshData:
    """
    Parse a morph mesh (.mmb, compiled from .mms).

    Morph meshes are meshes with vertex animations (e.g. heads with facial
    expressions). Only the base mesh is converted, by delegating to
    parse_multi_resolution_mesh; the morph animations are ignored.
    """
    return parse_multi_resolution_mesh(mmb.mesh, scale)


def parse_model(mdl: Model, scale: float = 0.01) -> MeshData:
    """
    Parse a model (.mdl, compiled from .asc).

    A model bundles a model mesh and its hierarchy in one file; both are
    passed to parse_model_mesh.

    The scale factor (default 0.01) is applied during parsing to convert
    from Gothic's centimeter units to Blender's meter units.
    """
    return parse_model_mesh(mdl.mesh, mdl.hierarchy, scale)
