from dataclasses import dataclass, field
from logging import error, info, warning
from typing import Dict, Optional

import bpy
import numpy as np  # numpy is bundled with Blender
from mathutils import Quaternion, Vector
from visual import MaterialData, MeshData, VisualLoader
from zenkit import Texture


@dataclass(frozen=True, slots=True)
class BlenderObjectData:
    name: str = field(default_factory=str)
    mesh: Optional[MeshData] = None
    position: Vector = field(default_factory=Vector)
    rotation: Quaternion = field(default_factory=Quaternion)


def create_texture(name: str, texture: Texture) -> bpy.types.Image:
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
    if existing_material := bpy.data.materials.get(material.name):
        return existing_material

    if not material.texture:
        bmat = bpy.data.materials.new(name=material.name)
        bmat.diffuse_color = material.color
        return bmat

    bmat = bpy.data.materials.new(name=material.name)
    bmat.use_nodes = True
    bmat.use_backface_culling = True
    bmat.blend_method = "CLIP"
    try:
        bmat.shadow_method = "CLIP"  # type: ignore
    except AttributeError:
        pass

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
    image = (
        (bpy.data.images.get(texture_name) or create_texture(texture_name, texture_obj())) if texture_obj else None  # type: ignore
    )
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
    unique_name: str, mesh_data: MeshData, visuals_cache: Dict[str, VisualLoader]
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(unique_name)
    mesh.from_pydata(mesh_data.vertices, [], mesh_data.faces)  # type: ignore
    mesh.normals_split_custom_set(mesh_data.normals)  # type: ignore

    if mesh_data.uvs:
        uv_layer = mesh.uv_layers.new(name="UVMap")
        flat_uvs = [coord for uv in mesh_data.uvs for coord in uv]
        uv_layer.data.foreach_set("uv", flat_uvs)

    if not mesh_data.materials:
        warning("Mesh has no materials")
    else:
        for material in mesh_data.materials:
            mat = bpy.data.materials.get(material.name)
            if not mat:
                mat = create_material(material, visuals_cache)
            mesh.materials.append(mat)
        mesh.polygons.foreach_set("material_index", mesh_data.material_indices)

    mesh.update()

    obj = bpy.data.objects.new(unique_name, mesh)
    obj.rotation_mode = "QUATERNION"
    bpy.context.collection.objects.link(obj)

    return obj


def create_obj_from_vob_data(
    unique_name: str, vob_data: BlenderObjectData, visuals_cache: Dict[str, VisualLoader]
) -> Optional[bpy.types.Object]:
    vob_mesh = vob_data.mesh

    if not vob_mesh:
        error(f"VOB {unique_name} has no mesh, skipping")
        return None

    obj = create_obj_from_mesh(unique_name, vob_mesh, visuals_cache)
    obj.location = vob_data.position or Vector((0, 0, 0))
    obj.rotation_quaternion = vob_data.rotation or Quaternion()

    return obj


def create_instance_from_vob_data(
    unique_name: str, obj: bpy.types.Object, vob_data: BlenderObjectData
) -> bpy.types.Object:
    instance = bpy.data.objects.new(unique_name, obj.data)
    instance.rotation_mode = "QUATERNION"
    instance.location = vob_data.position or Vector((0, 0, 0))
    instance.rotation_quaternion = vob_data.rotation or Quaternion()

    bpy.context.collection.objects.link(instance)
    return instance


def create_vobs(vobs: Dict[str, BlenderObjectData], visuals_cache: Dict[str, VisualLoader]):
    success_count = 0
    obj_cache: Dict[int, bpy.types.Object] = {}  # keyed by id(mesh), not mesh content

    for vob_name, vob_data in vobs.items():
        vob_mesh = vob_data.mesh
        mesh_key = id(vob_mesh)
        result = None

        if mesh_key in obj_cache:
            existing_obj = obj_cache[mesh_key]
            result = create_instance_from_vob_data(vob_name, existing_obj, vob_data)
        else:
            result = create_obj_from_vob_data(vob_name, vob_data, visuals_cache)
            if not result:
                warning(f"VOB {vob_name} has no mesh, skipping")
                continue
            obj_cache[mesh_key] = result

        success_count += 1

    bpy.context.view_layer.update()
    info(f"Created {success_count} VOBs")
