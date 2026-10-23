"""Record glyph coverage shared by the bundled interface font faces."""

import json
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1] / "carveracontroller/data/fonts"


def main():
    coverage = None
    for path in ROOT.glob("*.ttf"):
        with TTFont(path) as font:
            glyphs = set(font.getBestCmap())
        coverage = glyphs if coverage is None else coverage & glyphs
    ranges = []
    for codepoint in sorted(coverage or []):
        if ranges and ranges[-1][1] == codepoint - 1:
            ranges[-1][1] = codepoint
        else:
            ranges.append([codepoint, codepoint])
    (ROOT / "coverage.json").write_text(json.dumps(ranges) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
