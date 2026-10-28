import __future__

from unittest.mock import patch

import pytest
from kivy.lang import Builder

from carveracontroller.CNC import CNC
from tests.integration.conftest import pump_frames


@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize("rotation", [0.0, 12.5, -3.75])
@pytest.mark.parametrize("touch", [False, True])
def test_rotation_ok_sends_the_angle_and_closes(kivy_app, rotation, touch, deferred, monkeypatch):
    app = kivy_app
    rule = next(rule for _selector, rule in Builder.rules if rule.name == "<SetRotationPopup>")
    nodes = [rule]
    while nodes:
        node = nodes.pop()
        if node.id == "btn_ok":
            break
        nodes.extend(node.children)
    handler = next(handler for handler in node.handlers if handler.name == "on_release")
    if deferred:
        # Exercise deferred annotations on older host interpreters too.
        code = compile(handler.value, "<rotation button>", "exec", flags=__future__.annotations.compiler_flag)
        monkeypatch.setattr(handler, "co_value", code)
    popup = app.root.set_rotation_popup
    old_touch = app.android_touch
    old_rotation = CNC.vars["rotation_angle"]
    try:
        app.android_touch = touch
        CNC.vars["rotation_angle"] = 17.25
        popup.open(animation=False)
        pump_frames(4)
        assert popup.ids.txt_rotation.text == "17.250"
        popup.ids.txt_rotation.text = str(rotation)
        with patch.object(app.root.controller, "sendGCode") as send:
            popup.ids.btn_ok.dispatch("on_release")
            send.assert_called_once_with(f"G10L2R{rotation:.3f}P0")
        pump_frames(8)
        assert not popup._is_open
    finally:
        popup.dismiss(animation=False)
        app.android_touch = old_touch
        CNC.vars["rotation_angle"] = old_rotation
