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
        import setup_status_ui
        from kivy.base import EventLoop

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
        try:
            app._run_prepare()
            for _ in range(20):
                EventLoop.idle()
                time.sleep(0.01)
            assert "carveracontroller.main" not in sys.modules and "carveracontroller.Controller" not in sys.modules
            assert not any(name.endswith(("USBStream", "WifiStream")) for name in sys.modules)
            assert "isolated-test-fingerprint" in app.details.text
            assert "could not finish" in app.message.text
            from carveracontroller.ui import theme

            assert Path(theme.__file__).resolve().is_relative_to(presentation)
            assert Path(app.details._label.options["font_name_r"]).resolve().is_relative_to(presentation)
            app.request("setup-retry")
            for _ in range(20):
                EventLoop.idle()
                time.sleep(0.01)
            assert requests == ["setup-retry"] and not app.pending
            assert "Retrying setup" in app.feedback.text
            from kivy.core.window import Window

            capture = Window.screenshot(name=str(reports / "setup-window.png"))
            Path(capture).replace(reports / "setup-limited.png")
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
