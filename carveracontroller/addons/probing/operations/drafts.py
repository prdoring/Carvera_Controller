"""Keep incomplete probe edits out of saved settings."""

from carveracontroller.ui.editing import is_complete_number


class ProbeSettingsDraft:
    parameter_definitions = None

    def __init__(self, **kwargs):
        self._draft_values = {}
        super().__init__(**kwargs)

    def draft_changed(self, key, value):
        self._draft_values[key] = value

    def commit_draft(self, key):
        if key not in self._draft_values:
            return True
        value = self._draft_values[key]
        if not is_complete_number(value, allow_empty=True):
            return False
        self.setting_changed(key, value)
        del self._draft_values[key]
        return True

    def draft_config(self):
        for key in list(self._draft_values):
            self.commit_draft(key)
        result = {key: str(value) for key, value in self.config.items()}
        for key, value in self._draft_values.items():
            result[getattr(self.parameter_definitions, key).code] = value
        return result
