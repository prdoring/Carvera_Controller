"""The recovery application must import and render without the controller."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Requires the isolated graphical test runner")
def test_independent_system_assets_and_readiness(tmp_path):
    source = ROOT / "assets/packaging/kiosk/build_system_bundle.py"
    spec = importlib.util.spec_from_file_location("system_assets", source)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    release = tmp_path / "independent-system"
    runtime = release / "runtime"
    runtime.mkdir(parents=True)
    builder.presentation(ROOT, release / "system-ui")
    for name in ("recovery.py", "system_ui.py", "admin_accounts.py"):
        shutil.copyfile(source.parent / "runtime" / name, runtime / name)
    for name in ("runtime_profile.py", "kiosk_touch.py"):
        shutil.copyfile(ROOT / "carveracontroller" / name, runtime / name)
    (release / "system-bundle.json").write_text('{"version":"independent-test"}')
    script = r"""
import json, os, sys, time
from pathlib import Path
root = Path(sys.argv[1])
sys.path[:0] = [str(root / "runtime"), str(root / "system-ui")]
os.environ.update(CARVERA_PROFILE="kiosk", CARVERA_DATA_DIR=str(root / "data"),
                  CARVERA_RUNTIME_DIR=str(root / "run"), CARVERA_MAINT_DIR=str(root / "maint"))
import recovery
from kivy.base import EventLoop
from kivy.clock import Clock
from kivy.core.window import Window
recovery.call_helper = lambda request: {"controller": {}, "system": {"version": "independent-test"}}
app = recovery.Recovery()
try:
    app._run_prepare()
    for _ in range(100):
        EventLoop.idle()
        Clock.tick()
        time.sleep(.02)
    marker = json.loads((root / "run/system-ready.json").read_text())
    assert marker["system_version"] == "independent-test" and marker["pid"] == os.getpid()
    assert "carveracontroller.main" not in sys.modules
    assert "carveracontroller.Controller" not in sys.modules
    assert str(root / "system-ui") in recovery.theme.__file__
    assert app.details["system"]["version"] == "independent-test"
    Window.screenshot(name=str(root / "independent-system.png"))
finally:
    app.stop()
    EventLoop.close()
assert not (root / "run/system-ready.json").exists()
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(release)], cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr[-6000:]
