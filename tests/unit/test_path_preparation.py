import math

import pytest

from carveracontroller.GcodeViewer import (
    COLOR_SCHEME_BY_SPEED,
    COLOR_SCHEME_BY_TOOL,
    COLOR_SCHEME_BY_TYPE,
    COLOR_SCHEME_BY_Z,
    MESH_LINE_CHUNK,
    VERTEX_FLOAT_NUM,
    GCodeViewer,
    MeshManager,
)


def test_prepared_path_preserves_rapid_feed_bridges_and_rotary_positions():
    path = [
        [0, 0, 0, 0, 0, 1, 1, 1000],
        [10, 0, 0, 0, 1, 2, 1, 300],
        [10, 10, 0, 90, 1, 3, 2, 400],
        [0, 10, 5, 90, 0, 4, 2, 1000],
    ]
    prepared = MeshManager()
    prepared.add_path_data(path)
    assert prepared.raw_linenumbers == [1, 2, 2, 3, 4, 4]
    assert prepared.raw_tools == [1, 1, 1, 2, 2, 2]
    assert prepared.vertex_types == [2, 2, 1, 1, 1, 2]
    assert prepared.raw_positions == [0, 0, 0, 10, 0, 0, 10, 0, 0, 10, 10, 0, 0, 10, 5, 0, 10, 5]
    assert prepared.positions[9:12] == pytest.approx([10, 0, 10], abs=1e-5)
    assert prepared.positions[-3:] == pytest.approx([0, -5, 10], abs=1e-5)
    assert prepared.lengths[-1] / prepared.position_scale == pytest.approx(20 + math.sqrt(125))
    assert len(prepared.vertices) == 6 * VERTEX_FLOAT_NUM
    assert prepared.meshes[0][1] == list(range(6))
    assert prepared.feed_range[1] >= prepared.feed_range[0] > 0


def test_path_batches_match_existing_batch_boundary_behavior():
    first = [[0, 0, 0, 0, 0, 1, 1], [1, 0, 0, 0, 1, 2, 1]]
    second = [[2, 0, 0, 0, 0, 3, 1], [3, 0, 0, 0, 1, 4, 1]]
    prepared = MeshManager()
    prepared.add_path_data(first, False)
    assert not prepared.meshes
    prepared.add_path_data(second, True)
    assert prepared.raw_linenumbers == [1, 2, 2, 3, 4, 4]
    assert prepared.lengths[-1] / prepared.position_scale == pytest.approx(3)


def test_large_path_chunks_share_endpoint_and_empty_file_has_no_mesh():
    prepared = MeshManager()
    prepared.add_path_data([[i, 0, 0, 0, 1, i, 1] for i in range(MESH_LINE_CHUNK + 2)])
    first, second = prepared.meshes
    assert first[0][-VERTEX_FLOAT_NUM:] == second[0][:VERTEX_FLOAT_NUM]
    assert max(first[1]) < 65536
    assert len(second[1]) == 3
    empty = MeshManager()
    empty.add_path_data([])
    assert empty.meshes == []
    assert empty.lengths == []


def test_background_legend_totals_preserve_feed_and_rapid_durations():
    totals = GCodeViewer._legend_durations_for_path(
        [0, 2, 5], [300, 300, 0], [1, 1, 2], [0, 0, 0, 1, 0, 2, 2, 0, 4], 300, 600, 0, 4
    )
    assert totals[COLOR_SCHEME_BY_TYPE] == {("feed", "feed"): 2, ("rapid", "rapid"): 3}
    assert totals[COLOR_SCHEME_BY_TOOL] == {("tool", 1): 2, ("tool", 2): 3}
    assert sum(totals[COLOR_SCHEME_BY_SPEED].values()) == 5
    assert sum(totals[COLOR_SCHEME_BY_Z].values()) == 2
