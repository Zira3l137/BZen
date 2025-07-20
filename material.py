from dataclasses import dataclass, field
from logging import error, info
from os import scandir
from pathlib import Path
from typing import Dict, Optional, Tuple

from error import Err, Ok, Result


@dataclass(frozen=True, slots=True)
class MaterialData:
    name: str
    texture: Optional[str] = field(default=None)
    color: Tuple[float, float, float, float]


def index_textures(game_directory: Path) -> Result[Dict[str, str], Exception]:
    try:
        textures = {}

        def index_dir(dir, storage):
            for entry in scandir(dir):
                if entry.is_file() and entry.name.lower().endswith(".tga"):
                    storage[entry.name] = str(entry.path)
                else:
                    index_dir(entry.path, storage)

        index_dir(game_directory / "_work" / "data" / "textures", textures)

    except Exception as e:
        error(f"Failed to index textures")
        return Err(e)

    info(f"Indexed {len(textures)} textures")
    return Ok(textures)
