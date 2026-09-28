"""
Utility functions for the BZen project.

This module contains helper functions that are used across the project:
- Path manipulation (canonical_case_path, with_suffix, etc.)
- Blender-specific operations (blender_parse_cli, blender_clean_scene)
- Dependency management (install_dependencies_locally)
"""

import sys
from argparse import ArgumentParser, Namespace
from os import scandir
from pathlib import Path
from logging import warning
from subprocess import run
from typing import Dict, TypeVar

import bpy

ZENKIT_URL = "git+https://github.com/Zira3l137/ZenKit4Py.git"

T = TypeVar("T")


def insert_unique(mapping: Dict[str, T], key: str, value: T) -> str:
    """
    Insert ``value`` into ``mapping`` without overwriting an existing entry.

    If ``key`` is already taken, the value is stored under the first free
    "key.001", "key.002", ... instead (Blender's own naming style) and a
    warning is logged. Returns the key actually used.
    """
    unique_key, counter = key, 0
    while unique_key in mapping:
        counter += 1
        unique_key = f"{key}.{counter:03d}"
    if unique_key != key:
        warning(f'Name "{key}" is already used, storing this object as "{unique_key}"')
    mapping[unique_key] = value
    return unique_key


def with_suffix(path: str, suffix: str, replace: bool = False) -> str:
    """
    Add a suffix to a filename.

    If replace is True, the existing suffix is replaced; otherwise
    the new suffix is appended after any existing suffix.

    Examples:
        with_suffix("image.tga", "backup") -> "image.tga.backup"
        with_suffix("image.tga", "backup", replace=True) -> "image.backup"
    """
    result = path.rsplit(".", 1)[0] if replace else path
    return f"{result}.{suffix}"


def suffix(path: str, dot: bool = False) -> str:
    """
    Extract the file extension from a path.

    If dot is True, the leading dot is included (e.g., ".tga");
    otherwise it is stripped (e.g., "tga").

    Returns an empty string if the path has no extension.
    """
    file_name = path.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in file_name:
        return ""
    prefix = "." if dot else ""
    return f"{prefix}{file_name.rsplit('.', 1)[-1]}"


def trim_suffix(path: str) -> str:
    """
    Remove the last suffix (file extension) from a path.

    Examples:
        trim_suffix("image.tga") -> "image"
        trim_suffix("image.backup.tga") -> "image.backup"
    """
    return path.rsplit(".", 1)[0]


def canonical_case_path(path: Path | str) -> Path:
    """
    Resolve a path using case-insensitive directory traversal.

    This function traverses each component of the path from the
    starting directory, matching directories case-insensitively.
    The result is an absolute path with the actual (case-pensitive)
    directory names.

    This is needed because the ZenKit game format uses directories with
    inconsistent casing (e.g., "_work/data" vs "data/_WORK").

    Raises FileNotFoundError if any component does not exist as a
    case-insensitive match.
    """
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
            raise FileNotFoundError(
                f"No case-insensitive match for {part} in {current}"
            )

        current = Path(matches[0].path)

    return current.resolve()


def blender_parse_cli() -> Namespace:
    """
    Args:
        input: Path to the input file
        game_directory: Path to the game directory
        output: Path to the output file
        scale: Scale factor (default: 0.01)
        waynet: Parse waynet (default: False)
        verbosity: Verbosity level (0-3) (default: 0)
    """
    args = sys.argv[sys.argv.index("--") + 1 :]
    parser = ArgumentParser()

    parser.add_argument("input", type=str, help="Input file name")
    parser.add_argument("game_directory", type=Path, help="Path to the game directory")
    parser.add_argument("output", type=Path, help="Path to the output file")
    parser.add_argument(
        "scale", type=float, default=0.01, help="Scale factor (default: 0.01)"
    )
    parser.add_argument(
        "-w", "--waynet", action="store_true", help="Parse waynet (default: False)"
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        default=0,
        help="Verbosity level (0-3) (default: 0)",
    )

    return parser.parse_args(args)


def install_dependencies_locally():
    """Install the ZenKit library from its GitHub repository."""
    python = Path(sys.executable)
    run([python, "-m", "pip", "install", ZENKIT_URL])


def blender_clean_scene():
    """Clear the active Blender scene's collection (objects and child collections).

    This function removes all objects and child collections from the
    current Blender scene's collection. It is used to ensure a clean
    scene before loading a new world.

    The function operates on bpy.context.scene.collection, which is the
    root collection of the current Blender scene.
    """
    scene = bpy.context.scene

    if scene:

        for child_collection in scene.collection.children:
            scene.collection.children.unlink(child_collection)

        for child_object in scene.collection.objects:
            scene.collection.objects.unlink(child_object)

        bpy.ops.outliner.orphans_purge(do_recursive=True)


def blender_save_changes(*args, **kwargs):
    """
    Save the current Blender scene to a file.

    This function wraps bpy.ops.wm.save_mainfile with the standard
    Blender save arguments. It is used to save the converted Blender
    scene to the specified output file path.

    The filepath argument is passed through the standard Blender
    save_mainfile operator.
    """
    bpy.ops.wm.save_mainfile(*args, **kwargs)
