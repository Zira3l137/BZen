from dataclasses import dataclass, field
from logging import error, info
from os import scandir
from pathlib import Path
from typing import Dict, Optional, Tuple

import bpy

from error import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class MaterialData:
    name: str
    color: Tuple[float, float, float, float]
    texture: Optional[str] = field(default=None)


def index_textures(game_directory: Path) -> Result[Dict[str, str], Exception]:
    try:
        textures = {}

        def index_dir(dir, storage):
            for entry in scandir(dir):
                if not entry.is_dir():
                    if entry.name.lower().endswith(".tga"):
                        storage[entry.name.lower()] = str(entry.path)
                else:
                    index_dir(entry.path, storage)

        index_dir(game_directory / "_work" / "data" / "textures", textures)

    except Exception as e:
        error(f"Failed to index textures")
        return Err(e)

    info(f"Indexed {len(textures)} textures")
    return Ok(textures)


def create_material(material: MaterialData, textures: Dict[str, str]) -> Result[bpy.types.Material, Exception]:
    try:
        if existing_material := bpy.data.materials.get(material.name):
            return Ok(existing_material)

        if not material.texture:
            return Ok(bpy.data.materials.new(name=material.name))

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
        tex_path = str(textures[texture])

        image = bpy.data.images.get(tex_path) or bpy.data.images.load(tex_path)
        texture_node.image = image  # type: ignore

        bmat.diffuse_color = material.color
        shader.inputs[12].default_value = 0  # type: ignore # Metallic
        shader.inputs[2].default_value = 1  # type: ignore # Roughness

        bmat.blend_method = "CLIP"
        bmat.shadow_method = "CLIP"  # type: ignore

        links.new(texture_node.outputs["Color"], shader.inputs["Base Color"])
        links.new(texture_node.outputs["Alpha"], shader.inputs["Alpha"])
        links.new(shader.outputs["BSDF"], output.inputs["Surface"])

    except Exception as e:
        error(f"Failed to create material {material.name}")
        return Err(e)

    return Ok(bmat)
