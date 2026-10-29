"""Check kiosk ownership and the final, restricted sudo policy before imaging."""

import subprocess
import sys
from pathlib import Path


def verify(root):
    root = Path(root)
    paths = list((root / "opt/carvera/maintenance").rglob("*"))
    paths += list((root / "etc/carvera").rglob("*"))
    paths += list((root / "etc/systemd/system").glob("carvera-*.service"))
    paths += [root / "usr/local/sbin" / name for name in ("carvera-maint", "carvera-recover")]
    paths += [root / "etc/sudoers.d/carvera"]
    for path in paths:
        info = path.lstat()
        if path.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError(f"Privileged kiosk files must be owned by root and read-only to other users: {path}")
    for user, helper in (("carvera-admin", "carvera-maint"), ("carvera", "carvera-recover")):
        result = subprocess.run(["chroot", str(root), "sudo", "-n", "-l", "-U", user],
                                capture_output=True, text=True, check=True)
        expected = f'(root) NOPASSWD: /usr/local/sbin/{helper} ""'
        rules = [line.strip() for line in result.stdout.splitlines() if line.strip().startswith("(")]
        if rules != [expected]:
            raise ValueError(f"Unexpected sudo permissions for {user}: {rules}")
    for role in ("carvera", "carvera-admin"):
        result = subprocess.run(["chroot", str(root), "id", "-nG", role], capture_output=True, text=True, check=True)
        if "sudo" in result.stdout.split():
            raise ValueError(f"{role} must not belong to the sudo group")
    code = """
import ctypes
import importlib.metadata
package = importlib.metadata.distribution('Kivy')
assert not any(str(path).startswith('Kivy.libs/') for path in package.files), 'Kivy must use system SDL2'
window = next(path for path in package.files if path.name.startswith('_window_sdl2.') and path.suffix == '.so')
ctypes.PyDLL(str(package.locate_file(window)))
sdl = ctypes.CDLL('libSDL2-2.0.so.0')
sdl.SDL_GetVideoDriver.restype = ctypes.c_char_p
drivers = [sdl.SDL_GetVideoDriver(i).decode() for i in range(sdl.SDL_GetNumVideoDrivers())]
assert 'wayland' in drivers, drivers
print('ARM64 Kivy extension loaded; SDL Wayland backend verified.')
"""
    subprocess.run(["chroot", str(root), "/opt/carvera/current/venv/bin/python", "-c", code], check=True)
    print("Kiosk helper ownership and restricted sudo permissions verified.")


if __name__ == "__main__":
    verify(sys.argv[1])
