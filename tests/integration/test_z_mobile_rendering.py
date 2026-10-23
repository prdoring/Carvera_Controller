"""Reviewed mobile dialog baselines are required, including on a fresh checkout."""

from pathlib import Path

import pytest
from kivy.core.window import Window
from PIL import Image, ImageChops, ImageStat

from tests.integration.conftest import pump_frames, set_window_size


@pytest.mark.parametrize("scene", ["input", "unlock"])
def test_mobile_dialog_rendering(mobile, update_references, tmp_path, scene):
    from carveracontroller.main import InputPopup, UnlockPopup

    app, _ = mobile
    set_window_size((800, 480))
    modal = InputPopup() if scene == "input" else UnlockPopup()
    if scene == "input":
        modal.lb_title.text = "Name this saved position"
        modal.txt_content.text = "Fixture origin"
        modal.txt_content.focus = False
    modal.open(animation=False)
    pump_frames(24)
    screenshot = Window.screenshot(name=str(tmp_path / "window.png"))
    with Image.open(screenshot) as image:
        # Exclude the translucent backdrop and rounded outside edge.
        actual = image.convert("RGB").crop((round(modal.x + 12), round(Window.height - modal.top + 12),
                                            round(modal.right - 12), round(Window.height - modal.y - 12)))
    baseline = Path(__file__).parent / "reference" / f"mobile-{scene}.png"
    if update_references:
        baseline.parent.mkdir(exist_ok=True)
        actual.save(baseline)
    assert baseline.is_file(), f"Required mobile baseline missing: {baseline}"
    with Image.open(baseline) as reference:
        actual.save(tmp_path / f"mobile-{scene}-actual.png")
        assert actual.size == reference.size
        difference = ImageChops.difference(actual, reference.convert("RGB"))
        error = sum(ImageStat.Stat(difference).mean) / 3
        if error > .5:
            actual.save(tmp_path / f"mobile-{scene}-actual.png")
            difference.save(tmp_path / f"mobile-{scene}-difference.png")
        assert error <= .5, f"Mobile rendering changed (mean pixel error {error:.2f}); review {tmp_path}"
