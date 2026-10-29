#!/bin/sh
set -eu
release=$(readlink -f /opt/carvera/current)
exec "$release/venv/bin/python" -m carveracontroller
