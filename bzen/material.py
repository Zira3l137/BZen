from dataclasses import dataclass, field
from logging import error, info
from os import scandir
from pathlib import Path
from typing import Dict, Optional, Tuple


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
