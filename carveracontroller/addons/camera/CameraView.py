"""Camera frame display with host-side brightness, contrast and gamma."""

import logging
from io import BytesIO

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.graphics import Rectangle, RenderContext
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.popup import Popup
from kivy.uix.widget import Widget

ADJUST_MIN = 0.2
ADJUST_MAX = 3.0
ADJUST_DEFAULT = 1.0

_FRAGMENT_SHADER = """
$HEADER$
uniform float brightness;
uniform float contrast;
uniform float gamma;
void main(void) {
    vec4 frame = texture2D(texture0, tex_coord0);
    vec3 rgb = frame.rgb * brightness;
    rgb = (rgb - 0.5) * contrast + 0.5;
    rgb = clamp(rgb, 0.0, 1.0);
    rgb = pow(rgb, vec3(1.0 / max(gamma, 0.01)));
    gl_FragColor = vec4(clamp(rgb, 0.0, 1.0), frame.a) * frag_color;
}
"""

logger = logging.getLogger(__name__)


class CameraView(Widget):
    """Letterboxes the latest camera frame and grades it through a shader.

    The stream carries no sensor exposure control, so brightness, contrast and
    gamma are applied on the host and cannot recover fully clipped highlights.
    """

    texture = ObjectProperty(None, allownone=True)
    brightness = NumericProperty(ADJUST_DEFAULT)
    contrast = NumericProperty(ADJUST_DEFAULT)
    gamma = NumericProperty(ADJUST_DEFAULT)

    def __init__(self, **kwargs):
        self.canvas = RenderContext(use_parent_projection=True, use_parent_modelview=True)
        self.canvas.shader.fs = _FRAGMENT_SHADER
        super().__init__(**kwargs)
        with self.canvas:
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self._update_uniforms()
        self.bind(
            pos=self._layout_frame,
            size=self._layout_frame,
            texture=self._layout_frame,
            brightness=self._update_uniforms,
            contrast=self._update_uniforms,
            gamma=self._update_uniforms,
        )

    def show_frame(self, jpeg):
        """Decode one JPEG frame, dropping partial or garbled ones."""
        try:
            texture = CoreImage(BytesIO(jpeg), ext="jpg").texture
        except Exception as exc:
            logger.warning("Camera frame decode failed: %s", exc)
            return
        texture.mag_filter = "linear"
        texture.min_filter = "linear"
        self.texture = texture

    def _update_uniforms(self, *args):
        self.canvas["brightness"] = float(self.brightness)
        self.canvas["contrast"] = float(self.contrast)
        self.canvas["gamma"] = float(self.gamma)
        self.canvas.ask_update()

    def _layout_frame(self, *args):
        """Fit the frame to its own aspect ratio so it is never distorted."""
        self._rect.texture = self.texture
        frame_width, frame_height = self.texture.size if self.texture else (0, 0)
        width, height = self.size
        if not (frame_width and frame_height and width and height):
            self._rect.size = self.size
            self._rect.pos = self.pos
            return
        scale = min(width / float(frame_width), height / float(frame_height))
        fitted_width, fitted_height = frame_width * scale, frame_height * scale
        self._rect.size = (fitted_width, fitted_height)
        self._rect.pos = (self.x + (width - fitted_width) / 2.0, self.y + (height - fitted_height) / 2.0)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if self.collide_point(*touch.pos):
            return True
        return super().on_touch_up(touch)


class CameraControls(BoxLayout):
    """Keep compact camera adjustments in a bounded, scrollable dialog."""

    adjust_open = BooleanProperty(False)
    adjust_popup = ObjectProperty(None, allownone=True)

    def on_kv_post(self, _base_widget):
        Clock.schedule_once(self._bind_app, 0)

    def _bind_app(self, _dt):
        app = App.get_running_app()
        if app is not None:
            app.bind(camera_streaming=self._sync_adjust_popup,
                     supports_camera=self._sync_adjust_popup,
                     android_touch=self._sync_adjust_popup)
            if app.root is not None:
                app.root.content.bind(current=self._page_changed)
        self._sync_adjust_popup()

    def on_parent(self, _instance, parent):
        if parent is None and self.adjust_popup is not None:
            self.adjust_popup.dismiss()

    def on_adjust_open(self, *_args):
        self._sync_adjust_popup()

    def _page_changed(self, _content, page):
        if page != "File" and self.adjust_popup is not None:
            self.adjust_popup.dismiss()

    def _sync_adjust_popup(self, *_args):
        app = App.get_running_app()
        if app is None or "adjust_panel" not in self.ids:
            return
        visible = self.adjust_open and app.camera_streaming and app.supports_camera and app.android_touch
        if not visible:
            if self.adjust_popup is not None:
                self.adjust_popup.dismiss()
            return
        if self.adjust_popup is not None:
            return
        from carveracontroller.__main__ import tr
        from carveracontroller.ui.android_layout import DialogActions, DialogSurface

        panel = getattr(self.ids.adjust_panel, "__self__", self.ids.adjust_panel)
        self._inline_viewport = panel.parent
        self._inline_viewport.remove_widget(panel)
        surface = DialogSurface()
        surface.add_widget(panel)
        actions = DialogActions()
        close = Button(text=tr._("Close"))
        actions.add_widget(close)
        surface.add_widget(actions)
        popup = Popup(title=tr._("Camera adjustments"), content=surface, size_hint=(.9, .9))
        self.adjust_popup = popup
        close.bind(on_release=lambda *_: popup.dismiss())
        popup.bind(on_dismiss=self._restore_inline_adjustments)
        popup.open()

    def _restore_inline_adjustments(self, *_args):
        panel = getattr(self.ids.adjust_panel, "__self__", self.ids.adjust_panel)
        if panel.parent is not None:
            panel.parent.remove_widget(panel)
        self._inline_viewport.add_widget(panel)
        self.adjust_popup = None
        self.adjust_open = False
