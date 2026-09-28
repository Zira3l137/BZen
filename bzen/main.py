import subprocess
import sys
from argparse import ArgumentParser
from logging import error
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
        lights: Create Blender lights for light VOBs (default: False)
        verbosity: Verbosity level (0-3) (default: 0)
    """
    parser = ArgumentParser()
    parser.add_argument("input", type=str, help="Input file name")
    parser.add_argument("blender-exe", type=Path, help="Path to the blender executable")
    parser.add_argument("game-directory", type=Path, help="Path to the game directory")
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
    parser.add_argument("-w", "--waynet", action="store_true", help="Parse waynet (default: False)")
    parser.add_argument(
        "-l",
        "--lights",
        action="store_true",
        help="Create a Blender point light for every light VOB (default: False)",
    )
    parser.add_argument(
        "-v",
        "--verbosity",
        type=int,
        default=0,
        help="Verbosity level (0-3) (default: 0)",
    )
    return parser.parse_args().__dict__


def main():
    args = parse_args()

    input: str = args["input"]
    blender_exe: Path = args["blender-exe"]
    game_directory: Path = args["game-directory"]
    output: Path | None = args["output"]
    scale: float = args["scale"]
    waynet: bool = args["waynet"]
    lights: bool = args["lights"]
    verbosity: int = args["verbosity"]

    path_errors = []
    for path in [blender_exe, game_directory]:
        if not path.exists():
            message = f'"{str(path)}" does not exist'
            path_errors.append(message)
            error(message)

    if len(path_errors):
        exit(f'Following provided paths do not exist: {", ".join(path_errors)}')

    if not output:
        output = Path.cwd() / Path(input).with_suffix(".blend").name

    blender_args = [
        blender_exe,
        "--background",
        "--factory-startup",
        # Without this Blender exits with 0 even when the script raises. It must
        # come before --python because it applies to the scripts that follow it.
        "--python-exit-code",
        "1",
        "--python",
        BLENDER_SCRIPT,
        "--",
        str(input),
        str(game_directory),
        str(output),
        str(scale),
        "-v",
        str(verbosity),
    ]

    if waynet:
        blender_args.append("-w")
    if lights:
        blender_args.append("-l")

    completed_process = subprocess.run(blender_args)
    if completed_process.returncode != 0:
        log_file = output.with_name(f"{output.stem}.log")
        sys.exit(
            f"Conversion failed (Blender exited with code {completed_process.returncode}). "
            f"See the output above and {log_file} for details."
        )


if __name__ == "__main__":
    main()
