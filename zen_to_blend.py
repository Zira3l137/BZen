import sys
from argparse import ArgumentError, ArgumentParser
from pathlib import Path
from typing import Any, Dict

script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.append(str(script_dir))
    sys.path.append(str(script_dir / "venv" / "Lib" / "site-packages"))

from logging import error, info

from zenkit import DaedalusVm, GameVersion, World

from log import logging_setup
from material import index_textures
from utils import blender_save_changes, find_case_insensitive_path
from visual import index_visuals, parse_world_mesh
from vob import create_obj_from_mesh, create_vobs, index_vobs, parse_waynet


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
        parser.add_argument("input", type=Path, help="Path to the input file")
        parser.add_argument("game-directory", type=Path, help="Path to the game directory")
        parser.add_argument("output", type=Path, help="Path to the output file")
        parser.add_argument("scale", type=float, default=0.01, help="Scale factor (default: 0.01)")
        parser.add_argument("-w", "--waynet", action="store_true", help="Parse waynet (default: False)")
        parser.add_argument("verbosity", type=int, default=0, help="Verbosity level (0-3) (default: 0)")

    except ArgumentError as e:
        raise e

    return parser.parse_args(args).__dict__


def main():
    try:
        args = parse_args()
        input_path: Path = args["input"]
        game_directory: Path = args["game-directory"]
        output_path: Path = args["output"]
        scale: float = args["scale"]
        should_parse_waynet: bool = args["waynet"]

        logging_setup(args["verbosity"], output_path.with_name(f"{output_path.stem}.log"))

        info("Loading input file")
        if not input_path.suffix.lower() == ".zen":
            raise Exception("Input file must be a .zen file")

        info("Loading world")
        world = World.load(input_path)

        if not len(world.root_objects):
            error("Zenkit error: could not load world")
            raise Exception("Zenkit error: could not load world")

        info("Loading Daedalus virtual machine")
        vm = DaedalusVm.load(find_case_insensitive_path(game_directory, "_work", "data", "scripts", "_compiled", "gothic.dat"))

        info("Indexing textures")
        textures = index_textures(game_directory)
        if len(textures) == 0:
            error("Attention! No textures were found during parsing!")

        info("Indexing visuals")
        visuals = index_visuals(game_directory)

        info("Indexing VOBs")
        vobs = index_vobs(world, vm, visuals, scale)

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
        create_obj_from_mesh("LEVEL", wrld_mesh_data, textures)

        info("Creating VOBs")
        create_vobs(vobs, textures)

        info(f"Saving to {output_path}...")
        blender_save_changes(filepath=str(output_path))
        info("Done.")

    except Exception as e:
        raise e


if __name__ == "__main__":
    main()
