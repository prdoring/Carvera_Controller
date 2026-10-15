"""Isolated UI development with recorded commands and no physical transports."""

import os
import socket
from contextlib import ExitStack
from unittest.mock import patch


class Simulation:
    def __init__(self):
        self.commands = []
        self.attempts = []
        self._patches = ExitStack()

    def blocked(self, *args, **kwargs):
        self.attempts.append((args, kwargs))
        raise RuntimeError("Physical connections are disabled in the UI simulator")

    def install(self):
        import serial

        from carveracontroller import main
        from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils
        from carveracontroller.Controller import Controller
        from carveracontroller.USBStream import USBStream
        from carveracontroller.WIFIStream import MachineDetector, WIFIStream

        for owner, name in ((Controller, "open"), (USBStream, "open"), (USBStream, "_serial_for_address"),
                            (WIFIStream, "open"), (MachineDetector, "query_for_machines"),
                            (MachineDetector, "is_machine_busy"), (serial, "Serial")):
            self._patches.enter_context(patch.object(owner, name, self.blocked))
        self._patches.enter_context(patch.object(main.Makera, "setup_pendant", lambda root: None))
        self._patches.enter_context(patch.object(main.Makera, "attempt_reconnect", self.blocked))
        self._patches.enter_context(patch.object(main, "UrlRequest", self.blocked))
        self._patches.enter_context(patch.object(main.Utils, "comports", lambda *a, **k: []))
        self._patches.enter_context(patch.object(main.Utils, "list_identifiable_usb_serial_ports", lambda *a, **k: []))
        self._patches.enter_context(patch.object(ConfigUtils, "CONFIG_DIR", os.environ["KIVY_HOME"]))
        self._patches.enter_context(patch.object(socket, "create_connection", self.blocked))
        self._patches.enter_context(patch.object(socket.socket, "connect", self.blocked))
        self._patches.enter_context(patch.object(socket.socket, "sendto", self.blocked))
        self._patches.enter_context(patch.object(Controller, "executeCommand", self.record))
        self._patches.enter_context(patch.object(Controller, "executeFileCommand", self.record))
        self._patches.enter_context(patch.object(Controller, "executeRealtimeSequence", self.record))
        return self

    def record(self, *commands):
        self.commands.extend(commands)
        return True

    def configure(self):
        from kivy.config import Config

        for key, value in {"show_update": "0", "address": "", "pendant_type": "None",
                           "last_connection_method": "", "auto_reconnect_enabled": "0"}.items():
            Config.set("carvera", key, value)

    def close(self):
        from carveracontroller.addons.probing.operations.ConfigUtils import ConfigUtils

        ConfigUtils.flush_saves()
        ConfigUtils._writer.submit(lambda: None).result(timeout=5)
        self._patches.close()
