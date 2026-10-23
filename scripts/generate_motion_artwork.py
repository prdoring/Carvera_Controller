"""Build signed motion help while retaining the original CAD direction references."""

import base64
import colorsys
import io
import json
from pathlib import Path

from generate_probing_artwork import COPPER, MUTED, ROOT, Drawing
from PIL import Image, ImageDraw

SOURCES = ROOT / "assets/design/slate/motion/references"


def cad_reference(path, axis):
    image = Image.open(path).convert("RGBA")
    corners = [image.getpixel(point) for point in ((0, 0), (511, 0), (0, 511), (511, 511))]
    if axis != "A" and len(set(corners)) == 1:
        ImageDraw.floodfill(image, (0, 0), (0, 0, 0, 0), thresh=2)
    pixels = []
    for r, g, b, alpha in image.getdata():
        h, saturation, value = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        moving = (
            (axis == "A" and 0.09 < h < 0.20 and saturation > 0.35)
            or (axis == "X" and r > g * 1.1 and r > b * 1.1 and saturation > 0.15)
            or (axis == "Y" and g > r * 1.02 and g > b * 1.15 and saturation > 0.15)
        )
        base, shade = ((214, 153, 99), 0.45 + 0.55 * value) if moving else ((166, 181, 178), 0.18 + 0.72 * value)
        pixels.append((*[round(c * shade) for c in base], alpha))
    image.putdata(pixels)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def main():
    manifest_path = ROOT / "assets/design/slate/artwork-manifest.json"
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = [entry for entry in entries if "/AxisMotion/" not in entry["target"]]
    for axis in ("X", "Y", "Z", "A"):
        for sign, suffix in ((1, "Pos"), (-1, "Neg")):
            name = f"AxisMotion_{axis}{suffix}"
            direction = axis + ("+" if sign > 0 else "−")
            d = Drawing()
            d.title = axis + " AXIS · " + ("POSITIVE" if sign > 0 else "NEGATIVE")
            d.parameter(34, 89, direction, 44, anchor="start")
            if axis == "Z":
                d.rect(128, 125, 29, 249)
                d.rect(128, 125, 280, 29)
                d.rect(113, 363, 306, 26)
                d.rect(228, 191, 62, 91)
                d.line(259, 282, 259, 327, MUTED, 10)
                d.arrow(344, 327 if sign > 0 else 184, 344, 184 if sign > 0 else 327, COPPER)
                d.axes(True)
                d.notes = ["View from −Y toward the X/Z plane.", "Spindle rises." if sign > 0 else "Spindle lowers."]
            else:
                encoded = cad_reference(SOURCES / (name + ".png"), axis)
                d.parts.append(
                    f'<image x="91" y="94" width="330" height="330" href="data:image/png;base64,{encoded}"/>'
                )
                if axis == "A":
                    d.notes = ["Oblique view toward the chuck face.", "Chuck rotates; bed remains stationary."]
                elif axis == "X":
                    d.notes = ["Front view: spindle moves along X.", "Bed is stationary during this movement."]
                else:
                    d.notes = ["Front view: bed moves along Y.", "Spindle is stationary during this movement."]
            source = Path("assets/design/slate/motion") / (name + ".svg")
            (ROOT / source).parent.mkdir(parents=True, exist_ok=True)
            (ROOT / source).write_text(d.svg(), encoding="utf-8")
            target = Path("carveracontroller/data/AxisMotion") / (name + ".png")
            entries.append(
                {
                    "source": source.as_posix(),
                    "target": target.as_posix(),
                    "width": 512,
                    "height": 512,
                    "mode": "help",
                    "description": d.notes,
                }
            )
    manifest_path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    print("Generated eight signed motion-help images")


if __name__ == "__main__":
    main()
