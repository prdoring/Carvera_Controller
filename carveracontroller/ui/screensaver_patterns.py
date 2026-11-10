"""Bounded workshop drawings and screensaver selection, independent of Kivy."""

import math
import random
from itertools import zip_longest

TIMEOUTS = (0, 1, 2, 5, 10, 15, 30)
CYCLE_SECONDS = 33
ROTATION_SECONDS = 30 * 60


def _polar(cx, cy, radius, angle):
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


def _gear_mesh(rng):
    large, small = rng.choice((16, 18)), rng.choice((10, 12))
    pitch = 0.015
    outlines, bores = [], []
    for teeth, cx, phase in ((large, -small * pitch, 0), (small, large * pitch, math.pi + math.pi / small)):
        radius = teeth * pitch
        step = math.tau / teeth
        outline = [
            _polar(cx, 0, radius + offset, phase + (tooth + fraction) * step)
            for tooth in range(teeth)
            for fraction, offset in ((-0.4, -0.02), (-0.2, 0.016), (0.2, 0.016), (0.4, -0.02))
        ]
        outlines.append([*outline, outline[0]])
        bore = radius * 0.34
        bores.append(ellipse(cx, 0, bore, bore, count=36))
    return [*outlines, *bores]


def _pcb_routing(rng):
    routes = (
        ((-0.08, 0.08), (-0.08, 0.15), (-0.14, 0.21), (-0.30, 0.21), (-0.37, 0.28)),
        ((0.01, 0.08), (0.01, 0.21), (0.07, 0.27), (0.17, 0.27)),
        ((-0.16, 0.04), (-0.28, 0.04), (-0.36, 0.12), (-0.51, 0.12)),
        ((-0.16, -0.04), (-0.29, -0.04), (-0.35, -0.10), (-0.50, -0.10)),
        ((0.16, 0.03), (0.30, 0.03), (0.37, -0.04), (0.50, -0.04)),
        ((0.16, -0.04), (0.25, -0.04), (0.34, -0.13), (0.46, -0.13)),
        ((-0.09, -0.08), (-0.09, -0.17), (-0.16, -0.24), (-0.32, -0.24)),
        ((0.07, -0.08), (0.07, -0.18), (0.15, -0.26), (0.27, -0.26)),
        ((0.38, 0.18), (0.43, 0.18), (0.49, 0.24), (0.55, 0.24)),
        ((0.33, 0.23), (0.33, 0.29), (0.38, 0.34)),
    )
    paths = []
    for route in routes:
        x, y = route[-1]
        previous_x, previous_y = route[-2]
        angle = math.atan2(previous_y - y, previous_x - x)
        paths.append([*route[:-1], _polar(x, y, 0.013, angle)])
        paths.append(ellipse(x, y, 0.013, 0.013, angle, count=16))
    paths.extend(
        (
            [(0.10, 0.08), (0.10, 0.12), (0.16, 0.18), (0.28, 0.18)],
            [(-0.16, -0.08), (0.16, -0.08), (0.16, 0.08), (-0.16, 0.08), (-0.16, -0.08)],
            [(0.28, 0.13), (0.38, 0.13), (0.38, 0.23), (0.28, 0.23), (0.28, 0.13)],
        )
    )
    direction = rng.choice((-1, 1))
    return [[(direction * x, y) for x, y in path] for path in paths]


def _turbine_impeller(rng):
    vanes = rng.randint(7, 9)
    phase = rng.uniform(0, math.tau)
    sweep = rng.uniform(0.64, 0.90)
    hub, rim = 0.06, 0.31
    paths = []
    for vane in range(vanes):
        angle = phase + vane * math.tau / vanes
        outline = [
            _polar(0, 0, hub + (rim - hub) * t, angle + sweep * t + side * 0.26 * math.sin(math.pi * t))
            for side, samples in ((0, range(19)), (1, range(17, -1, -1)))
            for t in (step / 18 for step in samples)
        ]
        paths.append(outline)
    return [*paths, ellipse(0, 0, hub, hub, count=40), ellipse(0, 0, rim, rim)]


def _basket_weave(rng):
    pitch = 0.15
    half_width = rng.uniform(0.024, 0.032)
    gap = half_width + 0.006
    columns = [(i - 2.5) * pitch for i in range(6)]
    rows = [(i - 1.5) * pitch for i in range(4)]

    def strips(centers, crossings, first_gap):
        left, right = crossings[0] - pitch / 2, crossings[-1] + pitch / 2
        for i, y in enumerate(centers):
            gaps = crossings[(i + first_gap) % 2 :: 2]
            starts = [left, *(x + gap for x in gaps)]
            ends = [*(x - gap for x in gaps), right]
            top, bottom = y + half_width, y - half_width
            paths = []
            for start, end in zip(starts, ends):
                if start == left:
                    cap = [_polar(left, y, half_width, math.pi * (0.5 + j / 8)) for j in range(9)]
                    paths.append([(end, top), *cap, (end, bottom)])
                elif end == right:
                    cap = [_polar(right, y, half_width, math.pi * (-0.5 + j / 8)) for j in range(9)]
                    paths.append([(start, bottom), *cap, (start, top)])
                else:
                    paths.extend(([(start, top), (end, top)], [(end, bottom), (start, bottom)]))
            yield paths

    vertical = ([[(y, x) for x, y in path] for path in strip] for strip in strips(columns, rows, 1))
    strips_in_order = zip_longest(strips(rows, columns, 0), vertical, fillvalue=())
    return [path for pair in strips_in_order for strip in pair for path in strip]


def _waveform(rng):
    phase = rng.uniform(0, math.tau)
    frequency = rng.uniform(1.4, 1.8)
    samples = [(t, 0.23 * math.cos(t * math.pi / 2) ** 2) for t in (i / 48 - 1 for i in range(97))]
    wave = [(0.6 * t, height * math.sin(math.tau * (frequency * t + 2.4 * t**3) + phase)) for t, height in samples]
    return [wave, *[[(0.6 * t, sign * height) for t, height in samples] for sign in (1, -1)]]


def _bridge_truss(rng):
    bays = rng.randint(5, 7)
    pitch, height = 0.16, rng.uniform(0.18, 0.26)
    deck = [(i * pitch, 0) for i in range(bays + 1)]
    top = [((i + 0.5) * pitch, height * (0.76 if i in (0, bays - 1) else 1)) for i in range(bays)]
    braces = [point for pair in zip(deck, top) for point in pair] + [deck[-1]]
    span = deck[-1][0]
    return [
        braces,
        [deck[0], deck[-1]],
        top,
        [(0, 0), (0, -0.065), (0.035, -0.065), (0.035, 0)],
        [(span, 0), (span, -0.065), (span - 0.035, -0.065), (span - 0.035, 0)],
    ]


_PATTERNS = {
    "gears": _gear_mesh,
    "pcb": _pcb_routing,
    "impeller": _turbine_impeller,
    "weave": _basket_weave,
    "waveform": _waveform,
    "truss": _bridge_truss,
}
TRACE_STYLES = ("toolpath", "contours", "block", "orbits", *_PATTERNS)
STYLES = ("clock", *TRACE_STYLES, "parts")
STYLE_OPTIONS = (*STYLES, "random_traces", "random")


def preferences(values):
    try:
        minutes = int(values.get("screensaver_timeout_minutes", "30"))
    except (TypeError, ValueError):
        minutes = 30
    if minutes not in TIMEOUTS:
        minutes = 30
    style = values.get("screensaver_style", "random")
    if style not in STYLE_OPTIONS:
        style = "random"
    return minutes, style, str(values.get("screensaver_show_clock", "1")).lower() not in ("0", "false", "no")


class Rotation:
    def __init__(self, rng=None, *, styles=STYLES):
        self.rng = rng or random.Random()
        self.styles = styles
        self.bag = []
        self.previous = None

    def next(self):
        if not self.bag:
            self.bag = list(self.styles)
            self.rng.shuffle(self.bag)
            if self.bag[-1] == self.previous:
                self.bag[0], self.bag[-1] = self.bag[-1], self.bag[0]
        self.previous = self.bag.pop()
        return self.previous


def ellipse(cx, cy, rx, ry, angle=0, count=80):
    ca, sa = math.cos(angle), math.sin(angle)
    points = []
    for i in range(count + 1):
        t = i * math.tau / count
        x, y = rx * math.cos(t), ry * math.sin(t)
        points.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return points


def pattern(style, rng):
    """Return separate polylines in a normalized, clock-free drawing area."""
    paths = _pattern(style, rng)
    if not paths:
        return paths
    xs = [x for path in paths for x, _ in path]
    ys = [y for path in paths for _, y in path]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    scale = min(0.84 / (max(xs) - min(xs)), 0.64 / (max(ys) - min(ys)), 1)
    center_x, center_y = rng.uniform(0.47, 0.53), rng.uniform(0.48, 0.52)
    return [[(center_x + (x - cx) * scale, center_y + (y - cy) * scale) for x, y in path] for path in paths]


def _pattern(style, rng):
    if style == "toolpath":
        paths = []
        width, height = rng.uniform(0.32, 0.4), rng.uniform(0.24, 0.32)
        for i in range(rng.randint(5, 8)):
            rx, ry = width - i * 0.035, height - i * 0.026
            radius = min(0.045, ry / 2)
            line = []
            for cx, cy, start in (
                (rx - radius, ry - radius, 0),
                (-rx + radius, ry - radius, 90),
                (-rx + radius, -ry + radius, 180),
                (rx - radius, -ry + radius, 270),
            ):
                for step in range(9):
                    t = math.radians(start + step * 90 / 8)
                    line.append((0.5 + cx + radius * math.cos(t), 0.5 + cy + radius * math.sin(t)))
            line.append(line[0])
            paths.append(line)
        return paths
    if style == "contours":
        phase = rng.uniform(0, math.tau)
        lobes = rng.randint(2, 4)
        cx, cy = rng.uniform(0.42, 0.58), rng.uniform(0.43, 0.57)
        return [
            [
                (
                    cx + r * math.cos(t) * (1 + 0.14 * math.sin(lobes * t + phase)),
                    cy + r * 0.78 * math.sin(t) * (1 + 0.12 * math.cos(3 * t + phase)),
                )
                for t in (i * math.tau / 96 for i in range(97))
            ]
            for r in (0.07, 0.12, 0.17, 0.22, 0.27, 0.32, 0.37)
        ]
    if style == "orbits":
        return [
            ellipse(
                rng.uniform(0.42, 0.58),
                rng.uniform(0.42, 0.58),
                rng.uniform(0.2, 0.31),
                rng.uniform(0.08, 0.19),
                rng.uniform(0, math.pi),
            )
            for _ in range(rng.randint(3, 5))
        ]
    if style == "block":
        width, depth, height = rng.uniform(0.55, 0.7), rng.uniform(0.38, 0.55), rng.uniform(0.17, 0.27)

        def project(x, y, z):
            return (0.5 + (x - y) * 0.55, 0.38 + (x + y) * 0.28 + z)

        a, b, c, d = [project(x, y, height) for x, y in ((0, 0), (width, 0), (width, depth), (0, depth))]
        low_a, low_b, low_d = project(0, 0, 0), project(width, 0, 0), project(0, depth, 0)
        margin = rng.uniform(0.07, 0.11)
        pocket = [
            (margin, margin),
            (width - margin, margin),
            (width - margin, depth * 0.55),
            (width * 0.55, depth * 0.55),
            (width * 0.55, depth - margin),
            (margin, depth - margin),
        ]
        top = [project(x, y, height) for x, y in pocket]
        floor = [project(x, y, height * 0.6) for x, y in pocket]
        return [
            [a, b, c, d, a],
            [b, low_b, low_a, low_d, d],
            [a, low_a],
            [*top, top[0]],
            [*floor, floor[0]],
            *[[p, q] for p, q in zip(top, floor)],
        ]
    draw = _PATTERNS.get(style)
    if draw is None:
        return []
    # Convert equal units on both axes to the kiosk's 16:10 drawing area.
    return [[(x / 1.6, y) for x, y in path] for path in draw(rng)]


class Trace:
    def __init__(self, points):
        self.points = points
        self.lengths = [0.0]
        for a, b in zip(points, points[1:]):
            self.lengths.append(self.lengths[-1] + math.dist(a, b))
        self.length = self.lengths[-1]

    def prefix(self, distance):
        if distance <= 0:
            return []
        if distance >= self.length:
            return self.points
        result = [self.points[0]]
        for i in range(1, len(self.points)):
            if self.lengths[i] <= distance:
                result.append(self.points[i])
                continue
            a, b = self.points[i - 1], self.points[i]
            fraction = (distance - self.lengths[i - 1]) / (self.lengths[i] - self.lengths[i - 1])
            result.append((a[0] + (b[0] - a[0]) * fraction, a[1] + (b[1] - a[1]) * fraction))
            break
        return result
