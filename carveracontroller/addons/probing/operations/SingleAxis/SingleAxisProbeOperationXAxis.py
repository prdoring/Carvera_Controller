import copy

from carveracontroller.addons.probing.operations.OperationsBase import OperationsBase, ProbeSettingDefinition
from carveracontroller.addons.probing.operations.SingleAxis.SingleAxisProbeParameterDefinitions import (
    SingleAxisProbeParameterDefinitions,
)


class SingleAxisProbeOperationXAxis(OperationsBase):
    imagePath: str

    def __init__(self, title, x_is_negative_move, image_path, **kwargs):
        self.title = title
        self.imagePath = image_path
        self.x_is_negative_move = x_is_negative_move

    def generate(self, input_config: dict[str, str]):
        config = copy.deepcopy(input_config)

        # remove other axes for clarity
        config[SingleAxisProbeParameterDefinitions.YAxisDistance.code] = ""
        config[SingleAxisProbeParameterDefinitions.ZAxisDistance.code] = ""

        super().apply_direction(SingleAxisProbeParameterDefinitions.XAxisDistance.code, config, self.x_is_negative_move)

        return "M466" + self.config_to_gcode(config)

    def get_missing_config(self, config: dict[str, str]):
        definition = SingleAxisProbeParameterDefinitions.XAxisDistance
        if not config.get(definition.code, "").strip():
            return definition
        return None
