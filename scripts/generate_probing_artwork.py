"""Build editable probing diagrams and their selector/help export manifest."""

import json
import math
from html import escape
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
PNG_ROOT = Path("carveracontroller/addons/probing/data/icons_1024x768")
SVG_ROOT = Path("assets/design/slate/probing")
BG, PANEL, STOCK = "#222829", "#303A3C", "#435053"
INK, MUTED, COPPER = "#F0F0E8", "#B7C3C1", "#D69963"
UNUSED = {
    "outside_corner/Y+X-.png",
    "calibration/Calibrate_BoreY.png",
    "calibration/Calibrate_4th_Axis_Y_TT.png",
    "calibration/Calibrate_4th_Axis_Y.png",
    "calibration/Calibrate_4th_Axis_Level_01.png",
    "angle/probe_angle_arbitrary_positive.png",
}


FONT = TTFont(ROOT / "carveracontroller/data/fonts/IBMPlexSans-Regular.ttf")
BOLD_FONT = TTFont(ROOT / "carveracontroller/data/fonts/IBMPlexSans-SemiBold.ttf")


class Drawing:
    def __init__(self):
        self.parts = []
        self.title = ""
        self.notes = []

    def path(self, value, color=INK, width=3, fill="none", dashed=False):
        dash = ' stroke-dasharray="8 7"' if dashed else ""
        fill = "url(#stock)" if fill == STOCK else fill
        self.parts.append(
            f'<path d="{value}" fill="{fill}" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"{dash}/>'
        )

    def line(self, x1, y1, x2, y2, color=INK, width=3, dashed=False):
        self.path(f"M{x1} {y1}L{x2} {y2}", color, width, dashed=dashed)

    def rect(self, x, y, width, height, fill=STOCK):
        fill = "url(#stock)" if fill == STOCK else fill
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="4" fill="{fill}" stroke="{MUTED}" stroke-width="2.5"/>'
        )

    def circle(self, x, y, radius, fill="none", color=INK, width=3):
        fill = "url(#stock)" if fill == STOCK else fill
        self.parts.append(
            f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}" stroke="{color}" stroke-width="{width}"/>'
        )

    def text(self, x, y, value, size=24, color=INK, anchor="middle", bold=False):
        # Outlined glyphs keep exports identical without a system Plex installation.
        font = BOLD_FONT if bold else FONT
        glyphs, cmap = font.getGlyphSet(), font.getBestCmap()
        scale = size / font["head"].unitsPerEm
        names = [cmap.get(ord(char), ".notdef") for char in value]
        width = sum(font["hmtx"][name][0] for name in names) * scale
        left = x - (width / 2 if anchor == "middle" else width if anchor == "end" else 0)
        paths, cursor = [], left
        for name in names:
            pen = SVGPathPen(glyphs)
            glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, cursor, y)))
            paths.append(pen.getCommands())
            cursor += font["hmtx"][name][0] * scale
        commands = " ".join(paths)
        self.parts.append(
            f'<g data-text="{escape(value, quote=True)}" data-label-box="{left:.2f},{y - size * 0.78:.2f},{width:.2f},{size:.2f}" fill="{color}"><title>{escape(value)}</title><path d="{commands}"/></g>'
        )

    def parameter(self, x, y, value, size=56, color=COPPER, anchor="middle"):
        self.parts.append(f'<g data-parameter="{escape(value)}">')
        self.text(x, y, value, size, color, anchor, bold=True)
        self.parts.append("</g>")

    def arrow(self, x1, y1, x2, y2, color=COPPER, both=False):
        self.line(x1, y1, x2, y2, color, 4)

        def head(x, y, angle):
            radius = min(12, math.hypot(x2 - x1, y2 - y1) * 0.35)
            a = (x - radius * math.cos(angle - 0.5), y - radius * math.sin(angle - 0.5))
            b = (x - radius * math.cos(angle + 0.5), y - radius * math.sin(angle + 0.5))
            self.path(f"M{a[0]} {a[1]}L{x} {y}L{b[0]} {b[1]}", color, 4)

        angle = math.atan2(y2 - y1, x2 - x1)
        head(x2, y2, angle)
        if both:
            head(x1, y1, angle + math.pi)

    def probe(self, x, y, vertical=False):
        if vertical:
            self.line(x, y - 58, x, y - 15, INK, 8)
            self.rect(x - 14, y - 84, 28, 26)
        self.circle(x, y, 13, PANEL, INK, 3)
        self.circle(x, y, 4, COPPER, COPPER, 2)

    def axes(self, side=False, horizontal="X+"):
        self.arrow(48, 408, 93, 408, MUTED)
        self.arrow(48, 408, 48, 363, MUTED)
        self.text(111, 414, horizontal, 19, MUTED)
        self.text(28, 352, "Z+" if side else "Y+", 19, MUTED)

    def svg(self):
        head = '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">'
        head += '<defs><linearGradient id="stock" x2="0" y2="1"><stop stop-color="#526164"/><stop offset="1" stop-color="#364144"/></linearGradient><linearGradient id="background" x2="0" y2="1"><stop stop-color="#283133"/><stop offset="1" stop-color="#202728"/></linearGradient></defs>'
        frame = '<rect x="3" y="3" width="506" height="506" rx="16" fill="url(#background)" stroke="#566365" stroke-width="2"/>'
        artwork = "".join(self.parts)
        self.parts = []
        self.text(28, 32, self.title, 18, MUTED, "start", bold=True)
        for i, note in enumerate(self.notes):
            self.text(28, 460 + i * 25, note, 19, INK, "start")
        detail = '<g id="detail">' + "".join(self.parts) + "</g>"
        return head + frame + artwork + detail + "</svg>"


def single(d, name):
    axis, sign = name[0], 1 if "+" in name else -1
    d.title = "SINGLE AXIS · " + name.replace("-", "−")
    if axis == "Z":
        d.rect(142, 320, 228, 66)
        d.probe(256, 160, True)
        d.arrow(256, 184, 256, 303)
        d.parameter(329, 262, "Z−")
        d.axes(True)
    elif axis == "X":
        face = 338 if sign > 0 else 174
        start = 176 if sign > 0 else 336
        d.rect(face if sign > 0 else 110, 130, 64, 224)
        d.probe(start, 242)
        d.arrow(start + sign * 25, 242, face - sign * 18, 242)
        d.parameter(256, 320, name.replace("-", "−"))
        d.axes()
    else:
        face = 174 if sign > 0 else 338
        start = 336 if sign > 0 else 176
        d.rect(142, face - 64 if sign > 0 else face, 228, 64)
        d.probe(256, start)
        d.arrow(256, start - sign * 25, 256, face + sign * 18)
        d.parameter(337, 270, name.replace("-", "−"))
        d.axes()
    d.notes = ["Signed search toward the contacted face."]


def corner(d, name, inside):
    name = name.removeprefix("in")
    sx, sy = (1 if "X+" in name else -1), (1 if "Y+" in name else -1)
    d.title = ("INSIDE" if inside else "OUTSIDE") + " CORNER"
    if inside:
        x, y = (348 if sx > 0 else 164), (164 if sy > 0 else 348)
        d.rect(x if sx > 0 else 112, 112, 52, 288)
        d.rect(112, 112 if sy > 0 else y, 288, 52)
        px, py = x - sx * 122, y + sy * 122
        d.probe(px, py)
        d.arrow(px + sx * 24, py, x - sx * 18, py)
        d.arrow(px, py - sy * 24, px, y + sy * 18)
        d.parameter((px + x) / 2, py + 65 if sy > 0 else py - 30, "X+" if sx > 0 else "X−")
        d.parameter(px - sx * 66, (py + y) / 2 + 14, "Y+" if sy > 0 else "Y−")
    else:
        d.rect(170, 170, 172, 172)
        x, y = (170 if sx > 0 else 342), (342 if sy > 0 else 170)
        px, py = x - sx * 80, y - sy * 42
        d.probe(px, py)
        d.arrow(px + sx * 24, py, x - sx * 18, py)
        d.parameter(px + (20 if sx > 0 and sy > 0 else 0), py + 66 if sy > 0 else py - 31, "X+" if sx > 0 else "X−")
        px, py = x + sx * 44, y + sy * 72
        d.probe(px, py)
        d.arrow(px, py - sy * 24, px, y + sy * 18)
        d.parameter(px + sx * 78, py + 16, "Y+" if sy > 0 else "Y−")
    d.axes()
    d.notes = [name.replace("-", "−") + " · two perpendicular contact faces."]


def center(d, name, boss=False, calibration=False):
    circular = "circular" in name or "Bore" in name
    x_only = name.endswith("_x") or name.endswith("BossX")
    y_only = name.endswith("_y") or name.endswith("BossY")
    d.title = "TIP CALIBRATION" if calibration else "OUTSIDE CENTER" if boss else "INSIDE CENTER"
    if boss:
        d.circle(256, 252, 78, STOCK, MUTED, 2.5) if circular else d.rect(178, 174, 156, 156)
    else:
        d.rect(134, 130, 244, 244)
        d.circle(256, 252, 96, BG, MUTED, 2.5) if circular else d.rect(160, 156, 192, 192, BG)
    if not y_only:
        if boss:
            d.probe(126, 252)
            d.probe(386, 252)
            d.arrow(150, 252, 160, 252)
            d.arrow(362, 252, 352, 252)
            d.line(178, 174, 178, 100, MUTED, 2)
            d.line(334, 174, 334, 100, MUTED, 2)
            d.arrow(178, 100, 334, 100, INK, True)
            d.parameter(256, 84, "X", color=INK)
        elif calibration:
            d.line(160, 156, 160, 114, MUTED, 2)
            d.line(352, 156, 352, 114, MUTED, 2)
            d.arrow(160, 116, 352, 116, INK, True)
            d.parameter(256, 99, "X", color=INK)
        else:
            d.arrow(231, 252, 178, 252)
            d.arrow(281, 252, 334, 252)
            d.parameter(300 if circular else 312, 304 if circular else 311, "X")
    if not x_only:
        if boss:
            d.probe(256, 122)
            d.probe(256, 382)
            d.arrow(256, 146, 256, 156)
            d.arrow(256, 358, 256, 348)
            d.line(334, 174, 417, 174, MUTED, 2)
            d.line(334, 330, 417, 330, MUTED, 2)
            d.arrow(412, 174, 412, 330, INK, True)
            d.parameter(454, 269, "Y", color=INK)
        elif calibration:
            d.line(352, 156, 417, 156, MUTED, 2)
            d.line(352, 348, 417, 348, MUTED, 2)
            d.arrow(412, 156, 412, 348, INK, True)
            d.parameter(454, 269, "Y", color=INK)
        else:
            d.arrow(256, 227, 256, 175)
            d.arrow(256, 277, 256, 330)
            d.parameter(212 if circular else 205, 232 if circular else 203, "Y")
    if not boss:
        d.probe(256, 252)
    if boss:
        # Side clearance has its own dimension, below the width and motion cues.
        if y_only:
            d.line(334, 330, 386, 330, MUTED, 2)
            d.line(334, 382, 386, 382, MUTED, 2)
            d.arrow(374, 330, 374, 382, COPPER, True)
            d.parameter(423, 391, "J", 44)
        else:
            d.line(334, 330, 334, 390, MUTED, 2)
            d.line(386, 330, 386, 390, MUTED, 2)
            d.arrow(334, 377, 386, 377, COPPER, True)
            d.parameter(360, 428, "J", 44)
    d.axes()
    if calibration:
        d.notes = (
            ["Known X / Y diameter; both axes run."]
            if not boss
            else ["X / Y = known full reference width.", "Center to outside: X/2 + J, Y/2 + J."]
        )
    elif boss:
        d.notes = ["X / Y = full width or diameter.", "Center to outside: X/2 + J, Y/2 + J."]
    else:
        d.notes = ["X / Y = search reach from the start.", "Opposing contacts determine the center."]


def angle(d, name):
    d.title = "EDGE ANGLE"
    vertical = "_y_" in name
    if vertical:
        right = name.endswith("right")
        edge = 302 if right else 210
        d.path(
            f"M{edge} 140L{edge + 18} 346L{138 if right else 390} 346L{138 if right else 390} 140Z", MUTED, 2.5, STOCK
        )
        start = 399 if right else 113
        for y in (184, 304):
            d.probe(start, y)
            d.arrow(start + (-24 if right else 24), y, edge + (28 if right else -18), y)
        dimx = 79 if right else 432
        d.arrow(dimx, 184, dimx, 304, INK, True)
        d.parameter(dimx + (-34 if right else 34), 261, "Y", 44, INK)
        d.parameter(374 if right else 139, 264, "E")
        d.text(start, 370, "X−" if right else "X+", 25, COPPER)
    else:
        above = name.endswith("above")
        edge = 229 if above else 269
        d.path(
            f"M140 {edge}L370 {edge - 18}L370 {360 if above else 140}L140 {360 if above else 140}Z", MUTED, 2.5, STOCK
        )
        start = 135 if above else 363
        for x in (194, 316):
            d.probe(x, start)
            d.arrow(x, start + (24 if above else -24), x, edge + (-32 if above else 18))
        dimy = 94 if above else 96
        d.arrow(194, dimy, 316, dimy, INK, True)
        d.parameter(255, dimy - 13, "X", 44, INK)
        d.parameter(257, 198 if above else 340, "E")
        d.text(397, start + 8, "Y−" if above else "Y+", 25, COPPER)
    d.axes()
    d.notes = ["X / Y = separation between two samples.", "E = lateral approach / search distance."]


def reference_frame(d, negative=False):
    d.title = "XY REFERENCE ROTATION · Q"
    d.arrow(174, 334, 386, 334, MUTED)
    d.arrow(174, 334, 174, 122, MUTED)
    sign = -1 if negative else 1
    theta = math.radians(28) * sign
    d.arrow(174, 334, 174 + 210 * math.cos(theta), 334 - 210 * math.sin(theta))
    d.arrow(174, 334, 174 - 180 * math.sin(theta), 334 - 180 * math.cos(theta))
    d.path(
        f"M270 334A96 96 0 0 {0 if sign > 0 else 1} {174 + 96 * math.cos(theta)} {334 - 96 * math.sin(theta)}",
        COPPER,
        4,
    )
    d.parameter(324, 395 if sign > 0 else 283, "Q")
    d.line(292, 360 if sign > 0 else 293, 268, 315 if sign > 0 else 354, MUTED, 2)
    d.text(399, 341, "X+", 23, MUTED)
    d.text(174, 107, "Y+", 23, MUTED)
    d.parameter(407, 334 - 210 * math.sin(theta), "X", 32)
    d.parameter(174 - 180 * math.sin(theta), 128, "Y", 32)
    d.notes = ["View from +Z toward the XY plane.", "Positive Q turns counterclockwise."]


def angle_help(d):
    d.title = "ANGLE · REFERENCE AND RESULT"
    d.path("M90 320L430 165L440 300L110 370Z", MUTED, 3, STOCK)
    d.probe(140, 195)
    d.probe(300, 120)
    d.arrow(140, 217, 167, 274)
    d.arrow(300, 142, 327, 198)
    d.arrow(160, 160, 320, 85, INK, True)
    d.parameter(234, 98, "X", 56, INK)
    d.parameter(400, 140, "E", 52)
    d.arrow(80, 422, 300, 422, MUTED)
    d.arrow(80, 422, 80, 332, MUTED)
    d.arrow(80, 422, 280, 328)
    d.path("M170 422A90 90 0 0 0 161 384", COPPER, 4)
    d.parameter(270, 396, "Q", 52)
    d.line(240, 384, 166, 401, MUTED, 2)
    d.text(315, 429, "X+", 21, MUTED)
    d.text(60, 318, "Y+", 21, MUTED)
    d.text(432, 414, "+Z view", 20, MUTED)
    d.notes = ["X = sample separation; E = lateral reach.", "Q sets reference; #153 is measured angle."]


def bore_help(d, name):
    d.title = "POCKET · " + ("MOTION" if "overview" in name else name[-1].upper())
    d.path("M132 142L177 142L177 340L366 340L366 142L397 142L397 389L132 389Z", MUTED, 2.5, STOCK)
    d.probe(256, 174, True)
    d.line(256, 198, 256, 325, COPPER, 3, True)
    d.circle(256, 326, 12, PANEL, INK, 3)
    d.arrow(96, 174, 96, 370, COPPER, True)
    d.parameter(56, 283, "H", 44)
    d.line(273, 326, 318, 326, MUTED, 2)
    d.line(273, 269, 318, 269, MUTED, 2)
    d.arrow(308, 326, 308, 269, INK, True)
    d.parameter(338, 310, "C", 40, INK)
    d.text(439, 407, "Z− ↓", 22, MUTED)
    d.notes = ["H = maximum downward search travel.", "After a hit, retract C from that surface."]


def boss_help(d, name):
    d.title = "BOSS · " + ("MOTION" if "overview" in name else name[-1].upper())
    top_touch = name.endswith(("_h", "_c"))
    d.rect(221, 253, 173, 132)
    if top_touch:
        d.probe(300, 141, True)
        d.line(300, 165, 300, 237, COPPER, 3, True)
        d.circle(300, 239, 12, PANEL, INK, 3)
        d.arrow(432, 239, 432, 195, INK, True)
        d.parameter(467, 228, "R", 34, INK)
        d.line(300, 195, 155, 195, COPPER, 3, True)
        d.line(155, 195, 155, 334, COPPER, 3, True)
        d.text(299, 414, "H enabled · top touch first", 22, MUTED)
    else:
        d.probe(155, 162, True)
        d.line(155, 186, 155, 334, COPPER, 3, True)
        d.text(300, 414, "H disabled · no top touch", 22, MUTED)
    d.probe(155, 334)
    d.arrow(180, 334, 203, 334)
    if name.endswith("_h"):
        d.arrow(89, 141, 89, 358, COPPER, True)
        d.parameter(47, 270, "H", 44)
        d.notes = ["H = optional maximum downward search.", "After the hit, retract R before side travel."]
    elif name.endswith("_c"):
        d.arrow(88, 195, 88, 237, COPPER, True)
        d.parameter(48, 230, "C", 34)
        d.arrow(88, 237, 88, 315, INK, True)
        d.parameter(48, 289, "E", 34, INK)
        d.arrow(114, 315, 114, 334, INK, True)
        d.parameter(92, 384, "D/2", 28, INK)
        d.notes = ["Side descent: E + C + D/2.", "C is used after the optional top touch."]
    else:
        d.arrow(88, 162, 88, 315, COPPER, True)
        d.parameter(48, 256, "E", 44)
        d.arrow(114, 315, 114, 334, INK, True)
        d.parameter(92, 384, "D/2", 28, INK)
        d.notes = ["H disabled: side descent is E + D/2.", "H enabled: side descent is E + C + D/2."]


def anchor(d, name, tip=False):
    d.title = "ANCHOR 2 · TIP CALIBRATION" if tip else "ANCHOR " + ("2" if "2" in name else "1") + " · CALIBRATION"
    d.path("M155 140L207 140L207 332L388 332L388 384L155 384Z", MUTED, 2.5, STOCK)
    if tip:
        d.probe(101, 269)
        d.probe(267, 269)
        d.arrow(125, 269, 139, 269)
        d.arrow(243, 269, 224, 269)
        d.line(155, 140, 155, 98, MUTED, 2)
        d.line(207, 140, 207, 98, MUTED, 2)
        d.arrow(155, 104, 207, 104, INK, True)
        d.parameter(300, 101, "Anchor width", 27, INK)
        d.notes = ["Configured anchor width is sampled in X.", "Automatic position and top touch first."]
    else:
        d.probe(282, 257)
        d.arrow(258, 257, 226, 257)
        d.arrow(282, 281, 282, 314)
        d.parameter(253, 218, "X−", 44)
        d.parameter(345, 302, "Y−", 44)
        d.notes = ["Use the configured anchor geometry.", "Automatic positioning precedes probing."]
    d.axes()


def rotary_height(d):
    d.title = "ROTARY CENTER HEIGHT · M469.5"
    d.rect(91, 245, 103, 42)
    d.rect(194, 213, 190, 64)
    d.line(194, 245, 400, 245, MUTED, 2, True)
    d.probe(137, 230, True)
    d.arrow(137, 241, 137, 244)
    d.probe(290, 184, True)
    d.arrow(290, 200, 290, 212)
    d.line(137, 138, 137, 90, MUTED, 2)
    d.line(290, 91, 290, 90, MUTED, 2)
    d.arrow(137, 94, 290, 94, INK, True)
    d.parameter(214, 81, "X", 38, INK)
    d.arrow(416, 213, 416, 277, INK, True)
    d.parameter(458, 260, "R", 44, INK)
    d.arrow(350, 197, 350, 164, COPPER, True)
    d.parameter(390, 181, "C", 32)
    d.text(136, 319, "1 · Z reference", 21, MUTED)
    d.text(427, 315, "X / Z", 20, MUTED)
    for i, x in enumerate((84, 198, 312, 426)):
        d.circle(x, 376, 23, STOCK, MUTED, 2)
        d.arrow(x, 334, x, 349, COPPER)
        d.text(x, 419, "A" if i == 0 else f"A+{i * 90}°", 21)
        d.text(x, 384, str(i + 2), 21)
    d.notes = ["Four pin-top samples; R is pin diameter.", "Center height = mean(top samples) − R/2."]


def rotary(d, name):
    if name.endswith("_Z"):
        rotary_height(d)
        return
    leveling = "Level_" in name
    front = "Front" in name or "_Z" in name
    d.title = "ROTARY LEVEL" if leveling else "ROTARY CENTER · Z" if name.endswith("_Z") else "ROTARY CENTER · Y / Z"
    if not leveling and not front:
        d.rect(95, 170, 75, 180)
        d.rect(170, 218, 195, 80)
        d.line(170, 258, 385, 258, MUTED, 2, True)
        d.probe(275, 365)
        d.arrow(275, 343, 275, 315)
        d.probe(275, 151)
        d.arrow(275, 173, 275, 201)
        d.text(275, 408, "A+90° · front", 22)
        d.text(275, 118, "A−90° · back", 22)
        d.arrow(397, 218, 397, 298, INK, True)
        d.parameter(437, 271, "R")
        d.axes()
        d.notes = ["View from +Z. R is artifact diameter.", "Top touches and module Z reference also run."]
        return
    if leveling:
        d.path("M112 293L393 272L399 341L119 361Z", MUTED, 3, STOCK)
        for x, y in ((163, 288), (348, 275)):
            d.probe(x, y - 80, True)
            d.arrow(x, y - 57, x, y - 18)
        d.arrow(163, 374, 348, 374, INK, True)
        d.parameter(255, 428, "Y", 48, INK)
        d.parameter(161, 328, "−Y/2", 28, INK)
        d.parameter(346, 315, "+Y/2", 28, INK)
        d.arrow(414, 195, 414, 313, COPPER, True)
        d.parameter(450, 263, "H")
        d.notes = ["H is downward reach at each sample.", "Optional V rotation only when enabled."]
    else:
        d.rect(99, 374, 304, 24)
        d.circle(256, 277, 80, STOCK, MUTED, 3)
        d.line(149, 277, 363, 277, MUTED, 2, True)
        d.line(256, 185, 256, 374, MUTED, 2, True)
        d.probe(256, 160, True)
        d.arrow(256, 178, 256, 193)
        d.text(294, 180, "1 / 4", 23, COPPER)
        d.line(256, 197, 424, 197, MUTED, 2)
        d.line(256, 357, 424, 357, MUTED, 2)
        d.arrow(424, 197, 424, 357, INK, True)
        d.parameter(466, 295, "R", color=INK)
        if name.endswith("_Z"):
            d.text(256, 408, "A · A+90° · A+180° · A+270°", 21)
            d.notes = ["Mean top samples minus R/2.", "C = clearance; H is not used."]
        else:
            d.probe(144, 277)
            d.probe(368, 277)
            d.arrow(162, 277, 173, 277)
            d.arrow(350, 277, 339, 277)
            d.text(144, 319, "2", 25, COPPER)
            d.text(368, 319, "3", 25, COPPER)
            d.text(124, 240, "A+90°", 22)
            d.text(372, 240, "A−90°", 22)
            d.notes = ["Top → front → back → top; refine.", "R is diameter. Y / Z inputs are unused."]
        d.text(256, 426, "Z reference", 21, MUTED)
    if front or leveling:
        d.axes(True, "Y+")
        if leveling:
            d.text(391, 415, "+X view", 20, MUTED)
    else:
        d.axes()


def build(relative):
    d = Drawing()
    family = relative.parts[0]
    name = relative.stem
    if family == "single_axis":
        single(d, name)
    elif family in ("inside_corner", "outside_corner"):
        corner(d, name, family == "inside_corner")
    elif family == "inside_center":
        bore_help(d, name) if "parameter" in name or "overview" in name else center(d, name)
    elif family == "outside_center":
        boss_help(d, name) if "parameter" in name or "overview" in name else center(d, name, True)
    elif family == "angle":
        angle_help(d) if "arbitrary" in name else angle(d, name)
    elif family == "general_parameters":
        if name.endswith("_q"):
            reference_frame(d)
        else:
            d.title = "EFFECTIVE PROBE TIP · D"
            d.rect(228, 105, 56, 65)
            d.line(256, 170, 256, 258, INK, 12)
            d.circle(256, 296, 40, PANEL, INK, 5)
            d.arrow(216, 296, 296, 296, COPPER, True)
            d.parameter(256, 380, "D", 48)
            d.notes = ["Diameter across the contacting tip.", "Do not use the shaft diameter."]
    elif name.startswith("Calibrate_Bore"):
        center(d, name, False, True)
    elif name.startswith("Calibrate_Boss"):
        center(d, name, True, True)
    elif "Anchor" in name:
        anchor(d, name, "On_Anchor" in name)
    else:
        rotary(d, name)
    return d


def main():
    manifest = []
    selectors = 0
    files = sorted(p for p in (ROOT / PNG_ROOT).rglob("*.png") if "details" not in p.parts)
    for image in files:
        relative = image.relative_to(ROOT / PNG_ROOT)
        if relative.as_posix() in UNUSED:
            continue
        d = build(relative)
        source = SVG_ROOT / relative.with_suffix(".svg")
        (ROOT / source).parent.mkdir(parents=True, exist_ok=True)
        (ROOT / source).write_text(d.svg(), encoding="utf-8")
        help_only = any(
            s in relative.stem for s in ("parameter_", "motion_overview", "arbitrary_", "M469.6_Front", "Level_03")
        )
        if not help_only:
            selectors += 1
            manifest.append(
                {
                    "source": source.as_posix(),
                    "target": (PNG_ROOT / relative).as_posix(),
                    "width": 256,
                    "height": 256,
                    "mode": "selector",
                }
            )
            target = PNG_ROOT / "details" / relative
            (ROOT / target).parent.mkdir(parents=True, exist_ok=True)
        else:
            target = PNG_ROOT / relative
        manifest.append(
            {
                "source": source.as_posix(),
                "target": target.as_posix(),
                "width": 512,
                "height": 512,
                "mode": "help",
                "description": d.notes,
            }
        )
    assert selectors == 34, selectors
    assert len(manifest) == 80, len(manifest)
    (ROOT / "assets/design/slate/artwork-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{selectors} selectors, 46 detailed help drawings, {len(manifest)} exports")


if __name__ == "__main__":
    main()
