import math
from dataclasses import dataclass, field
from enum import StrEnum
from logging import error, info
from os import scandir
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TypeAlias

from mathutils import Matrix, Vector
from utils import canonical_case_path, suffix, trim_suffix, with_suffix
from zenkit import (Model, ModelHierarchy, ModelMesh, MorphMesh,
                    MultiResolutionMesh, Texture, Vfs, VfsNode, VirtualObject,
                    VisualDecal, World)

VobVisual: TypeAlias = MultiResolutionMesh | ModelMesh | Model | MorphMesh | ModelHierarchy | Texture
VisualLoader: TypeAlias = Callable[[], Optional[VobVisual]]


class VisualExtension(StrEnum):
    MRM = "mrm"
    MDL = "mdl"
    MDM = "mdm"
    MMB = "mmb"
    MDH = "mdh"
    TEX = "tex"


compiled = {
    "3ds": VisualExtension.MRM,
    "asc": VisualExtension.MDL,
    "mds": VisualExtension.MDM,
    "mms": VisualExtension.MMB,
    "tga": VisualExtension.TEX,
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
    try:
        paths = [
            canonical_case_path(game_directory / "_work" / "data" / category / "_compiled")
            for category in VISUAL_CATEGORIES
        ]
        stack = [entry for path in paths for entry in scandir(path)]
        while stack:
            entry = stack.pop()
            entry_ext = suffix(entry.name).lower()
            if not entry.is_dir():
                if entry_ext in [ve.value for ve in VisualExtension]:
                    extension = VisualExtension(entry_ext)
                    name = entry.name.lower()
                    if extension is VisualExtension.TEX:
                        name = with_suffix(name.replace("-c.", "."), "tga", True)
                    visuals[name] = lambda path=entry.path, extension=VisualExtension(entry_ext): load_visual(
                        path, extension
                    )
            else:
                stack.extend([entry for entry in scandir(entry.path)])

    except Exception as e:
        error("Failed to index visuals from disk")
        raise e

    info(f"Indexed from disk: {len(visuals)}")


def index_visuals_from_archives(game_directory: Path, visuals: Dict[str, VisualLoader]):
    try:
        paths = [canonical_case_path(game_directory / "data" / path) for path in VISUAL_ARCHIVES]

        for path in paths:
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
                    visuals[name] = lambda node=node, extension=VisualExtension(extension): load_visual(node, extension)
                if node.is_dir():
                    stack.extend(node.children)

    except Exception as e:
        error("Failed to index visuals from archives")
        raise e

    info(f"Indexed from archives: {len(visuals)}")


def load_visual(path: str | Path | VfsNode, extension: VisualExtension) -> Optional[VobVisual]:
    try:
        match extension:

            case VisualExtension.MRM:
                return MultiResolutionMesh.load(path)

            case VisualExtension.MDL:
                return Model.load(path)

            case VisualExtension.MDM:
                return ModelMesh.load(path)

            case VisualExtension.MMB:
                return MorphMesh.load(path)

            case VisualExtension.MDH:
                return ModelHierarchy.load(path)

            case VisualExtension.TEX:
                return Texture.load(path)

    except:
        error("Failed to load visual")
        return None


def parse_visual_data(name: str, cache: Dict[str, VisualLoader], scale: float = 0.01) -> Optional[MeshData]:
    try:
        extension = suffix(name).lower()
        if extension == "" or extension not in compiled:
            return None

        compiled_name = with_suffix(name, compiled[extension], True).lower()

        match extension:

            case "3ds":
                mrm = cache[compiled_name]()
                return parse_multi_resolution_mesh(mrm, scale)  # type: ignore

            case "mds":
                mdm = cache[compiled_name]()
                mdh = cache[with_suffix(name, "mdh", True).lower()]()
                return parse_model_mesh(mdm, mdh, scale)  # type: ignore

            case "asc":
                mdl = cache[compiled_name]()
                return parse_model(mdl, scale)  # type: ignore

            case "mms":
                mmb = cache[compiled_name]()
                return parse_morph_mesh(mmb, scale)  # type: ignore

    except Exception as e:
        error(f"Failed to parse visual data for {name}: {e}")
        raise e


def parse_visual_data_from_vob(
    vob: VirtualObject, cache: Dict[str, VisualLoader], scale: float = 0.01
) -> Optional[MeshData]:
    try:
        if vob.visual is None:
            return None

        name = vob.visual.name.lower()
        mesh_data = parse_visual_data(name, cache, scale)
        if not mesh_data:
            return None

    except Exception as e:
        error(f"Failed to parse visual data for {vob.name}: {e}")
        raise e

    return mesh_data


def parse_world_mesh(wrld: World, scale: float = 0.01) -> MeshData:
    try:
        bsp, mesh = wrld.bsp_tree, wrld.mesh
        vertices, uvs, faces = [], [], []
        normals, materials, material_indices = [], [], []

        for mat in mesh.materials:
            mat_color = mat.color
            color = (
                mat_color.r / 255,
                mat_color.g / 255,
                mat_color.b / 255,
                mat_color.a / 255,
            )
            materials.append(MaterialData(mat.name, color, mat.texture))

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

                for vertex_index in [0, index, index + 1]:

                    position_index = position_indices[vertex_index]
                    feature_index = feature_indices[vertex_index]

                    position = positions[position_index] * scale
                    position = (position.x, position.z, position.y)
                    position_hash = hash(position)

                    if position_hash not in vertex_cache:
                        vertex_cache[position_hash] = len(vertices)
                        vertices.append(position)

                    face.append(vertex_cache[position_hash])

                    vertex_feature = features[feature_index]
                    uv = vertex_feature.texture
                    normal = Vector([coord for coord in vertex_feature.normal])

                    uvs.append((uv.x, -uv.y))
                    normals.append(normal)

                faces.append(face)
                material_indices.append(polygon.material_index)

    except Exception as e:
        raise e

    return MeshData(vertices, faces, normals, uvs, materials, material_indices)


def parse_multi_resolution_mesh(mrm: MultiResolutionMesh, scale: float = 0.01) -> MeshData:
    try:
        vertices, uvs, faces = [], [], []
        normals, materials, material_indices = [], [], []

        for mat in mrm.material:
            mat_color = mat.color
            color = (
                mat_color.r / 255,
                mat_color.g / 255,
                mat_color.b / 255,
                mat_color.a / 255,
            )
            materials.append(MaterialData(mat.name, color, mat.texture))

        positions, vertex_cache = [Vector((pos.x, pos.y, pos.z)) for pos in mrm.positions], {}
        for submesh_index, submesh in enumerate(mrm.submeshes):
            wedges = submesh.wedges
            triangles = submesh.triangles

            for triangle in triangles:
                triangle_wedges = triangle.wedges
                face_indices = []
                for i in range(3):
                    wedge = wedges[triangle_wedges[i]]
                    normals.append(Vector((wedge.normal.x, wedge.normal.z, wedge.normal.y)))
                    pos = positions[wedge.index] * scale
                    blender_pos = (float(pos.x), float(pos.z), float(pos.y))

                    if blender_pos not in vertex_cache:
                        face_index = len(vertices)
                        face_indices.append(face_index)

                        vertices.append(Vector(blender_pos))
                        vertex_cache[blender_pos] = face_index
                    else:
                        face_indices.append(vertex_cache[blender_pos])

                    uvs.append((wedge.texture.x, -wedge.texture.y))
                material_indices.append(submesh_index)
                faces.append(face_indices)

    except Exception as e:
        error("Failed to parse multi-resolution mesh")
        raise e

    return MeshData(vertices, faces, normals, uvs, materials, material_indices)


def parse_decal_mesh(vob: VirtualObject, scale: float = 0.01) -> Optional[MeshData]:
    try:
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

    except Exception as e:
        error(f"Failed to parse decal data for {vob.name}: {e}")
        return None

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
    try:
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

    except Exception as e:
        error("Failed to parse mesh attachments.")
        raise e

    return MeshData(vertices, faces, normals, uvs, materials, material_indices), (
        vertex_offset,
        material_offset,
    )


def parse_model_mesh(mdm: ModelMesh, mdh: ModelHierarchy, scale: float = 0.01) -> MeshData:
    try:
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

    except Exception as e:
        error("Failed to parse model")
        raise e

    return MeshData(vertices, faces, normals, uvs, materials, material_indices)


def parse_morph_mesh(mmb: MorphMesh, scale: float = 0.01) -> MeshData:
    try:
        return parse_multi_resolution_mesh(mmb.mesh, scale)

    except Exception as e:
        error("Failed to parse morph mesh")
        raise e


def parse_model(mdl: Model, scale: float = 0.01) -> MeshData:
    try:
        return parse_model_mesh(mdl.mesh, mdl.hierarchy, scale)

    except Exception as e:
        error("Failed to parse model")
        raise e
