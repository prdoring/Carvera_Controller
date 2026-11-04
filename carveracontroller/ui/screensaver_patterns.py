"""Bounded workshop drawings and screensaver selection, independent of Kivy."""

import math
import random

STYLES = ("clock", "toolpath", "contours", "block", "orbits", "parts")
TIMEOUTS = (0, 1, 2, 5, 10, 15, 30)
CYCLE_SECONDS = 33
ROTATION_SECONDS = 30 * 60


def preferences(values):
    try:
        minutes = int(values.get("screensaver_timeout_minutes", "30"))
    except (TypeError, ValueError):
        minutes = 30
    if minutes not in TIMEOUTS:
        minutes = 30
    style = values.get("screensaver_style", "random")
    if style not in (*STYLES, "random"):
        style = "random"
    return minutes, style, str(values.get("screensaver_show_clock", "1")).lower() not in ("0", "false", "no")


class Rotation:
    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.bag = []
        self.previous = None

    def next(self):
        if not self.bag:
            self.bag = list(STYLES)
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
    return []


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
