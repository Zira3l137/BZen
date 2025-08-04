import sys
from argparse import ArgumentParser, Namespace
from os import scandir
from pathlib import Path
from subprocess import run

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
    parser.add_argument("scale", type=float, default=0.01, help="Scale factor (default: 0.01)")
    parser.add_argument("-w", "--waynet", action="store_true", help="Parse waynet (default: False)")
    parser.add_argument("-v", "--verbosity", type=int, default=0, help="Verbosity level (0-3) (default: 0)")

    return parser.parse_args(args)


def install_dependencies_locally():
    python = Path(sys.executable)
    run([python, "-m", "pip", "install", "-r", "requirements.txt"])


def blender_clean_scene():
    scene = bpy.context.scene

    if scene:

        for child_collection in scene.collection.children:
            scene.collection.children.unlink(child_collection)

        for child_object in scene.collection.objects:
            scene.collection.objects.unlink(child_object)

        bpy.ops.outliner.orphans_purge(do_recursive=True)


def blender_save_changes(*args, **kwargs):
    bpy.ops.wm.save_mainfile(*args, **kwargs)
