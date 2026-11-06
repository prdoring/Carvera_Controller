#!/bin/sh
set -eu
install -d -m 0755 -o root -g root /run/carvera-maint
attempt=0
while [ ! -S /run/carvera/wayland-0 ]; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 50 ] || exit 1
    sleep 0.2
done
if ! /usr/bin/python3 -E -s /opt/carvera/maintenance/setup_gate.py --check; then
    /usr/bin/python3 -E -s /opt/carvera/maintenance/setup_gate.py || true
    systemctl --no-block start carvera-setup.service
    exit 0
fi
systemctl --no-block stop carvera-setup.service
if [ -e /run/carvera-maint/session.started ]; then
    systemctl --no-block restart carvera-recovery.service
else
    touch /run/carvera-maint/session.started
    systemctl --no-block start carvera-controller.service
fi
