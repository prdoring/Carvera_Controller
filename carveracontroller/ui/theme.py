"""Slate Workshop colors, fonts and saved-color migration."""

import json
from bisect import bisect_right
from pathlib import Path

_GLYPH_RANGES = json.loads((Path(__file__).parents[1] / "data/fonts/coverage.json").read_text())
_GLYPH_STARTS = [first for first, _last in _GLYPH_RANGES]


def rgba(value):
    return tuple(int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)) + (1,)


BACKGROUND = rgba("222829")
PANEL = rgba("303A3C")
FIELD = rgba("151C1D")
CONTROL = rgba("435053")
CONTROL_HOVER = rgba("526164")
BORDER = rgba("566365")
TEXT = rgba("F0F0E8")
SECONDARY = rgba("B7C3C1")
MUTED = rgba("829290")
ACCENT = rgba("D69963")
SELECTED = rgba("655343")
DANGER = rgba("A3423E")
ERROR = rgba("F18A73")
SUCCESS = rgba("88B59B")
TRANSPARENT = (0, 0, 0, 0)
SANS = "PlexSans"
MONO = "PlexMono"


def font_for(text, mono=False):
    """Keep CJK and other existing Unicode text covered by the bundled font."""
    for char in str(text or ""):
        codepoint = ord(char)
        if codepoint < 128:
            continue
        index = bisect_right(_GLYPH_STARTS, codepoint) - 1
        if index < 0 or codepoint > _GLYPH_RANGES[index][1]:
            return "ARIALUNI"
    return MONO if mono else SANS


STOCK_COLORS = {
    "active_color": ("0,255,255,255", "214,153,99,255"),
    "gcode_color_comment": ("106,153,85,255", "136,165,144,255"),
    "gcode_color_g_command": ("86,156,214,255", "139,186,200,255"),
    "gcode_color_m_command": ("197,134,192,255", "191,165,191,255"),
    "gcode_color_coordinate": ("206,145,120,255", "223,188,153,255"),
    "gcode_color_feedrate": ("78,201,176,255", "147,192,174,255"),
    "gcode_color_spindle": ("209,105,105,255", "225,157,145,255"),
    "gcode_color_tool": ("181,206,168,255", "203,192,146,255"),
    "gcode_color_line_number": ("133,133,133,255", "130,146,144,255"),
    "gcode_color_parameter": ("156,220,254,255", "174,202,207,255"),
    "gcode_color_o_label": ("86,156,214,255", "139,186,200,255"),
    "gcode_color_o_keyword": ("220,220,170,255", "216,203,151,255"),
    "gcode_color_param_ref": ("181,206,168,255", "178,195,151,255"),
    "gcode_color_math_keyword": ("215,186,125,255", "214,153,99,255"),
}


def migrate_colors(config):
    """Replace stock colors once while retaining deliberately customized values."""
    if config.getint("carvera", "slate_colors_version", fallback=0) >= 1:
        return
    for key, (old, new) in STOCK_COLORS.items():
        value = config.get("carvera", key, fallback=old)
        if value.replace(" ", "") == old:
            config.set("carvera", key, new)
    config.set("carvera", "slate_colors_version", "1")


def jog_chevron(text, x, y, radius, visible, invert_y=False):
    """Draw a spatial cue without changing the signed machine command."""
    if not visible or text.startswith("A"):
        return []
    if text.startswith("X"):
        sign = 1 if "+" in text else -1
        return [x - sign * radius / 2, y + radius, x + sign * radius / 2, y, x - sign * radius / 2, y - radius]
    up = ("+" in text) if text.startswith("Z") or invert_y else ("-" in text)
    sign = 1 if up else -1
    return [x - radius, y - sign * radius / 2, x, y + sign * radius / 2, x + radius, y - sign * radius / 2]
