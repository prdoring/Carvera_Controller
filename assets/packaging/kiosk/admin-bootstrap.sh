#!/bin/sh
set -eu
cd /boot/firmware/kiosk-admin-bootstrap
sha256sum --check payload.sha256
exec /usr/bin/python3 -E -s ./admin_bootstrap.py ./request.json
