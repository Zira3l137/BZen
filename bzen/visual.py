import math
from dataclasses import dataclass, field
from enum import StrEnum
from logging import error, info
from os import scandir
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TypeAlias

from mathutils import Matrix, Vector
from utils import canonical_case_path, suffix, trim_suffix, with_suffix
from zenkit import (
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

VobVisual: TypeAlias = MultiResolutionMesh | ModelMesh | Model | MorphMesh | ModelHierarchy | Texture
VisualLoader: TypeAlias = Callable[[], Optional[VobVisual]]


class VisualExtension(StrEnum):
    MRM = "mrm"
    MDL = "mdl"
    MDM = "mdm"
    MMB = "mmb"
    MDH = "mdh"
    TEX = "tex"


_compiled_extension = {
    "3ds": VisualExtension.MRM,
    "asc": VisualExtension.MDL,
    "mds": VisualExtension.MDM,
    "mms": VisualExtension.MMB,
    "tga": VisualExtension.TEX,
}

_load_visual = {
    VisualExtension.MRM: MultiResolutionMesh.load,
    VisualExtension.MDL: Model.load,
    VisualExtension.MDM: ModelMesh.load,
    VisualExtension.MMB: MorphMesh.load,
    VisualExtension.MDH: ModelHierarchy.load,
    VisualExtension.TEX: Texture.load,
}

_parse_visual_data = {
    "3ds": lambda name, cache, scale: parse_multi_resolution_mesh(cache[name](), scale),
    "asc": lambda name, cache, scale: parse_model(cache[name](), scale),
    "mds": lambda name, cache, scale: parse_model_mesh(
        cache[name](), cache[with_suffix(name, "mdh", True).lower()](), scale
    ),
    "mms": lambda name, cache, scale: parse_morph_mesh(cache[name](), scale),
}

BASE_SCALE_MATRIX = Matrix().Scale(-1, 4, Vector((0, 1, 0)))
BASE_ROTATION_MATRIX = Matrix().Rotation(math.radians(-90), 4, Vector((1, 0, 0)))

VISUAL_CATEGORIES = ["anims", "textures", "meshes"]
VISUAL_ARCHIVES = [
    f"{category}.vdf" if not addon else f"{category}_addon.vdf"
    for category in VISUAL_CATEGORIES
    for addon in (False, True)
]


@dataclass(frozen=True, slots=True)
class MaterialData:
    name: str
    color: Tuple[float, float, float, float]
    texture: Optional[str] = field(default=None)

    def __hash__(self):
        return hash(self.name) + hash(self.color) + hash(self.texture)


@dataclass(frozen=True, slots=True)
class MeshData:
    vertices: list[Vector] = field(default_factory=list)
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


def _make_loader(path: str | Path | VfsNode, extension: VisualExtension) -> VisualLoader:
    return lambda: load_visual(path, extension)


def index_visuals(game_directory: Path) -> Dict[str, VisualLoader]:
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
    paths = [
        canonical_case_path(game_directory / "_work" / "data" / category / "_compiled")
        for category in VISUAL_CATEGORIES
    ]

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
    return _load_visual[extension](path)


def parse_visual_data(name: str, cache: Dict[str, VisualLoader], scale: float = 0.01) -> Optional[MeshData]:
    extension = suffix(name).lower()
    if extension == "" or extension not in _compiled_extension:
        return None

    compiled_name = with_suffix(name, _compiled_extension[extension], True).lower()
    return _parse_visual_data[extension](compiled_name, cache, scale)


def parse_visual_data_from_vob(
    vob: VirtualObject, cache: Dict[str, VisualLoader], scale: float = 0.01
) -> Optional[MeshData]:
    if vob.visual is None:
        return None

    name = vob.visual.name.lower()
    mesh_data = parse_visual_data(name, cache, scale)
    if not mesh_data:
        return None

    return mesh_data


def parse_world_mesh(wrld: World, scale: float = 0.01) -> MeshData:
    bsp, mesh = wrld.bsp_tree, wrld.mesh
    vertices, uvs, faces = [], [], []
    normals, materials, material_indices = [], [], []
    append_vertex, append_face = vertices.append, faces.append
    append_material_index, append_material = material_indices.append, materials.append
    extend_normals, extend_uvs = normals.extend, uvs.extend

    for mat in mesh.materials:
        mat_color = mat.color
        r, g, b, a = mat_color.r, mat_color.g, mat_color.b, mat_color.a
        inv255 = 1.0 / 255.0
        color = (
            r * inv255,
            g * inv255,
            b * inv255,
            a * inv255,
        )
        append_material(MaterialData(mat.name, color, mat.texture))

    vertex_cache, polygon_cache = {}, set()
    positions, features, polygons, leaf_polygon_indices = (
        mesh.positions,
        mesh.features,
        mesh.polygons,
        bsp.leaf_polygon_indices,
    )

    for leaf_index in leaf_polygon_indices:
        polygon = polygons[leaf_index]
        position_indices, feature_indices = (
            polygon.position_indices,
            polygon.feature_indices,
        )

        if polygon in polygon_cache or polygon.is_portal or polygon.is_ghost_occluder:
            continue

        polygon_cache.add(polygon)
        for index in range(1, len(position_indices) - 1):
            face = []
            face_normals, face_uvs = [], []

            for vertex_index in [0, index, index + 1]:

                position_index = position_indices[vertex_index]
                feature_index = feature_indices[vertex_index]

                position = positions[position_index] * scale
                position = (position.x, position.z, position.y)

                if position not in vertex_cache:
                    vertex_cache[position] = len(vertices)
                    append_vertex(position)

                face.append(vertex_cache[position])

                vertex_feature = features[feature_index]
                uv = vertex_feature.texture
                normal = Vector([coord for coord in vertex_feature.normal])

                face_uvs.append((uv.x, -uv.y))
                face_normals.append(normal)

            extend_uvs(face_uvs)
            extend_normals(face_normals)
            append_face(face)
            append_material_index(polygon.material_index)

    return MeshData(vertices, faces, normals, uvs, materials, material_indices)


def parse_multi_resolution_mesh(mrm: MultiResolutionMesh, scale: float = 0.01) -> MeshData:
    vertices, uvs, faces = [], [], []
    normals, materials, material_indices = [], [], []
    append_vertex, append_face = vertices.append, faces.append
    append_material_index = material_indices.append
    extend_normals, extend_uvs = normals.extend, uvs.extend

    for mat in mrm.material:
        mat_color = mat.color
        r, g, b, a = mat_color.r, mat_color.g, mat_color.b, mat_color.a
        inv255 = 1.0 / 255.0
        color = (
            r * inv255,
            g * inv255,
            b * inv255,
            a * inv255,
        )
        materials.append(MaterialData(mat.name, color, mat.texture))

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
    visual_name = vob.visual.name.lower()
    visual: VisualDecal = vob.visual  # type: ignore
    material = MaterialData(trim_suffix(visual_name), (1.0, 1.0, 1.0, 1.0), visual_name)
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

    normals = [Vector((0, 0, 1))] * 3 * 2  # 6 normals: 3 per triangle × 2 sides
    normals += [Vector((0, 0, -1))] * 3 * 2

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

        faces.extend(tuple(idx + vertex_offset for idx in face) for face in mesh.faces)
        material_indices.extend(idx + material_offset for idx in mesh.material_indices)
        materials.extend(mesh.materials)
        vertices.extend(vertices_relative_to_parent)
        normals.extend(mesh.normals)
        uvs.extend(mesh.uvs)

        vertex_offset += len(mesh.vertices)
        material_offset += len(mesh.materials)

    return MeshData(vertices, faces, normals, uvs, materials, material_indices), (
        vertex_offset,
        material_offset,
    )


def parse_model_mesh(mdm: ModelMesh, mdh: ModelHierarchy, scale: float = 0.01) -> MeshData:
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
        vertices.extend(mesh.vertices)
        normals.extend(mesh.normals)
        uvs.extend(mesh.uvs)

        vertex_offset += len(mesh.vertices)
        material_offset += len(mesh.materials)

    return MeshData(vertices, faces, normals, uvs, materials, material_indices)


def parse_morph_mesh(mmb: MorphMesh, scale: float = 0.01) -> MeshData:
    return parse_multi_resolution_mesh(mmb.mesh, scale)


def parse_model(mdl: Model, scale: float = 0.01) -> MeshData:
    return parse_model_mesh(mdl.mesh, mdl.hierarchy, scale)
