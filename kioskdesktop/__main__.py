"""Standalone desktop entry point, also used by frozen applications."""

import argparse
import json
import sys
from pathlib import Path


def main():
    metadata = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "desktop-build.json"
    kind = json.loads(metadata.read_text(encoding="utf-8")).get("kind") if metadata.exists() else "setup"
    if len(sys.argv) > 1 and sys.argv[1] == "--disk-worker":
        if kind != "setup":
            raise SystemExit(1)
        from kioskdesktop.disk_worker import main as disk_worker

        try:
            disk_worker(sys.argv[2:])
        except Exception:
            raise SystemExit(1) from None
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--viewer-server":
        from kioskdesktop.worker_io import inherited_pipes

        inherited_pipes()
        from kioskdesktop.viewer_server import main as viewer_worker

        try:
            viewer_worker(sys.argv[2:])
        except Exception:
            raise SystemExit("The private viewer worker could not start") from None
        return
    parser = argparse.ArgumentParser(description="Carvera Kiosk Setup and Screen Share")
    parser.add_argument("--viewer", action="store_true")
    parser.add_argument("--design-slice", choices=("setup", "erase", "viewer"))
    parser.add_argument("--capture", help=argparse.SUPPRESS)
    parser.add_argument("--self-check", type=Path, help="Write a new nonsecret offline runtime report")
    args = parser.parse_args()
    if args.self_check:
        from kioskdesktop.diagnostics import check
        from kioskdesktop.worker_io import inherited_pipes

        inherited_pipes()
        try:
            check(args.self_check)
        except Exception:
            import traceback

            traceback.print_exc(file=sys.stderr)
            raise SystemExit(1) from None
        return
    from kioskdesktop.gui import launch

    launch(viewer=args.viewer or kind == "viewer", design_slice=args.design_slice, capture=args.capture)


if __name__ == "__main__":
    main()
