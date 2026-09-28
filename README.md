# BZen: Gothic World to Blender Converter 🏰

BZen is a command-line tool for converting 3D world files (`.zen`) from Gothic and Gothic II into Blender projects. It uses the [ZenKit4Py](https://github.com/GothicKit/ZenKit4Py) library to parse game data and Blender's Python API (`bpy`) to reconstruct the world.

> [!WARNING]
>
> I did not expect this to be necessary to mention, but due to recent events I find it imperative to specify that this tool uses and relies on **existing installation of either Gothic 1 or 2**. Which means if you don't have a local installation of either game **BZen will not be able to do anything**.

## ✨ Features

- **Full World Conversion:** Converts the entire static world mesh from a `.zen` file.
- **VOB Support:** Parses and places a wide variety of Virtual Objects (VOBs), including items, lights, sounds, interactive objects, decals, trigger zones, fog zones, music zones, waypoints, and more. Invisible VOBs (triggers, lights, sounds, etc.) are represented with placeholder meshes so they remain visible and selectable in Blender.
- **Organized Scene:** VOBs are grouped into a `VOBs` collection with one child collection per VOB type (`oCItem`, `zCVobLight`, `oCMobContainer`, ...), so whole categories can be hidden, selected or excluded at once. Waypoints go into `Waynet/Waypoints`.
- **Waynet Parsing:** Optionally parses and visualizes the waynet: waypoints used by NPCs go to `Waynet/Waypoints`, and the connections between them are drawn as a single edge mesh (`WAYNET_EDGES`) in `Waynet/Waynet Edges`, so each part can be toggled on its own.
- **Material & Texture Loading:** Automatically creates materials and loads textures from loose files and `.vdf` archives.
- **Animated Textures:** Textures that the game animates (names containing `_A0`, such as waterfalls or fire) cycle through their frames at the in-game speed as the Blender timeline plays. Materials the game scrolls (flowing water and the like) scroll in the same direction and at the same speed. All frames are packed into the `.blend`, and the speed follows the scene's frame rate. Each frame is a separate texture in the material, so on some GPUs EEVEE may fail to display (pink) animations with many frames; Cycles is not affected. At `-v 2` the log lists every animated texture with its frame count.
- **Lights (opt-in):** With `--lights`, every light VOB also gets a Blender point light with the VOB's color and a brightness that matches the in-game falloff, collected in a `Lights` collection. Lights switched off in the game are created but hidden. Note that EEVEE before Blender 4.2 renders at most 128 active lights at a time; Cycles and EEVEE in 4.2+ are not limited this way.
- **Efficient Instancing:** Reuses mesh data for identical objects to keep `.blend` files small and performant.
- **Flexible Input:** Accepts a full path to a `.zen` file, a bare filename (auto-searched in the game's archives and working directory), or a prefixed name to force a specific search location (see [Input Formats](#-input-formats) below).
- **Log File Output:** Always writes a `.log` file alongside the output `.blend` file (same name, same directory) for post-run inspection.
- **Support for Gothic 1 & 2:** Works with both games.

## 🛠️ Requirements

- **[Python 3.10+](https://www.python.org/downloads/):** Required to run the main script.
- **[Blender](https://www.blender.org/download/):** The tool requires a path to the Blender executable. Blender 4.0, 4.2 and 5.2 are tested; other versions from 4.0 on should work, older versions **may or may not** work.
- **[ZenKit4Py](https://github.com/Zira3l137/ZenKit4Py):** Installed automatically into Blender's Python on first run if not already available. This tool uses a [fork](https://github.com/Zira3l137/ZenKit4Py) of ZenKit4Py that includes changes not yet merged into the upstream library.

## 📦 Installation

### Option 1 — Clone and install dependencies manually:

```bash
git clone https://github.com/Zira3l137/BZen
cd BZen
pip install -r requirements.txt
```

### Option 2 (**RECOMMENDED**) — Install as a CLI tool via pip:

```bash
pip install git+https://github.com/Zira3l137/BZen
```

After Option 2, the `bzen` command is available globally. After Option 1, run the tool with `python -m bzen` from inside the cloned directory, or use `python bzen/main.py` directly.

## 🚀 Usage

```bash
# If installed via pip (Option 2):
bzen <input> <path_to_blender_exe> <path_to_gothic_directory> [options]

# If cloned (Option 1):
python -m bzen <input> <path_to_blender_exe> <path_to_gothic_directory> [options]
```

### Example

```bash
bzen "NEWWORLD.ZEN" "C:\Program Files\Blender Foundation\Blender 4.2\blender.exe" "D:\Gothic II" -o "D:\exports\newworld.blend" -w -v 2
```

This command will:
1. Search for `NEWWORLD.ZEN` in the game's `.vdf` archives, then in the working directory files if not found there.
2. Launch a headless Blender process using the provided executable.
3. Load textures, meshes, and other assets from `D:\Gothic II`.
4. Include the waynet in the export (`-w`).
5. Set logging verbosity to Info level (`-v 2`).
6. Save the result to `D:\exports\newworld.blend` and a log to `D:\exports\newworld.log`.

## 📥 Input Formats

The `input` argument is more flexible than a plain file path. Three formats are supported:

| Format | Example | Behavior |
|---|---|---|
| Bare filename | `NEWWORLD.ZEN` | Searches `data/worlds.vdf` and `data/worlds_addon.vdf` first, then `_work/data/worlds/` on disk |
| Absolute path | `D:\Gothic II\\_work\Data\Worlds\NEWWORLD.ZEN` | Loads directly from the given path |
| Prefixed name | `v:NEWWORLD.ZEN` | Forces archive search (`v:` prefix) |
| Prefixed name | `w:NEWWORLD.ZEN` | Forces disk search in `_work/data/worlds/` (`w:` prefix) |

## ⚙️ Command-Line Arguments

| Argument | Short | Description |
|---|---|---|
| `input` | | (Required) `.zen` file to convert. See [Input Formats](#-input-formats). |
| `blender-exe` | | (Required) Full path to the Blender executable. |
| `game-directory` | | (Required) Root directory of the Gothic installation (the folder containing `Data/` and `_work/`). |
| `--output` | `-o` | Path for the output `.blend` file. Defaults to the current directory, named after the input file. A `.log` file is always written alongside it. |
| `--scale` | `-s` | World scale factor. Defaults to `0.01` (converts Gothic's centimeter units to Blender's meter units). |
| `--waynet` | `-w` | Include the waynet (NPC navigation points) in the output. Disabled by default. |
| `--lights` | `-l` | Create a Blender point light for every light VOB. Disabled by default. |
| `--verbosity` | `-v` | Logging detail level: `0` = Errors only (default), `1` = Warnings, `2` = Info, `3` = Debug. |

## 🔬 How It Works

The tool runs in two stages:

**1. CLI Entrypoint (`main.py`):** Parses arguments, validates that the Blender executable and game directory exist, then launches a headless Blender process in the background, passing all parameters to the next stage.

**2. Blender Script (`zen_to_blend.py`):** Executed inside Blender's embedded Python interpreter. It:
- Loads the `.zen` world file (via archive, disk, or direct path depending on the input format).
- Loads the `GOTHIC.DAT` Daedalus script file to resolve item visuals.
- Indexes all available textures and meshes from both loose files (`_work/data/`) and `.vdf` archives (`data/`).
- Parses the static world mesh and creates a single `LEVEL` object in Blender.
- Iterates all VOBs in the world tree, creates a unique mesh object for each distinct visual, and instances it for every subsequent VOB sharing that visual.
- Invisible VOB types (triggers, lights, sounds, etc.) are placed using internal placeholder meshes so they appear in the scene.
- If `--lights` is set, a point light is created for every light VOB.
- If `--waynet` is set, waypoints are also parsed and placed, and the connections between them are built as one mesh of loose edges.
- Saves the result to the specified `.blend` file and writes a log file next to it.

## 🙏 Acknowledgements

This project's development was revitalized thanks to the generous support of **[vvBastervv](https://worldofplayers.ru/members/94865/)**. His contribution was crucial in allowing the time and resources needed to bring BZen to its current state.

Thanks also to [Auronen](https://github.com/auronen) for invaluable technical advice throughout development.

## 📄 License

This project is licensed under the terms of the [license.md](license.md) file.
