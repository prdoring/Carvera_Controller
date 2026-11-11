"""Render the limited setup app using only the independent System presentation."""

import gettext
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

SOURCE = Path(__file__).resolve().parents[2]
ASSETS = SOURCE / "assets/packaging/kiosk"


def main():
    spec = importlib.util.spec_from_file_location("system_packager", ASSETS / "build_system_bundle.py")
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)
    reports = Path(os.environ.get("CARVERA_BOOT_REPORTS", "/tmp"))
    reports.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="carvera-independent-ui-") as temporary:
        release = Path(temporary)
        runtime = release / "runtime"
        runtime.mkdir()
        presentation = release / "system-ui"
        packager.presentation(SOURCE, presentation)
        for source in (presentation / "carveracontroller/locales").rglob("*.po"):
            subprocess.run(["msgfmt", str(source), "-o", str(source.with_suffix(".mo"))], check=True)
        assert isinstance(
            gettext.translation("en", presentation / "carveracontroller/locales", languages=["en"]),
            gettext.GNUTranslations,
        )
        for name in ("setup_status_ui.py", "system_ui.py"):
            shutil.copyfile(ASSETS / "runtime" / name, runtime / name)
        for name in ("runtime_profile.py", "kiosk_touch.py"):
            shutil.copyfile(SOURCE / "carveracontroller" / name, runtime / name)
        os.environ.update(CARVERA_PROFILE="kiosk", CARVERA_DATA_DIR=str(release / "data"), KIVY_NO_ARGS="1")
        Path("/var/lib/carvera/recovery").mkdir(parents=True, exist_ok=True)
        os.chdir(release)
        sys.path = [
            str(runtime),
            *(value for value in sys.path if value and not Path(value).resolve().is_relative_to(SOURCE)),
        ]
        # Xvfb has no window manager to size a fullscreen client. Set the
        # initial dimensions before SDL creates its native window.
        os.environ["KIVY_HOME"] = "/var/lib/carvera/recovery"
        from kivy.config import Config

        Config.set("graphics", "width", "1920")
        Config.set("graphics", "height", "1200")
        import setup_status_ui
        from kivy.base import EventLoop
        from kivy.core.window import Window

        Window.fullscreen = False
        Window.left = Window.top = 0

        status = Path("/run/carvera-maint/setup-status.json")
        status.parent.mkdir(parents=True, exist_ok=True)
        status.write_text(
            json.dumps(
                {"phase": "applying", "host_fingerprints": ["SHA256:isolated-test-fingerprint"], "error": "interrupted"}
            )
        )
        requests = []

        def call(arguments, **kwargs):
            assert arguments == ["sudo", "-n", "/usr/local/sbin/carvera-recover"]
            request = json.loads(kwargs["input"])
            assert set(request) == {"action", "id"} and len(request["id"]) == 32
            requests.append(request["action"])
            return SimpleNamespace(stdout='{"ok":true,"result":{"phase":"queued"}}')

        setup_status_ui.subprocess = SimpleNamespace(run=call)
        app = setup_status_ui.SetupStatus()
        failures = []
        from kivy.clock import Clock

        def capture(_dt):
            try:
                from PIL import ImageGrab

                from carveracontroller.ui import theme

                assert "Retrying setup" in app.feedback.text
                (reports / "setup-geometry.json").write_text(
                    json.dumps(
                        {"window": list(Window.size), "system": list(Window.system_size), "root": list(app.root.size)}
                    )
                )
                assert tuple(Window.size) == (1920, 1200)
                assert tuple(app.root.size) == tuple(Window.size)
                assert app.shutdown.right <= Window.width and app.shutdown.y >= 0
                picture = ImageGrab.grab()
                picture.save(reports / "setup-limited.png")
                expected = [round(channel * 255) for channel in theme.BACKGROUND[:3]]
                assert all(
                    abs(actual - target) <= 2 for actual, target in zip(picture.getpixel((1910, 1190)), expected)
                )
                status.write_text(json.dumps({"phase": "fresh", "error": "storage"}))
                app.refresh()
                assert "storage preparation" in app.message.text
                assert not app.retry.disabled
                status.write_text(json.dumps({"phase": "unknown"}))
                app.refresh()
                assert "needs recovery" in app.message.text
                assert app.retry.disabled
                app.pending_action = "setup-shutdown"
                app.finished(SimpleNamespace(result=lambda: SimpleNamespace(stdout='{"ok":true}')))
                assert "Shutting down" in app.feedback.text
            except Exception as error:
                failures.append(error)
            finally:
                app.stop()

        def check(_dt):
            try:
                assert "carveracontroller.main" not in sys.modules
                assert "carveracontroller.Controller" not in sys.modules
                assert not any(name.endswith(("USBStream", "WifiStream")) for name in sys.modules)
                assert "isolated-test-fingerprint" in app.details.text
                assert "Setup was interrupted" in app.message.text
                from carveracontroller.ui import theme

                assert Path(theme.__file__).resolve().is_relative_to(presentation)
                assert Path(app.details._label.options["font_name_r"]).resolve().is_relative_to(presentation)
                app.request("setup-retry")
                deadline = time.monotonic() + 10

                def ready(_dt):
                    if time.monotonic() >= deadline:
                        failures.append(TimeoutError("The limited setup action did not finish"))
                        app.stop()
                        return False
                    if app.pending:
                        return True
                    if requests != ["setup-retry"]:
                        failures.append(AssertionError("Unexpected limited setup action"))
                        app.stop()
                    else:
                        Clock.schedule_once(capture, 0.1)
                    return False

                Clock.schedule_interval(ready, 0.05)
            except Exception as error:
                failures.append(error)
                app.stop()

        try:
            Clock.schedule_once(check, 0.3)
            app.run()
            if failures:
                raise failures[0]
            print("PASS: independent limited setup UI, bundled fonts/translations, fixed helper request", flush=True)
        finally:
            app.stop()
            EventLoop.close()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc(file=sys.__stderr__)
        raise SystemExit(1) from None
