from os import scandir
from pathlib import Path

import bpy


def with_suffix(path: str, suffix: str, replace: bool = False) -> str:
    result = path.rsplit(".", 1)[0] if replace else path
    return f"{result}.{suffix}"


def suffix(path: str, dot: bool = False) -> str:
    prefix = "." if dot else ""
    return f"{prefix}{path.rsplit('.', 1)[-1]}"


def trim_suffix(path: str) -> str:
    return path.rsplit(".", 1)[0]


def canonical_case_path(path: Path | str) -> Path:
    if isinstance(path, str):
        path = Path(path)

    if path.is_absolute():
        parts = path.parts
        current = Path(parts[0])  # root ("/" on POSIX)
        parts = parts[1:]
    else:
        current = Path.cwd()
        parts = path.parts

    for part in parts:
        try:
            entries = list(scandir(current))
        except FileNotFoundError:
            raise FileNotFoundError(f"Directory does not exist: {current}")

        matches = [e for e in entries if e.name.lower() == part.lower()]

        if not matches:
            raise FileNotFoundError(f"No case-insensitive match for {part} in {current}")

        current = Path(matches[0].path)

    return current.resolve()


def blender_save_changes(*args, **kwargs):
    bpy.ops.wm.save_mainfile(*args, **kwargs)
