"""CMM file contracts and facing commands captured from the mobile baseline."""

import hashlib
import io
import json
from pathlib import Path

import pytest

from carveracontroller.addons.cmm_workbench.core.io_export import export_csv, export_dxf, export_json
from carveracontroller.addons.cmm_workbench.core.io_import import import_csv, import_dxf
from carveracontroller.addons.cmm_workbench.core.session import CMMWorkbenchFeature as Feature
from carveracontroller.addons.cmm_workbench.core.session import CMMWorkbenchSession as Session
from carveracontroller.addons.facing.facing_gcode import FacingParams, generate_facing_gcode


@pytest.fixture
def session():
    a = Feature.new_point("Fixture origin · 基准", -12.5, 8.25, -3)
    b = Feature.new_point('Second, "quoted" point', 15, 8.25, 2)
    c = Feature.new_point("Third point", 15, 20, 0)
    a.sketch_visible = False
    return Session(
        features=[
            a,
            b,
            c,
            Feature.new_circle("Bore", 2, 3, 4),
            Feature.new_ellipse("Pocket", 20, 30, 8, 4),
            Feature.new_corner("Corner", 50, 60),
            Feature.new_angle("Edge", 12.5, probe_variant="XAbove", x=7, y=9, z=0),
            Feature.new_segment("Segment", a.id, b.id),
            Feature.new_polyline("Open", [a.id, b.id, c.id]),
            Feature.new_polyline("Closed", [a.id, b.id, c.id], closed=True),
            Feature.new_derived_circle("Circumcircle", (a.id, b.id, c.id), 5, 6, 7),
            Feature.new_derived_point("Intersection", "one", "two", 3, 4),
        ]
    )


def test_json_round_trip_preserves_the_entire_cmm_session(session):
    assert Session.loads(export_json(session)).to_json_dict() == session.to_json_dict()


def test_csv_round_trip_keeps_labels_geometry_and_construction_references(session):
    restored, report = import_csv(export_csv(session))
    assert report.imported == len(session.features)
    assert report.skipped == 0
    assert [(f.id, f.kind, f.label, f.payload) for f in restored.features] == [
        (f.id, f.kind, f.label, f.payload) for f in session.features
    ]


def test_dxf_export_and_import_keep_measured_and_constructed_geometry(session):
    import ezdxf

    text = export_dxf(session)
    document = ezdxf.read(io.StringIO(text))
    entities = list(document.modelspace())
    circle = next(e for e in entities if e.dxftype() == "CIRCLE" and e.dxf.layer == "PROBED_CENTERS")
    assert tuple(circle.dxf.center) == (2, 3, 0)
    assert circle.dxf.radius == 4
    segment = next(e for e in entities if e.dxftype() == "LINE" and e.dxf.layer == "CONSTRUCTED_SEGMENTS")
    assert tuple(segment.dxf.start) == (-12.5, 8.25, 0)
    assert tuple(segment.dxf.end) == (15, 8.25, 0)
    polylines = [e for e in entities if e.dxftype() == "LWPOLYLINE"]
    assert len(polylines) == 2
    assert {bool(e.closed) for e in polylines} == {False, True}
    restored, report = import_dxf(text)
    assert restored.features
    assert report.imported > 0
    assert any(f.payload.get("r") == 4 for f in restored.features)


def test_corrupt_cmm_inputs_report_failure():
    with pytest.raises(ValueError):
        Session.loads("{broken")
    with pytest.raises(ValueError, match="required columns"):
        import_csv("x,y,z\n1,2,3\n")
    with pytest.raises(ValueError):
        import_dxf("not a drawing")


PROGRAMS = json.loads((Path(__file__).parents[1] / "resources/facing_programs.json").read_text())


@pytest.mark.parametrize(
    "case",
    PROGRAMS,
    ids=lambda c: "-".join(
        str(c["params"][key])
        for key in ("stock_origin_corner", "pattern", "milling_direction", "finish_enabled", "ext_port_enabled")
    ),
)
def test_all_facing_patterns_origins_and_optional_passes_keep_baseline_commands(case):
    program = generate_facing_gcode(FacingParams(**case["params"]))
    assert hashlib.sha256(program.encode()).hexdigest() == case["sha256"]
