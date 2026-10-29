import os
import sys
import tempfile

from carveracontroller.runtime_profile import prepare

prepare()

_simulation_home = None
if os.environ.get("CARVERA_SIMULATION") == "1" and "KIVY_HOME" not in os.environ:
    _simulation_home = tempfile.TemporaryDirectory(prefix="carvera-simulation-")
    os.environ["KIVY_HOME"] = _simulation_home.name

import certifi

if getattr(sys, "frozen", False):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from carveracontroller.main import main
from carveracontroller.translation import tr

if __name__ == "__main__":
    main()
