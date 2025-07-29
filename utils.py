import bpy
from pathlib import Path

def with_suffix(path: str, suffix: str, replace: bool = False) -> str:
    result = path.rsplit(".", 1)[0] if replace else path
    return f"{result}.{suffix}"


def suffix(path: str, dot: bool = False) -> str:
    prefix = "." if dot else ""
    return f"{prefix}{path.rsplit('.', 1)[-1]}"


def trim_suffix(path: str) -> str:
    return path.rsplit(".", 1)[0]

def find_case_insensitive_path(base: Path | str, *relative_parts: str) -> Path:
    current = base if isinstance(base, Path) else Path(base)
    
    for part in relative_parts:
        matches = [entry for entry in current.iterdir() if entry.name.lower() == part.lower()]
        
        if not matches:
            raise FileNotFoundError(f"Could not find path component '{part}' under '{current}'")
        elif len(matches) > 1:
            raise RuntimeError(f"Ambiguous path: multiple matches found for '{part}' under '{current}'")
        
        current = matches[0]
        
    return current

def blender_save_changes(*args, **kwargs):
    bpy.ops.wm.save_mainfile(*args, **kwargs)
