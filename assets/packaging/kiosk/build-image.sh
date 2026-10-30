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
cp /project/kiosk/README.md /export/README.md
python3 /project/kiosk/package_release.py "$version" /export /project/kiosk/kiosk.py /usr/share/novnc
