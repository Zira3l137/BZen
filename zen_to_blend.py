import sys
from argparse import ArgumentError, ArgumentParser
from pathlib import Path
from typing import Any, Dict

script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.append(str(script_dir))

from logging import error, info, warning

from zenkit import GameVersion, World

from error import Err, Ok, Result
from log import logging_setup
from material import index_textures
from utils import blender_save_changes
from visual import index_visuals, parse_world_mesh
from vob import create_obj_from_mesh, create_vobs, index_vobs


def parse_args() -> Result[Dict[str, Any], ArgumentError]:
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
        parser.add_argument("verbosity", type=int, default=0, help="Verbosity level (0-3) (default: 0)")

    except ArgumentError as e:
        return Err(e)

    return Ok(parser.parse_args(args).__dict__)


def main() -> Result[None, Exception]:
    try:
        args = parse_args().expect("Failed to parse arguments")
        input_path: Path = args["input"]
        game_directory: Path = args["game-directory"]
        output_path: Path = args["output"]

        logging_setup(args["verbosity"], output_path.with_name(f"{output_path.stem}.log"))

        info("Loading input file")
        if not input_path.suffix.lower() == ".zen":
            return Err(Exception("Input file must be a .zen file"))

        game_version = (
            GameVersion.GOTHIC2 if "gothicii" in game_directory.stem.lower().replace(" ", "") else GameVersion.GOTHIC1
        )
        world = World.load(input_path, game_version)
        info(f"Loading {game_version.name} world")

        if not len(world.root_objects):
            error("Zenkit error: could not load world")
            return Err(Exception("Zenkit error: could not load world"))

        info("Indexing textures")
        textures = index_textures(game_directory).unwrap()

        info("Indexing visuals")
        visuals = index_visuals(game_directory).unwrap()

        info("Indexing VOBs")
        vobs = index_vobs(world, visuals).unwrap()

        if len(vobs) == 0:
            error("Attention! No VOB entries were found during parsing!")

        info("Parsing world data")
        wrld_mesh_data = parse_world_mesh(world, 0.01).unwrap()

        if wrld_mesh_data.is_empty():
            error("Attention! World mesh is empty!")

        info("Creating world")
        create_obj_from_mesh("LEVEL", wrld_mesh_data, textures).unwrap()

        info("Creating VOBs")
        create_vobs(vobs, textures).unwrap()

        info(f"Saving to {output_path}...")
        blender_save_changes(filepath=str(output_path))
        info("Done.")

    except Exception as e:
        return Err(e)

    return Ok(None)


if __name__ == "__main__":
    main().unwrap()
