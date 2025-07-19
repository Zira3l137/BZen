import subprocess
from argparse import ArgumentError, ArgumentParser, Namespace
from logging import error
from pathlib import Path

from error import Err, Ok, Result
from log import logging_setup

BLENDER_SCRIPT = str(Path(__file__).parent / "zen_to_blend.py")


def parse_args() -> Result[Namespace, ArgumentError]:
    """
    Args:
        input: Path to the input file
        blender_exe: Path to the blender executable
        game_directory: Path to the game directory
        output: Path to the output file (defaults to current directory)
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
    return Ok(parser.parse_args())


def main(input: Path, blender_exe: Path, game_directory: Path, output: Path) -> Result[None, Exception]:
    blender_args = [
        blender_exe,
        "--background",
        "--factory-start",
        "--python",
        BLENDER_SCRIPT,
        "--",
        str(input),
        str(game_directory),
        str(output),
    ]

    completed_process = subprocess.run(blender_args, capture_output=True, encoding="utf-8")
    if completed_process.returncode != 0:
        return Err(Exception(completed_process.stderr))

    return Ok(None)


if __name__ == "__main__":
    args = parse_args().unwrap()

    logging_setup(args.verbosity)

    input, blender_exe, game_directory, output = args.input, args.blender_exe, args.game_directory, None

    if any([not path.exists() for path in [input, blender_exe, game_directory]]):
        error("Input file, blender executable, or game directory does not exist")
        exit(1)

    if not output:
        output = Path.cwd() / args.input.with_suffix(".blend").name

    result = main(input, blender_exe, game_directory, output).unwrap()
