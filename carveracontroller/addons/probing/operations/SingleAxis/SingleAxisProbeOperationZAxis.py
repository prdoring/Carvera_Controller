import copy

from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import (
    SingleAxisProbeParameterDefinitions,
)


class SingleAxisProbeOperationZAxis(OperationsBase):
    imagePath: str

    def __init__(self, title, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path

    def generate(self, input_config: dict[str, str]):
        config = copy.deepcopy(input_config)

        # remove other axes for clarity
        config[SingleAxisProbeParameterDefinitions.XAxisDistance.code] = ""
        config[SingleAxisProbeParameterDefinitions.YAxisDistance.code] = ""

        super().apply_direction(SingleAxisProbeParameterDefinitions.ZAxisDistance.code, config, True)

        return "M466" + self.config_to_gcode(config)

    def get_missing_config(self, config: dict[str, str]):
        print(config)
        definition = SingleAxisProbeParameterDefinitions.ZAxisDistance
        if not config.get(definition.code, "").strip():
            return definition
        return None
