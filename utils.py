import bpy


def with_suffix(path: str, suffix: str, replace: bool = False) -> str:
    result = path.rsplit(".", 1)[0] if replace else path
    return f"{result}.{suffix}"


def suffix(path: str, dot: bool = False) -> str:
    prefix = "." if dot else ""
    return f"{prefix}{path.rsplit('.', 1)[-1]}"


def trim_suffix(path: str) -> str:
    return path.rsplit(".", 1)[0]


def abgr_to_rgba(color: int) -> tuple[float, float, float, float]:
    a, b, g, r = (color >> 24) & 0xFF, (color >> 16) & 0xFF, (color >> 8) & 0xFF, color & 0xFF
    a_f, b_f, g_f, r_f = a / 255.0, b / 255.0, g / 255.0, r / 255.0
    return (r_f, g_f, b_f, a_f)


def blender_save_changes(*args, **kwargs):
    bpy.ops.wm.save_mainfile(*args, **kwargs)
