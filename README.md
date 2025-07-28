# BZen: Gothic World to Blender Converter 🏰

BZen is a powerful command-line tool for converting 3D world files (ZENs) from the Gothic and Gothic II games into Blender projects. It leverages the [ZenKit4Py](https://github.com/GothicKit/ZenKit4Py) library to parse the original game data and uses Blender's Python API (`bpy`) to reconstruct the world, including its static geometry (world mesh), all objects (VOBs), and even the NPC pathing network (waynet).

## ✨ Features

- **Full World Conversion:** Converts the entire static world mesh from a `.zen` file.
- **VOB Support:** Parses and places a wide variety of Virtual Objects (VOBs), including items, lights, sounds, and interactive objects.
- **Waynet Parsing:** Optionally parses and visualizes the waynet, showing waypoints and paths used by NPCs.
- **Material & Texture Loading:** Automatically creates materials and loads the corresponding textures from the game's data files.
- **Efficient Instancing:** Uses Blender's object instancing to keep `.blend` files small and performant, reusing mesh data for identical objects.
- **Support for Gothic 1 & 2:** Automatically detects the game version based on the provided game directory.
- **Cross-Platform:** Runs on any system where Python and Blender are available.

## 🛠️ Requirements

- **[Python 3.x](https://www.python.org/downloads/):** Required to run the main script. (Optional: you can use Blender's bundled Python distribution directly.)
- **[Blender 4.0 - 4.2](https://www.blender.org/download/releases/):** The tool requires a path to the Blender executable to perform the conversion. (Only versions 4.0 and 4.2 are tested.)
- **[ZenKit4Py](https://github.com/GothicKit/ZenKit4Py):** The script requires it for parsing the original game data. (This tool uses a [fork](https://github.com/Zira3l137/ZenKit4Py) of ZenKit4Py since the current version of the original library lacks some changes introduced by me. That is until the main contributor merges my pull request.)

## 🚀 Usage

BZen is a command-line tool. You need to provide paths to the input `.zen` file, your Blender executable, and the root directory of your Gothic game installation.

```bash
python main.py <path_to_zen_file> <path_to_blender_exe> <path_to_gothic_directory> [options]
```

### Example

```bash
python main.py "D:\Gothic\worlds\NEWORLD.ZEN" "C:\Program Files\Blender Foundation\Blender 3.6\blender.exe" "D:\Gothic" -o "D:\exports\neworld.blend" -w -v 2
```

This command will:
1.  Parse `NEWORLD.ZEN` from the specified Gothic world directory.
2.  Use the Blender executable at the given path.
3.  Read game data (textures, meshes, etc.) from the `D:\Gothic` directory.
4.  Include the waynet in the export (`-w`).
5.  Set the logging verbosity to level 2 (Info) (`-v 2`).
6.  Save the final output to `D:\exports\neworld.blend`.

## ⚙️ Command-Line Arguments

| Argument           | Short | Description                                                                                             |
| ------------------ | ----- | ------------------------------------------------------------------------------------------------------- |
| `input`            |       | (Required) Path to the input `.zen` file.                                                               |
| `blender-exe`      |       | (Required) Path to the Blender executable.                                                              |
| `game-directory`   |       | (Required) Path to the root directory of the Gothic game installation.                                  |
| `--output`         | `-o`  | Path to the output `.blend` file. If not provided, it defaults to a `.blend` file with the same name as the input ZEN in the current directory. |
| `--scale`          | `-s`  | A float value to scale the world. Defaults to `0.01` (Blender's default unit).                                                   |
| `--waynet`         | `-w`  | A flag to enable parsing and including the waynet. Disabled by default.                                 |
| `--verbosity`      | `-v`  | An integer from 0 to 3 to control the logging level (0: Error, 1: Warning, 2: Info, 3: Debug). Defaults to 0. |

## 🔬 How It Works

The tool operates in two main stages:

1.  **CLI Entrypoint (`main.py`):** This script is what you run from your terminal. It parses the command-line arguments and validates the paths. It then launches a new, headless Blender process in the background.

2.  **Blender Script (`zen_to_blend.py`):** This script is executed by the Blender process. It performs the core conversion logic:
    - It initializes `zenkit` and loads the specified `.zen` file and the game's `GOTHIC.DAT` script file.
    - It indexes all available textures and visual assets (meshes, models) from the game directory, searching both loose files and `.vdf` archives.
    - It parses the world's static mesh and creates a single Blender object for it.
    - It iterates through all VOBs in the world, parsing their visual data. It creates a unique Blender object for each new mesh and then creates instances for any subsequent VOBs that use the same mesh, which is highly efficient.
    - If enabled, it parses the waynet and creates simple visual representations for waypoints.
    - Finally, it saves all the created objects into the specified output `.blend` file.

## 🙏 Acknowledgements

This project's development was revitalized thanks to the generous support of **[vvBastervv](https://worldofplayers.ru/members/94865/)**. His contribution was crucial in allowing me to dedicate the time and resources needed to bring BZen to its current state.

I would also like to extend my gratitude to [Auronen](https://github.com/auronen) for his invaluable advice and for always being available to share his opinions on various technical matters throughout the development process.

## 📄 License

This project is licensed under the terms of the license.md file.


```
