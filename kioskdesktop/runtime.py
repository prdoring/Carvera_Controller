"""Load only the shared standard-library runtime, independently of the controller."""

import importlib.util
import sys
from pathlib import Path


def shared(name):
    if name not in {"admin_accounts", "setup_protocol", "settings"}:
        raise ValueError("Unknown shared runtime")
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    directory = root / "runtime"
    if not directory.is_dir():
        directory = root / "assets/packaging/kiosk/runtime"
    if not directory.is_dir():
        directory = root / "bootstrap"
    spec = importlib.util.spec_from_file_location("kiosk_shared_" + name, directory / (name + ".py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("The shared setup runtime is missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
