from abc import abstractmethod


class OperationsBase:
    title: str = ""

    def __init__(self, value):
        self.title = value.title
        self.value = value

    @abstractmethod
    def generate(self, config: dict[str, str]) -> str:
        pass

    def config_to_gcode(self, config: dict[str, str]) -> str:
        return " " + " ".join([f"{key}{value}" for key, value in config.items() if value.strip() != ""])

    def validate_required(self, required_definitions, config: dict[str, str]):
        for name, definition in required_definitions.items():
            if not config.get(definition.code, "").strip():
                return definition
        return None

    def apply_direction(self, key, config: dict[str, str], is_opposite: bool):
        if not is_opposite or key not in config:
            return

        raw = config[key]
        if raw is None or not str(raw).strip():
            return

        try:
            config[key] = str(float(raw) * -1)
        except (TypeError, ValueError):
            # Leave non-numeric values untouched; callers may still surface them via validation.
            return

    @abstractmethod
    def get_missing_config(self, config: dict[str, str]):
        pass


class ProbeSettingDefinition:
    code: str
    description: str
    is_required: bool

    def __init__(
        self, g_code_param: str, label: str, is_required: bool = False, description: str = "", default_val: str = ""
    ):
        self.label = label
        self.code = g_code_param
        self.description = description
        self.is_required = is_required
        self.default = default_val
