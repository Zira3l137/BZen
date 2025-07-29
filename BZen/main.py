import subprocess
from argparse import ArgumentError, ArgumentParser
from logging import error
from os import remove
from pathlib import Path
from typing import Any, Dict

BLENDER_SCRIPT = str(Path(__file__).parent / "zen_to_blend.py")


def parse_args() -> Dict[str, Any]:
    """
    Args:
        input: Path to the input file
        blender_exe: Path to the blender executable
        game_directory: Path to the game directory
        output: Path to the output file (defaults to current directory)
        scale: Scale factor (default: 0.01)
        waynet: Parse waynet (default: False)
        verbosity: Verbosity level (0-3) (default: 0)
    """
    parser = ArgumentParser()
    try:
        parser.add_argument("input", type=Path, help="Path to the input file")
        parser.add_argument(
            "blender-exe", type=Path, help="Path to the blender executable"
        )
        parser.add_argument(
            "game-directory", type=Path, help="Path to the game directory"
        )
        parser.add_argument(
            "-o",
            "--output",
            type=Path,
            help="Path to the output file (defaults to current directory)",
        )
        parser.add_argument(
            "-s",
            "--scale",
            type=float,
            default=0.01,
            help="Scale factor (default: 0.01)",
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
    except ArgumentError as e:
        raise e
    return parser.parse_args().__dict__


def main():
    args = parse_args()

    input: Path = args["input"]
    blender_exe: Path = args["blender-exe"]
    game_directory: Path = args["game-directory"]
    output: Path | None = args["output"]
    scale: float = args["scale"]
    waynet: bool = args["waynet"]
    verbosity: int = args["verbosity"]

    path_errors = []
    for path in [input, blender_exe, game_directory]:
        if not path.exists():
            message = f'"{str(path)}" does not exist'
            path_errors.append(message)
            error(message)

    if len(path_errors):
        exit(f'Following provided paths do not exist: {", ".join(path_errors)}')

    if not output:
        output = Path.cwd() / input.with_suffix(".blend").name
    elif output.exists():
        remove(output)

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
        str(scale),
        str(verbosity),
    ]

    if waynet:
        blender_args.append("-w")

    completed_process = subprocess.run(blender_args)
    if completed_process.returncode != 0:
        raise Exception(completed_process.stderr)


if __name__ == "__main__":
    main()
