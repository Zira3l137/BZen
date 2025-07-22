from dataclasses import dataclass, field
from enum import StrEnum
from logging import error, info, warning
from os import scandir
from pathlib import Path
from typing import Callable, Dict, List, Tuple, TypeAlias

from mathutils import Vector
from zenkit import (Model, ModelHierarchy, ModelMesh, MorphMesh,
                    MultiResolutionMesh, Vfs, VfsNode, VirtualObject,
                    VisualType, World)

from error import Err, Ok, Option, Result, none, some
from exceptions import NoVisualDataException, UnknownExtensionException
from material import MaterialData
from utils import abgr_to_rgba, suffix, with_suffix

VobVisual: TypeAlias = (
    Option[MultiResolutionMesh] | Option[ModelMesh] | Option[Model] | Option[MorphMesh] | Option[ModelHierarchy]
)
VisualLoader: TypeAlias = Callable[[], VobVisual]


class VisualExtension(StrEnum):
    MRM = "mrm"
    MDL = "mdl"
    MDM = "mdm"
    MMB = "mmb"
    MDH = "mdh"


compiled = {
    "3ds": VisualExtension.MRM,
    "asc": VisualExtension.MDL,
    "mds": VisualExtension.MDM,
    "mms": VisualExtension.MMB,
}


@dataclass(frozen=True, slots=True)
class MeshData:
    vertices: list[Vector] = field(default_factory=list)
    faces: List[Tuple[int, int, int]] = field(default_factory=list)
    normals: List[Vector] = field(default_factory=list)
    uvs: List[Tuple[float, float]] = field(default_factory=list)
    materials: List[MaterialData] = field(default_factory=list)
    material_indices: List[int] = field(default_factory=list)


def index_visuals(game_directory: Path) -> Result[Dict[str, VisualLoader], Exception]:
    try:
        visuals = {}
        index_visuals_from_disk(game_directory, visuals).unwrap()
        index_visuals_from_archives(game_directory, visuals).unwrap()
    except Exception as e:
        error("Failed to index visuals")
        return Err(e)

    info(f"Indexed {len(visuals)} visuals")
    return Ok(visuals)


def index_visuals_from_disk(game_directory: Path, visuals: Dict[str, VisualLoader]) -> Result[None, Exception]:
    try:
        paths = [game_directory / "_work" / "data" / path / "_compiled" for path in ("meshes", "anims")]

        def index_dir(dir: str | Path, storage: Dict[str, VisualLoader]):
            for entry in scandir(dir):
                entry_ext = suffix(entry.name).lower()
                if not entry.is_dir():
                    if entry_ext in [ve.value for ve in VisualExtension]:
                        storage[entry.name.lower()] = lambda path=entry.path, extension=VisualExtension(
                            entry_ext
                        ): load_visual(path, extension)
                else:
                    index_dir(entry.path, storage)

        for path in paths:
            index_dir(path, visuals)

    except Exception as e:
        error("Failed to index visuals from disk")
        return Err(e)

    info(f"Indexed from disk: {len(visuals)}")
    return Ok(None)


def index_visuals_from_archives(game_directory: Path, visuals: Dict[str, VisualLoader]) -> Result[None, Exception]:
    try:
        paths = [
            game_directory / "data" / path
            for path in ("meshes.vdf", "meshes_addon.vdf", "anims.vdf", "anims_addon.vdf")
        ]

        def index_archive(root: VfsNode, storage: Dict[str, VisualLoader]):
            stack = [root]
            while stack:
                node = stack.pop()
                extension = suffix(node.name).lower()
                if extension in [ve.value for ve in VisualExtension]:
                    storage[node.name.lower()] = lambda node=node, extension=VisualExtension(extension): load_visual(
                        node, extension
                    )
                if node.is_dir():
                    stack.extend(node.children)

        for path in paths:
            vfs = Vfs()
            vfs.mount_disk(str(path))
            index_archive(vfs.root, visuals)

    except Exception as e:
        error("Failed to index visuals from archives")
        return Err(e)

    info(f"Indexed from archives: {len(visuals)}")
    return Ok(None)


def load_visual(path: str | Path | VfsNode, extension: VisualExtension) -> VobVisual:
    try:
        match extension:

            case VisualExtension.MRM:
                return some(MultiResolutionMesh.load(path))

            case VisualExtension.MDL:
                return some(Model.load(path))

            case VisualExtension.MDM:
                return some(ModelMesh.load(path))

            case VisualExtension.MMB:
                return some(MorphMesh.load(path))

            case VisualExtension.MDH:
                return some(ModelHierarchy.load(path))

    except:
        error("Failed to load visual")
        return none()


def parse_visual_data(
    obj: VirtualObject, cache: Dict[str, VisualLoader], scale: float = 0.01
) -> Result[MeshData, NoVisualDataException | UnknownExtensionException]:
    try:
        if obj.visual is None:
            return Err(NoVisualDataException(f"object has no visual: {obj.name}"))

        name = obj.visual.name
        extension = suffix(name).lower()
        if extension not in compiled:
            return Err(UnknownExtensionException(f"unknown visual extension: {extension}"))

        compiled_name = with_suffix(name, compiled[extension], True).lower()
        match obj.visual.type:

            case VisualType.MULTI_RESOLUTION_MESH:
                mrm = cache[compiled_name]().unwrap()
                return parse_multi_resolution_mesh(mrm, scale).map_err(lambda err: NoVisualDataException(str(err)))  # type: ignore

            case VisualType.MESH:
                return Ok(MeshData([], [], [], [], []))
                # mdm = cache[compiled_name]().unwrap()
                # mdh = cache[with_suffix(name, "mdh", True)]().unwrap()
                # return parse_mesh(mdm, mdh, scale).map_err(lambda err: NoVisualDataException(str(err)))  # type: ignore

            case VisualType.MODEL:
                return Ok(MeshData([], [], [], [], []))
                # mdl = cache[compiled_name]().unwrap()
                # return parse_model(mdl, scale).map_err(lambda err: NoVisualDataException(str(err)))  # type: ignore

            case VisualType.MORPH_MESH:
                mmb = cache[compiled_name]().unwrap()
                return parse_morph_mesh(mmb, scale).map_err(lambda err: NoVisualDataException(str(err)))  # type: ignore

            case _:
                return Err(NoVisualDataException(f"unknown visual type: {obj.visual.type}"))

    except Exception as e:
        error(f"Failed to parse visual data")
        return Err(NoVisualDataException(str(e)))


def parse_world_mesh(wrld: World, scale: float = 0.01) -> Result[MeshData, Exception]:
    try:
        bsp, mesh = wrld.bsp_tree, wrld.mesh
        vertices, uvs, faces, normals, material_indices = [], [], [], [], []
        materials = [MaterialData(mat.name, abgr_to_rgba(mat.color), mat.texture) for mat in mesh.materials]  # type: ignore

        vertex_cache, polygon_cache = {}, set()
        positions, features, polygons, leaf_polygon_indices = (
            mesh.positions,
            mesh.features,
            mesh.polygons,
            bsp.leaf_polygon_indices,
        )

        for leaf_index in leaf_polygon_indices:
            polygon = polygons[leaf_index]
            position_indices, feature_indices = polygon.position_indices, polygon.feature_indices

            if polygon in polygon_cache or polygon.is_portal or polygon.is_ghost_occluder or polygon.is_lod:
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
        return Err(e)

    return Ok(MeshData(vertices, faces, normals, uvs, materials, material_indices))


def parse_multi_resolution_mesh(mrm: MultiResolutionMesh, scale: float = 0.01) -> Result[MeshData, Exception]:
    try:
        vertices, faces, uvs, normals, material_indices = [], [], [], [], []
        materials = [MaterialData(mat.name, abgr_to_rgba(mat.color), mat.texture) for mat in mrm.material]  # type: ignore

        positions, vertex_cache = mrm.positions, {}
        for submesh_index, submesh in enumerate(mrm.submeshes):
            wedges = submesh.wedges

            for triangle in submesh.triangles:
                triangle_wedges = triangle.wedges
                face_wedges = [wedges[triangle_wedges[i]] for i in range(3)]

                face_indices = []
                for wedge in face_wedges:
                    normals.append(Vector((wedge.normal.x, wedge.normal.z, wedge.normal.y)))
                    pos = positions[wedge.index] * scale
                    blender_pos = (float(pos.x), float(pos.z), float(pos.y))
                    pos_hash = hash(blender_pos)

                    if pos_hash not in vertex_cache:
                        face_index = len(vertices)
                        face_indices.append(face_index)

                        vertices.append(blender_pos)
                        vertex_cache[pos_hash] = face_index
                    else:
                        face_indices.append(vertex_cache[pos_hash])

                    uvs.append((wedge.texture.x, -wedge.texture.y))
                material_indices.append(submesh_index)
                faces.append(face_indices)

        return Ok(MeshData(vertices, faces, normals, uvs, materials, material_indices))

    except Exception as e:
        error("Failed to parse multi-resolution mesh")
        return Err(e)


# TODO: Implement
def parse_mesh(mdm: ModelMesh, mdh: ModelHierarchy, scale: float = 0.01) -> Result[MeshData, Exception]:
    warning("MDM is not supported yet")
    return Err(Exception("MDM is not supported yet"))


# TODO: Implement
def parse_model(mdl: Model, scale: float = 0.01) -> Result[MeshData, Exception]:
    warning("MDL is not supported yet")
    return Err(Exception("MDL is not supported yet"))


def parse_morph_mesh(mmb: MorphMesh, scale: float = 0.01) -> Result[MeshData, Exception]:
    return parse_multi_resolution_mesh(mmb.mesh, scale)
