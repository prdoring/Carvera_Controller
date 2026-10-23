"""Generate the small, stretchable Slate Workshop control textures."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "carveracontroller/data/theme"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, radius, fill in [
        ("button", 6, 245),
        ("button-down", 6, 208),
        ("button-disabled", 6, 145),
        ("field", 6, 255),
        ("field-focus", 6, 255),
        ("panel", 9, 255),
    ]:
        image = Image.new("RGBA", (128, 128))
        draw = ImageDraw.Draw(image)
        mask = Image.new("L", image.size)
        md = ImageDraw.Draw(mask)
        md.rounded_rectangle((2, 2, 125, 123), radius=radius * 4, fill=255)
        for y in range(128):
            level = max(0, min(255, round(fill + 10 - y * (0.50 if name == "button" else 0.22))))
            draw.line((0, y, 127, y), fill=(level, level, level, 255))
        image.putalpha(mask)
        image.resize((32, 32), Image.Resampling.LANCZOS).save(OUT / (name + ".png"))
    surface = Image.new("RGBA", (64, 128))
    sd = ImageDraw.Draw(surface)
    for y in range(128):
        v = round(255 - y * 0.55)
        sd.line((0, y, 63, y), fill=(v, v, v, 255))
    surface.save(OUT / "surface.png")
    for radio in (False, True):
        for active, suffix in [(False, "off"), (True, "on"), (False, "disabled"), (True, "on-disabled")]:
            image = Image.new("RGBA", (128, 128))
            d = ImageDraw.Draw(image)
            muted = "disabled" in suffix
            color = "#829290" if muted else "#D69963" if active else "#B7C3C1"
            if radio:
                d.ellipse((28, 28, 100, 100), outline=color, width=6)
                if active:
                    d.ellipse((46, 46, 82, 82), fill=color)
            else:
                d.rounded_rectangle(
                    (28, 28, 100, 100), radius=12, outline=color, width=6, fill="#655343" if active else "#151C1D"
                )
                if active:
                    d.line([(44, 64), (58, 78), (86, 48)], fill=color, width=9)
            image.resize((32, 32), Image.Resampling.LANCZOS).save(
                OUT / (("radio-" if radio else "check-") + suffix + ".png")
            )
    im = Image.new("RGBA", (88, 88))
    d = ImageDraw.Draw(im)
    d.ellipse((3, 3, 84, 84), fill="#D69963", outline="#F0C49A", width=4)
    im.resize((22, 22), Image.Resampling.LANCZOS).save(OUT / "slider-thumb.png")
    Image.new("RGBA", (8, 3), "#566365").save(OUT / "slider-track.png")
    Image.new("RGBA", (3, 8), "#566365").save(OUT / "slider-track-vertical.png")


if __name__ == "__main__":
    main()
