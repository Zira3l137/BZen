import bpy


def with_suffix(path: str, suffix: str, replace: bool = False) -> str:
    result = path.rsplit(".", 1)[0] if replace else path
    return f"{result}.{suffix}"


def suffix(path: str, dot: bool = False) -> str:
    prefix = "." if dot else ""
    return f"{prefix}{path.rsplit('.', 1)[-1]}"


def trim_suffix(path: str) -> str:
    return path.rsplit(".", 1)[0]


def blender_save_changes(*args, **kwargs):
    bpy.ops.wm.save_mainfile(*args, **kwargs)
