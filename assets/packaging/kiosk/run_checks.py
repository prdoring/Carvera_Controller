"""Run Linux UI checks on a private virtual display without TCP listeners."""

import os
import select
import subprocess
import sys


def main():
    read, write = os.pipe()
    display = subprocess.Popen([
        "Xvfb", "-displayfd", str(write), "-screen", "0", "1920x1200x24", "-nolisten", "tcp",
    ], pass_fds=(write,))
    os.close(write)
    try:
        if not select.select([read], [], [], 15)[0]:
            raise RuntimeError("The test display did not become ready")
        number = os.read(read, 32).decode().strip()
        if not number.isdecimal():
            raise RuntimeError("The test display failed to start")
        environment = dict(os.environ, DISPLAY=":" + number)
        return subprocess.run([sys.executable, "-m", "pytest", *sys.argv[1:]], env=environment, check=False).returncode
    finally:
        os.close(read)
        display.terminate()
        try:
            display.wait(timeout=5)
        except subprocess.TimeoutExpired:
            display.kill()
            display.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
