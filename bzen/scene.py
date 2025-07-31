from dataclasses import dataclass, field
from logging import error, info, warning
from typing import Dict, Optional

import bpy
from material import MaterialData
from mathutils import Euler, Vector
from visual import MeshData


@dataclass(frozen=True, slots=True)
class BlenderObjectData:
    name: str = field(default_factory=str)
    mesh: Optional[MeshData] = None
    position: Vector = field(default_factory=Vector)
    rotation: Euler = field(default_factory=Euler)


def create_material(material: MaterialData, textures: Dict[str, str]) -> bpy.types.Material:
    try:
        if existing_material := bpy.data.materials.get(material.name):
            return existing_material

        if not material.texture:
            bmat = bpy.data.materials.new(name=material.name)
            bmat.diffuse_color = material.color
            return bmat

        bmat = bpy.data.materials.new(name=material.name)
        bmat.use_nodes = True
        bmat.use_backface_culling = True

        nodes = bmat.node_tree.nodes
        links = bmat.node_tree.links

        for node in nodes:
            nodes.remove(node)

        shader = nodes.new(type="ShaderNodeBsdfPrincipled")
        shader.location = (-0, 0)

        output = nodes.new(type="ShaderNodeOutputMaterial")
        output.location = (400, 0)

        texture_node = nodes.new(type="ShaderNodeTexImage")
        texture_node.location = (-400, 0)

        texture = material.texture.lower()

        tex_path = None
        if texture in textures:
            tex_path = textures[texture]
        elif texture in textures.values():
            tex_path = textures["default.tga"]

        image = bpy.data.images.get(tex_path) or bpy.data.images.load(tex_path) if tex_path else None
        texture_node.image = image  # type: ignore

        bmat.diffuse_color = material.color
        shader.inputs[12].default_value = 0  # type: ignore # Metallic
        shader.inputs[2].default_value = 1  # type: ignore # Roughness

        bmat.blend_method = "CLIP"
        try:
            bmat.shadow_method = "CLIP"  # type: ignore
        except AttributeError:
            pass

        links.new(texture_node.outputs["Color"], shader.inputs["Base Color"])
        links.new(texture_node.outputs["Alpha"], shader.inputs["Alpha"])
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    except Exception as e:
        error(f"Failed to create material {material.name}")
        raise e

    return bmat


def create_obj_from_mesh(unique_name: str, mesh_data: MeshData, textures: Dict[str, str]) -> bpy.types.Object:
    try:
        mesh = bpy.data.meshes.new(unique_name)
        mesh.from_pydata(mesh_data.vertices, [], mesh_data.faces)  # type: ignore
        mesh.normals_split_custom_set(mesh_data.normals)  # type: ignore

        if mesh_data.uvs:
            uv_layer = mesh.uv_layers.new(name="UVMap")
            for i in range(len(uv_layer.data)):
                uv_layer.data[i].uv = mesh_data.uvs[i]

        for material in mesh_data.materials:
            mat = bpy.data.materials.get(material.name)
            if not mat:
                mat = create_material(material, textures)
            mesh.materials.append(mat)

        for index, polygon in enumerate(mesh.polygons):
            if not len(mesh_data.materials):
                warning("Mesh has no materials")
                continue

            polygon.material_index = mesh_data.material_indices[index]

        mesh.update()

        obj = bpy.data.objects.new(unique_name, mesh)
        bpy.context.collection.objects.link(obj)
    except Exception as e:
        error("Failed to create object from mesh")
        raise e

    return obj


def create_obj_from_vob_data(
    unique_name: str, vob_data: BlenderObjectData, textures: Dict[str, str]
) -> Optional[bpy.types.Object]:
    try:
        vob_mesh = vob_data.mesh

        if not vob_mesh:
            error(f"VOB {unique_name} has no mesh, skipping")
            return None

        obj = create_obj_from_mesh(unique_name, vob_mesh, textures)
        obj.location = vob_data.position or Vector((0, 0, 0))
        obj.rotation_euler = vob_data.rotation or Euler((0, 0, 0))
    except Exception as e:
        error(f"Failed to create object {unique_name}")
        raise e

    return obj


def create_instance_from_vob_data(
    unique_name: str, obj: bpy.types.Object, vob_data: BlenderObjectData
) -> bpy.types.Object:
    try:
        instance = bpy.data.objects.new(unique_name, obj.data)
        instance.location = vob_data.position or Vector((0, 0, 0))
        instance.rotation_euler = vob_data.rotation or Euler((0, 0, 0))

        bpy.context.collection.objects.link(instance)
    except Exception as e:
        error(f"Failed to create instance {unique_name}")
        raise e

    return instance


def create_vobs(vobs: Dict[str, BlenderObjectData], textures: Dict[str, str]):
    try:
        success_count = 0
        mesh_cache = set()
        obj_cache = {}

        for vob_name, vob_data in vobs.items():
            mesh_hash = hash(vob_data.mesh)
            result = None

            if mesh_hash in mesh_cache:
                existing_obj = obj_cache[mesh_hash]
                result = create_instance_from_vob_data(vob_name, existing_obj, vob_data)
            else:
                result = create_obj_from_vob_data(vob_name, vob_data, textures)
                if not result:
                    warning(f"VOB {vob_name} has no mesh, skipping")
                    continue

                mesh_cache.add(mesh_hash)
                obj_cache[mesh_hash] = result

            success_count += 1

    except Exception as e:
        error("Failed to create VOBs")
        raise e

    bpy.context.view_layer.update()
    info(f"Created {success_count} VOBs")
