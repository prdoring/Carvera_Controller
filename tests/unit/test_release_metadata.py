import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


def build_function(name):
    """Exercise build metadata without importing platform-specific packaging tools."""
    path = Path(__file__).resolve().parents[2] / "scripts/build.py"
    source = ast.parse(path.read_text())
    nodes = [
        node
        for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        in (
            "convert_version_to_4part",
            "codegen_version_string",
            "version_type",
        )
    ]
    import argparse
    import logging
    import re

    toml = SimpleNamespace(
        load=lambda path: {"tool": {"poetry": {"version": "0.0.0"}}},
        dump=lambda data, stream: stream.write(
            '[tool.poetry]\nversion = "' + data["tool"]["poetry"]["version"] + '"\n'
        ),
    )
    namespace = {"re": re, "logger": logging.getLogger(__name__), "toml": toml, "argparse": argparse}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("version", ["1.0.0.dev5", "1.0.0rc1", "1.0.0", "2.2.0-RC1", "2.2.0-DEV"])
def test_android_keeps_release_identity_separate_from_numeric_package_version(tmp_path, version):
    project = tmp_path / "carveracontroller"
    project.mkdir()
    (tmp_path / "pyproject.toml").write_text('[tool.poetry]\nversion = "0.0.0"\n')
    build_function("codegen_version_string")(version, project, tmp_path, "android")
    namespace = {}
    exec((project / "__version__.py").read_text(), namespace)
    assert namespace["__release_version__"] == version
    assert all(part.isdigit() for part in namespace["__version__"].split("."))
    assert len(namespace["__version__"].split(".")) == 4


@pytest.mark.parametrize("version", ["1.0.0.dev5", "1.0.0rc1", "1.0.0"])
def test_canonical_release_versions_are_accepted_by_desktop_builder(version):
    assert build_function("version_type")("v" + version) == version
