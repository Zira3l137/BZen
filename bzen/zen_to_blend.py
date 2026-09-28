import sys
from pathlib import Path
from typing import Dict, List
from time import perf_counter


def venv_site_packages(project_dir: Path) -> List[Path]:
    """
    Return the site-packages directories of a "venv" or ".venv" virtual
    environment in ``project_dir``, for both the Windows layout
    (Lib/site-packages) and the Linux/macOS layout
    (lib/pythonX.Y/site-packages). Only existing directories are returned.
    """
    found = []
    for venv_name in ("venv", ".venv"):
        venv_dir = project_dir / venv_name
        candidates = [venv_dir / "Lib" / "site-packages", *sorted(venv_dir.glob("lib/python*/site-packages"))]
        found.extend(path for path in candidates if path.is_dir())
    return found


script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.append(str(script_dir))
    # Blender runs this script with its own Python; let it find packages
    # (ZenKit) installed into a virtual environment in the project directory.
    sys.path.extend(str(path) for path in venv_site_packages(script_dir.parent))

from logging import error, exception, info

from utils import (
    blender_clean_scene,
    blender_parse_cli,
    blender_save_changes,
    canonical_case_path,
    insert_unique,
    install_dependencies_locally,
    suffix,
)

try:
    from zenkit import DaedalusVm, Vfs, VfsNode, World
except ModuleNotFoundError:
    install_dependencies_locally()
    from zenkit import DaedalusVm, Vfs, VfsNode, World

from log import logging_setup
from scene import create_obj_from_mesh, create_vobs
from visual import index_visuals, parse_world_mesh
from vob import parse_blender_obj_data_from_world, parse_waynet


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
        args = blender_parse_cli()
        input_file_name: str = args.input
        game_directory: Path = args.game_directory
        output_path: Path = args.output
        scale: float = args.scale
        should_parse_waynet: bool = args.waynet
        perf_journal: Dict[str, float] = dict()

        logging_setup(args.verbosity, output_path.with_name(f"{output_path.stem}.log"))

        info(f"Cleaning scene")
        blender_clean_scene()

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
        start_time = perf_counter()
        visuals = index_visuals(game_directory)
        elapsed_time = perf_counter() - start_time
        perf_journal["Visuals indexed in (ms) "] = elapsed_time * 1000

        info("Indexing VOBs")
        start_time = perf_counter()
        vobs = parse_blender_obj_data_from_world(world, vm, visuals, scale)
        elapsed_time = perf_counter() - start_time
        perf_journal["VOBs indexed in (ms) "] = elapsed_time * 1000

        if should_parse_waynet:
            info("Parsing waynet")
            start_time = perf_counter()
            waynet_data = parse_waynet(world, visuals, scale)
            elapsed_time = perf_counter() - start_time
            perf_journal["Waynet parsed in (ms) "] = elapsed_time * 1000
            # Waypoints are keyed by their own names, VOBs by visual name + id;
            # the two can collide, so merge without letting one replace the other.
            for name, waypoint_data in waynet_data.items():
                insert_unique(vobs, name, waypoint_data)

        if len(vobs) == 0:
            error("Attention! No VOB entries were found during parsing!")

        info("Parsing world data")
        start_time = perf_counter()
        wrld_mesh_data = parse_world_mesh(world, scale)
        elapsed_time = perf_counter() - start_time
        perf_journal["World mesh parsed in (ms) "] = elapsed_time * 1000

        if wrld_mesh_data.is_empty():
            error("Attention! World mesh is empty!")

        info("Creating world")
        start_time = perf_counter()
        create_obj_from_mesh("LEVEL", wrld_mesh_data, visuals)
        elapsed_time = perf_counter() - start_time
        perf_journal["World created in (ms) "] = elapsed_time * 1000

        info("Creating VOBs")
        start_time = perf_counter()
        create_vobs(vobs, visuals)
        elapsed_time = perf_counter() - start_time
        perf_journal["VOBs created in (ms) "] = elapsed_time * 1000

        info(f"Saving to {output_path}...")
        blender_save_changes(filepath=str(output_path))

        for key, value in perf_journal.items():
            info(f"{key}: {value:.3f}")

        info("Done.")

    except Exception:
        # Record the traceback in the .log file too, not just on the console,
        # then re-raise so Blender exits non-zero (see --python-exit-code).
        exception("Conversion failed")
        raise


if __name__ == "__main__":
    main()
