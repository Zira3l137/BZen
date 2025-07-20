import subprocess
import sys
from argparse import ArgumentError, ArgumentParser
from logging import error
from pathlib import Path
from typing import Any, Dict

script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.append(str(script_dir))

from error import Err, Ok, Result
from log import logging_setup

BLENDER_SCRIPT = str(Path(__file__).parent / "zen_to_blend.py")


def parse_args() -> Result[Dict[str, Any], ArgumentError]:
    """
    Args:
        input: Path to the input file
        blender_exe: Path to the blender executable
        game_directory: Path to the game directory
        output: Path to the output file (defaults to current directory)
        verbosity: Verbosity level (0-3)
    """
    parser = ArgumentParser()
    try:
        parser.add_argument("input", type=Path, help="Path to the input file")
        parser.add_argument("blender-exe", type=Path, help="Path to the blender executable")
        parser.add_argument("game-directory", type=Path, help="Path to the game directory")
        parser.add_argument("-o", "--output", type=Path, help="Path to the output file (defaults to current directory)")
        parser.add_argument("-v", "--verbosity", type=int, default=0, help="Verbosity level (0-3) (default: 0)")
    except ArgumentError as e:
        return Err(e)
    return Ok(parser.parse_args().__dict__)


def main(input: Path, blender_exe: Path, game_directory: Path, output: Path, verbosity: int) -> Result[None, Exception]:
    blender_args = [
        blender_exe,
        "--background",
        "--factory-startup",
        "--python",
        BLENDER_SCRIPT,
        "--",
        str(input),
        str(game_directory),
        str(output),
        str(verbosity),
    ]

    completed_process = subprocess.run(blender_args)
    if completed_process.returncode != 0:
        return Err(Exception(completed_process.stderr))

    return Ok(None)


if __name__ == "__main__":
    args = parse_args().unwrap()

    logging_setup(args["verbosity"])

    input, blender_exe, game_directory, output, verbosity = (
        args["input"],
        args["blender-exe"],
        args["game-directory"],
        args["output"],
        args["verbosity"],
    )

    if any([not path.exists() for path in [input, blender_exe, game_directory]]):
        error("Input file, blender executable, or game directory does not exist")
        exit(1)

    if not output:
        output = Path.cwd() / input.with_suffix(".blend").name

    if output.exists():
        error("Output file already exists")
        exit(1)

    main(input, blender_exe, game_directory, output, verbosity).unwrap()
