#!/bin/bash
set -euo pipefail
mkdir -p /work /cache /export
exec 9>/work/build.lock
flock -n 9 || { echo 'Another kiosk image build is using this work volume' >&2; exit 1; }
version=$(python3 -c 'import json; print(json.load(open("/project/kiosk/payload/bundle.json"))["version"])')
/opt/image-gen/rpi-image-gen build \
    -S /project/kiosk -c /project/kiosk/config/pi4.yaml -- \
    IGconf_sys_workroot=/work IGconf_sys_cachedir=/cache IGconf_artefact_version="$version"
image=/work/image-carvera-kiosk-pi4/carvera-kiosk-pi4.img
test -f "$image"
xz -T2 -c "$image" > "/export/carvera-kiosk-pi4-$version.img.xz"
cp /project/kiosk/payload/carvera-kiosk-app-*.tar.gz /project/kiosk/payload/bundle.json /export/
mkdir -p /export/laptop/novnc
cp -aL /usr/share/novnc/. /export/laptop/novnc/
cp /project/kiosk/laptop-requirements.txt /export/laptop/
cp /project/kiosk/kiosk.py /export/laptop/
cd /export
sha256sum *.xz *.tar.gz > SHA256SUMS
