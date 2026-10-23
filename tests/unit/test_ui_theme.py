"""Slate palette migration and packaged instructional artwork contracts."""

import json
from configparser import ConfigParser
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from carveracontroller.ui import theme

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets/design/slate"
PREFIX = "carveracontroller/addons/probing/data/icons_1024x768/"


def test_stock_color_migration_is_once_and_preserves_custom_choices():
    config = ConfigParser()
    config.add_section("carvera")
    for key, (old, _) in theme.STOCK_COLORS.items():
        config.set("carvera", key, old)
    config.set("carvera", "gcode_color_tool", "12,34,56,255")
    theme.migrate_colors(config)
    assert config.get("carvera", "active_color") == "214,153,99,255"
    assert config.get("carvera", "gcode_color_tool") == "12,34,56,255"
    for key, (_, new) in theme.STOCK_COLORS.items():
        if key != "gcode_color_tool":
            assert config.get("carvera", key) == new
    config.set("carvera", "active_color", "0,255,255,255")
    theme.migrate_colors(config)
    assert config.get("carvera", "active_color") == "0,255,255,255"
    assert config.getint("carvera", "slate_colors_version") == 1


def test_font_aliases_and_unicode_fallback():
    assert theme.font_for("Speed 600") == "PlexSans"
    assert theme.font_for("−12.250", mono=True) == "PlexMono"
    assert theme.font_for("文件 车刀") == "ARIALUNI"
    assert theme.font_for("القياس") == "ARIALUNI"
    assert theme.font_for("工具 6", mono=True) == "ARIALUNI"
    for file in ("IBMPlexSans-Regular.ttf", "IBMPlexSans-SemiBold.ttf", "IBMPlexMono-Regular.ttf", "OFL.txt"):
        assert (ROOT / "carveracontroller/data/fonts" / file).is_file()
    assert (ROOT / "carveracontroller/data/theme/LUCIDE-LICENSE.txt").is_file()


def expected_selector_labels():
    expected = {}
    for direction in ("X+", "X−", "Y+", "Y−", "Z−"):
        expected["single_axis/" + direction.replace("−", "-") + ".png"] = {direction}
    for family, prefix in (("outside_corner", ""), ("inside_corner", "in")):
        for x in ("X+", "X−"):
            for y in ("Y+", "Y−"):
                expected[f"{family}/{prefix}{x}{y}.png".replace("−", "-")] = {x, y}
    for family, base, suffixes in (
        ("inside_center", "inside_center_rectangular_pocket", ("_x", "_y", "")),
        ("outside_center", "outside_center_rect_boss", ("_x", "_y", "")),
    ):
        for suffix in suffixes:
            labels = {"X"} if suffix == "_x" else {"Y"} if suffix == "_y" else {"X", "Y"}
            expected[f"{family}/{base}{suffix}.png"] = labels | ({"J"} if family == "outside_center" else set())
    expected["inside_center/inside_center_circular_bore.png"] = {"X", "Y"}
    expected["outside_center/outside_center_circular_boss.png"] = {"X", "Y", "J"}
    for direction in ("x_above", "x_below", "y_left", "y_right"):
        expected[f"angle/probe_angle_{direction}.png"] = {direction[0].upper(), "E"}
    expected.update(
        {
            "calibration/Calibrate_BoreX.png": {"X", "Y"},
            "calibration/Calibrate_BossX.png": {"X", "J"},
            "calibration/Calibrate_BossY.png": {"Y", "J"},
            "calibration/Calibrate_On_Anchor_2.png": {"Anchor width"},
            "calibration/Calibrate_Anchor_1.png": {"X−", "Y−"},
            "calibration/Calibrate_Anchor_2.png": {"X−", "Y−"},
            "calibration/Calibrate_4th_Axis_Z.png": {"X", "C", "R"},
            "calibration/Calibrate_4th_Axis_M469.6_Top.png": {"R"},
            "calibration/Calibrate_4th_Axis_Level_02.png": {"Y", "H", "−Y/2", "+Y/2"},
        }
    )
    return expected


@pytest.mark.parametrize("relative,expected", expected_selector_labels().items())
def test_selector_parameter_letters_are_visible_in_both_exports(relative, expected):
    master = ART / "probing" / Path(relative).with_suffix(".svg")
    drawing = ET.parse(master).getroot()
    details = next(node for node in drawing if node.get("id") == "detail")
    drawing.remove(details)
    labels = {node.get("data-parameter") for node in drawing.iter() if node.get("data-parameter")}
    assert expected <= labels, (relative, expected - labels)
    if relative.endswith("Calibrate_4th_Axis_Z.png"):
        assert "H" not in labels
    for detail, size in (("", 256), ("details/", 512)):
        with Image.open(ROOT / (PREFIX + detail + relative)) as image:
            assert image.size == (size, size)


def test_probe_exports_cover_every_active_selector_and_help_image():
    entries = json.loads((ART / "artwork-manifest.json").read_text())
    entries = [entry for entry in entries if "/probing/" in entry["source"]]
    assert len(entries) == 80
    assert len({entry["source"] for entry in entries}) == 46
    selectors = [entry for entry in entries if entry["mode"] == "selector"]
    assert len(selectors) == 34
    assert {entry["target"].removeprefix(PREFIX) for entry in selectors} == set(expected_selector_labels())
    for entry in entries:
        assert (ROOT / entry["source"]).is_file()
        with Image.open(ROOT / entry["target"]) as image:
            assert image.size == (entry["width"], entry["height"])


def test_interface_icon_exports_and_clear_search_meaning():
    icons = json.loads((ART / "icons/manifest.json").read_text())
    assert len(icons) == 52
    assert icons["data/delete.png"] == "x"
    for target, source in icons.items():
        assert (ART / "icons" / (source + ".svg")).is_file()
        with Image.open(ROOT / "carveracontroller" / target) as image:
            assert image.size == (128, 128)


SETTINGS_CONTRACT = json.loads((ROOT / "tests/resources/settings_contract.json").read_text())


@pytest.mark.parametrize("setting", SETTINGS_CONTRACT, ids=lambda s: s["schema"] + ":" + s["section"] + "/" + s["key"])
def test_every_existing_schema_key_type_default_and_choice_remains(setting):
    schema = json.loads((ROOT / "carveracontroller" / setting["schema"]).read_text(encoding="utf-8"))
    item = next(
        item for item in schema if item.get("section") == setting["section"] and item.get("key") == setting["key"]
    )
    for key, value in setting.items():
        if key != "schema":
            if key == "default" and setting["key"] in theme.STOCK_COLORS:
                value = theme.STOCK_COLORS[setting["key"]][1]
            assert item.get(key) == value


def test_settings_inventory_covers_157_distinct_section_key_pairs():
    assert len({(item["section"], item["key"]) for item in SETTINGS_CONTRACT}) == 157


def test_probe_lettering_stays_inside_frames_and_does_not_overlap():
    from itertools import combinations

    for master in (ART / "probing").rglob("*.svg"):
        labels = []
        for node in ET.parse(master).getroot().iter():
            if "data-label-box" not in node.attrib:
                continue
            x, y, width, height = map(float, node.get("data-label-box").split(","))
            assert x >= 12 and y >= 10 and x + width <= 500 and y + height <= 500, master
            labels.append((x, y, width, height, node.get("data-text")))
        for a, b in combinations(labels, 2):
            overlap_x = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            overlap_y = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            assert min(overlap_x, overlap_y) <= 1, (master, a[-1], b[-1])


def test_all_motion_help_has_signed_letters_and_reference_views():
    entries = json.loads((ART / "artwork-manifest.json").read_text())
    motions = [entry for entry in entries if "/AxisMotion/" in entry["target"]]
    assert len(motions) == 8
    for entry in motions:
        master = ET.parse(ROOT / entry["source"]).getroot()
        filename = Path(entry["target"]).stem
        axis = filename.removeprefix("AxisMotion_")[0]
        direction = axis + ("+" if filename.endswith("Pos") else "−")
        labels = {node.get("data-parameter") for node in master.iter()}
        assert direction in labels
        assert any("view" in caption.lower() for caption in entry["description"])
        with Image.open(ROOT / entry["target"]) as image:
            assert image.size == (512, 512)


def _artwork_strokes(drawing):
    import math
    import re

    segments = []
    for node in drawing:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag == "rect" and node.get("x") != "3":
            x, y, width, height = [float(node.get(key)) for key in ("x", "y", "width", "height")]
            points = [(x, y), (x + width, y), (x + width, y + height), (x, y + height), (x, y)]
            segments.extend(zip(points, points[1:]))
        elif tag == "circle":
            x, y, radius = [float(node.get(key)) for key in ("cx", "cy", "r")]
            points = [
                (x + radius * math.cos(step * math.pi / 32), y + radius * math.sin(step * math.pi / 32))
                for step in range(65)
            ]
            segments.extend(zip(points, points[1:]))
        elif tag == "path":
            start = last = None
            for command in re.split("(?=[MLAZ])", node.get("d", "")):
                if not command:
                    continue
                values = re.findall(r"-?\d+(?:\.\d+)?(?:e[+-]?\d+)?", command)
                if command[0] in ("M", "L") and len(values) == 2:
                    point = tuple(map(float, values))
                    if command[0] == "L" and last is not None:
                        segments.append((last, point))
                    if command[0] == "M":
                        start = point
                    last = point
                elif command[0] == "Z" and last is not None:
                    segments.append((last, start))
                elif command[0] == "A":
                    last = None
    return segments


def test_probe_parameter_labels_clear_dimension_lines_and_stock_outlines():
    import math

    for master in (ART / "probing").rglob("*.svg"):
        drawing = ET.parse(master).getroot()
        strokes = _artwork_strokes(drawing)
        for group in drawing.iter():
            parameter = group.get("data-parameter")
            if not parameter:
                continue
            label = next(node for node in group if node.get("data-label-box"))
            x, y, width, height = map(float, label.get("data-label-box").split(","))
            for start, end in strokes:
                steps = max(2, math.ceil(math.dist(start, end)))
                collision = any(
                    x - 2 < start[0] + (end[0] - start[0]) * step / steps < x + width + 2
                    and y - 2 < start[1] + (end[1] - start[1]) * step / steps < y + height + 2
                    for step in range(steps + 1)
                )
                assert not collision, (master, parameter, start, end)
