"""Exercise actual DXF entities at the CMM import boundary."""

import io

import ezdxf
import pytest

from carveracontroller.addons.cmm_workbench.core.gcode import build_m118_echo_tail
from carveracontroller.addons.cmm_workbench.core.io_export import export_dxf
from carveracontroller.addons.cmm_workbench.core.io_import import import_dxf
from carveracontroller.addons.cmm_workbench.core.session import CMMWorkbenchFeature, CMMWorkbenchSession, FeatureKind


def dxf_text(doc):
    stream = io.StringIO()
    doc.write(stream)
    return stream.getvalue()


@pytest.mark.parametrize("entity_type", ["TEXT", "MTEXT"])
@pytest.mark.parametrize("text", ["12.500°", "12.500° measured", "12.500 deg"])
def test_imports_degree_labels(entity_type, text):
    doc = ezdxf.new("R2010")
    attrs = {"layer": "PROBED_ANGLES", "insert": (1, 2, 3)}
    if entity_type == "TEXT":
        doc.modelspace().add_text(text, dxfattribs=attrs)
    else:
        doc.modelspace().add_mtext(text, dxfattribs=attrs)
    session, report = import_dxf(dxf_text(doc))
    assert report.skipped == 0
    assert len(session.features) == 1
    assert session.features[0].kind == FeatureKind.ANGLE
    assert session.features[0].payload["degrees"] == 12.5


def test_angle_survives_export_import():
    session = CMMWorkbenchSession()
    session.features.append(CMMWorkbenchFeature.new_angle("Angle", -12.5, x=1, y=2, z=3))
    imported, report = import_dxf(export_dxf(session))
    assert report.skipped == 0
    assert len(imported.features) == 1
    assert imported.features[0].payload["degrees"] == -12.5


@pytest.mark.parametrize("lightweight", [True, False])
def test_imports_both_polyline_entity_types(lightweight):
    doc = ezdxf.new("R2010")
    attrs = {"layer": "CONSTRUCTED_POLYLINES"}
    if lightweight:
        doc.modelspace().add_lwpolyline([(1, 2), (3, 4), (5, 6)], close=True, dxfattribs=attrs)
    else:
        doc.modelspace().add_polyline3d([(1, 2, 0), (3, 4, 0), (5, 6, 0)], close=True, dxfattribs=attrs)
    session, report = import_dxf(dxf_text(doc))
    assert report.skipped == 0
    (polyline,) = [f for f in session.features if f.kind == FeatureKind.POLYLINE]
    assert polyline.payload["closed"] is True


def test_unknown_echo_operation_and_empty_explicit_variables_are_rejected():
    with pytest.raises(ValueError, match="Unknown op"):
        build_m118_echo_tail("M999")
    with pytest.raises(ValueError, match="Empty result_vars"):
        build_m118_echo_tail("M466", ["", " "])
    assert "M118.1 P#154" in build_m118_echo_tail("M466", ["154"])
