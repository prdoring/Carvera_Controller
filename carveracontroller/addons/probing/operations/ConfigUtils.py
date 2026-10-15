from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from kivy.clock import Clock

logger = logging.getLogger(__name__)


class ConfigUtils:
    CONFIG_DIR = os.path.expanduser("~/.kivy/")
    _pending = {}
    _writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="probe-settings")

    @staticmethod
    def schedule_save(config, filename):
        previous = ConfigUtils._pending.pop(filename, None)
        if previous is not None:
            previous[1].cancel()
        snapshot = dict(config)
        event = Clock.schedule_once(lambda _dt: ConfigUtils._submit_save(filename), 0.3)
        ConfigUtils._pending[filename] = (snapshot, event)

    @staticmethod
    def _submit_save(filename):
        pending = ConfigUtils._pending.pop(filename, None)
        if pending is not None:
            pending[1].cancel()
            ConfigUtils._writer.submit(ConfigUtils.save_config, pending[0], filename)

    @staticmethod
    def flush_saves():
        for filename in list(ConfigUtils._pending):
            ConfigUtils._submit_save(filename)

    @staticmethod
    def save_config(config: dict, filename: str):
        try:
            os.makedirs(ConfigUtils.CONFIG_DIR, exist_ok=True)  # Ensure directory exists
            file_path = os.path.join(ConfigUtils.CONFIG_DIR, filename)
            with open(file_path, "w") as f:
                json.dump(config, f, indent=4)
            logger.info(f"Configuration saved to {file_path}")
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")

    @staticmethod
    def load_config(filename: str) -> dict:
        file_path = os.path.join(ConfigUtils.CONFIG_DIR, filename)
        if os.path.exists(file_path):
            try:
                with open(file_path) as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading configuration: {e}")
        return {}  # Return an empty dictionary if loading fails or file doesn't exist


def _format_hint_value(val) -> str:
    try:
        f = float(val)
        if f == int(f):
            return str(int(f))
        return "%g" % f
    except (ValueError, TypeError):
        return str(val).strip()


def _get_setting_list() -> dict:
    from kivy.app import App

    return App.get_running_app().root.setting_list


def get_machine_config_hint(config_key: str) -> str | None:
    try:
        val = _get_setting_list().get(config_key)
        if val is not None and str(val).strip():
            return _format_hint_value(val)
    except Exception:
        pass
    return None
