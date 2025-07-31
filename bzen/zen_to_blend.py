import sys
from argparse import ArgumentError, ArgumentParser
from pathlib import Path
from typing import Any, Dict

script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.append(str(script_dir))
    sys.path.append(str(script_dir.parent / "venv" / "Lib" / "site-packages"))
    sys.path.append(str(script_dir.parent / ".venv" / "Lib" / "site-packages"))

from logging import error, info

from log import logging_setup
from scene import create_obj_from_mesh, create_vobs
from utils import blender_save_changes, canonical_case_path, suffix
from visual import index_visuals, parse_world_mesh
from vob import parse_blender_obj_data_from_world, parse_waynet
from zenkit import DaedalusVm, Vfs, VfsNode, World


def parse_args() -> Dict[str, Any]:
    """
    Args:
        input: Path to the input file
        game_directory: Path to the game directory
        output: Path to the output file
    """
    args = sys.argv[sys.argv.index("--") + 1 :]
    parser = ArgumentParser()

    try:
        parser.add_argument("input", type=str, help="Input file name")
        parser.add_argument("game-directory", type=Path, help="Path to the game directory")
        parser.add_argument("output", type=Path, help="Path to the output file")
        parser.add_argument("scale", type=float, default=0.01, help="Scale factor (default: 0.01)")
        parser.add_argument("-w", "--waynet", action="store_true", help="Parse waynet (default: False)")
        parser.add_argument("verbosity", type=int, default=0, help="Verbosity level (0-3) (default: 0)")

    except ArgumentError as e:
        raise e

    return parser.parse_args(args).__dict__


def load_world_from_archive(name: str, game_directory: Path) -> World:
    matches: Dict[Path, VfsNode] = {}
    for path in (
        canonical_case_path(game_directory / "data" / archive) for archive in ["worlds.vdf", "worlds_addon.vdf"]
    ):
        if not path.exists():
            continue

        vfs = Vfs()
        vfs.mount_disk(path)
        stack = [vfs.root]
        while stack:
            node = stack.pop()
            if node.name.lower() == name.lower():
                matches[path] = node
                break
            if node.is_dir():
                stack.extend(node.children)

    if matches:
        archive_names, nodes = tuple(matches.keys()), tuple(matches.values())
        info(f"Loading from archive: {archive_names[-1]}")
        return World.load(nodes[-1])
    else:
        raise Exception('Could not find world in "data/worlds.vdf" or "data/worlds_addon.vdf"')


def load_world_from_disk(name: str, game_directory: Path) -> World:
    info("Loading world from disk")
    for path in canonical_case_path(game_directory / "_work" / "data" / "worlds").glob("**/*.zen"):
        if path.name.lower() == name.lower():
            return World.load(path)
    else:
        raise Exception('Could not find world in ".../_work/data/worlds"')


def load_world(input: str, game_directory: Path) -> World:
    if suffix(input, True).lower() != ".zen":
        raise Exception("Input file must be a .zen file")

    if not ":" in input.lower():
        if len(Path(input).parts) == 1:
            try:
                return load_world_from_archive(str(input), game_directory)
            except Exception:
                return load_world_from_disk(str(input), game_directory)
        return World.load(input)

    prefix, name = input.split(":", 1)

    match prefix.lower():
        case "w":
            return load_world_from_disk(name, game_directory)
        case "v":
            return load_world_from_archive(name, game_directory)
        case _:
            raise Exception("Invalid prefix")


def main():
    try:
        args = parse_args()
        input_file_name: str = args["input"]
        game_directory: Path = args["game-directory"]
        output_path: Path = args["output"]
        scale: float = args["scale"]
        should_parse_waynet: bool = args["waynet"]

        logging_setup(args["verbosity"], output_path.with_name(f"{output_path.stem}.log"))

        info(f"Loading world")
        world = load_world(input_file_name, game_directory)

        if not len(world.root_objects):
            error("Zenkit error: could not load world")
            raise Exception("Zenkit error: could not load world")

        info("Loading Daedalus virtual machine")
        vm = DaedalusVm.load(
            canonical_case_path(game_directory / "_work" / "data" / "scripts" / "_compiled" / "gothic.dat")
        )

        info("Indexing visuals")
        visuals = index_visuals(game_directory)

        info("Indexing VOBs")
        vobs = parse_blender_obj_data_from_world(world, vm, visuals, scale)

        if should_parse_waynet:
            info("Parsing waynet")
            waynet_data = parse_waynet(world, visuals, scale)
            vobs.update(waynet_data)

        if len(vobs) == 0:
            error("Attention! No VOB entries were found during parsing!")

        info("Parsing world data")
        wrld_mesh_data = parse_world_mesh(world, 0.01)

        if wrld_mesh_data.is_empty():
            error("Attention! World mesh is empty!")

        info("Creating world")
        create_obj_from_mesh("LEVEL", wrld_mesh_data, visuals)

        info("Creating VOBs")
        create_vobs(vobs, visuals)

        info(f"Saving to {output_path}...")
        blender_save_changes(filepath=str(output_path))
        info("Done.")

    except Exception as e:
        raise e


if __name__ == "__main__":
    main()
