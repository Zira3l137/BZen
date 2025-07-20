import sys
from argparse import ArgumentError, ArgumentParser
from pathlib import Path
from typing import Any, Dict

script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.append(str(script_dir))

from logging import info

from error import Err, Ok, Result
from log import logging_setup


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
    args = parse_args()
    if args.is_err():
        return Err(args.error())
    args = args.unwrap()

    logging_setup(args["verbosity"])

    # TODO: Implement zen_to_blend
    info(args["input"])
    info(args["game-directory"])
    info(args["output"])

    return Ok(None)


if __name__ == "__main__":
    main().unwrap()
