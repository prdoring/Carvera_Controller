"""Recolor registered backgrounds without moving or resampling their geometry.

Pass a source checkout/directory containing the original package images.
"""

import argparse
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]


def refresh(source):
    package = ROOT / "carveracontroller"
    original = Path(source) / "carveracontroller"
    for path in sorted((original / "data/play_file_image_backgrounds").glob("*.png")):
        im = Image.open(path)
        gray = im.convert("L")
        hist = gray.histogram()
        background = max(range(256), key=hist.__getitem__)
        dark, light = ("#222829", "#91A09D") if background < 128 else ("#91A09D", "#222829")
        out = ImageOps.colorize(gray, dark, light)
        if "A" in im.getbands():
            out.putalpha(im.getchannel("A"))
        out.save(package / "data/play_file_image_backgrounds" / path.name)
    atlas = Image.open(original / "data/GcodeViewer/view_cube_atlas.png")
    gray = atlas.convert("L")
    histogram = gray.histogram()
    background = max(range(256), key=histogram.__getitem__)
    out = ImageOps.colorize(gray, "#151C1D", "#F0F0E8", mid="#303A3C", midpoint=background)
    if "A" in atlas.getbands():
        out.putalpha(atlas.getchannel("A"))
    out.save(package / "data/GcodeViewer/view_cube_atlas.png")
    print("Recolored six registered backgrounds and the view cube")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    refresh(parser.parse_args().source)
