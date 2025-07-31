from dataclasses import dataclass, field
from logging import error, info
from os import scandir
from pathlib import Path
from typing import Dict, Optional, Tuple

import bpy


@dataclass(frozen=True, slots=True)
class MaterialData:
    name: str
    color: Tuple[float, float, float, float]
    texture: Optional[str] = field(default=None)

    def __hash__(self):
        return hash(self.name) + hash(self.color) + hash(self.texture)


def index_textures(game_directory: Path) -> Dict[str, str]:
    try:
        textures = {}
        stack = [entry for entry in scandir(game_directory / "_work" / "data" / "textures")]

        while stack:
            entry = stack.pop()
            if not entry.is_dir():
                if entry.name.lower().endswith(".tga"):
                    textures[entry.name.lower()] = str(entry.path)
            else:
                stack.extend([entry for entry in scandir(entry.path)])

    except Exception as e:
        error(f"Failed to index textures")
        raise e

    info(f"Indexed {len(textures)} textures")
    return textures


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
