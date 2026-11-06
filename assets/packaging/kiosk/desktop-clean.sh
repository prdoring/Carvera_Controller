#!/bin/sh
set -eu
for executable in python python3 git ssh docker; do
    if command -v "$executable" >/dev/null; then
        echo 'The clean runtime contains an unexpected development tool' >&2
        exit 1
    fi
done
stage=$(mktemp -d /tmp/'kiosk portable 工作室.XXXXXX')
trap 'rm -rf "$stage"' EXIT
for archive in /packages/packages/*.tar.gz; do
    tar -xzf "$archive" -C "$stage"
done
for app in CarveraKioskSetup CarveraKioskScreenShare; do
    xvfb-run -a -s '-screen 0 1280x1000x24 -nolisten tcp' "$stage/$app/$app" --self-check "$stage/$app-portable.json"
done
dpkg -i /packages/packages/*.deb
for app in setup screen-share; do
    xvfb-run -a -s '-screen 0 1280x1000x24 -nolisten tcp' "carvera-kiosk-$app" --self-check "$stage/$app-installed.json"
done
echo 'PASS: installed and portable tools ran without Python, Git, Docker or OpenSSH'
