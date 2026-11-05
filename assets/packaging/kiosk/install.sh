#!/bin/bash
set -euo pipefail
target=$1
source=/project/kiosk
payload=$source/payload
version=$(python3 -c 'import json; print(json.load(open("/project/kiosk/payload/bundle.json"))["version"])')
for group in carvera video render input dialout; do
    chroot "$target" groupadd -f "$group"
done
chroot "$target" useradd --system --create-home --home-dir /var/lib/carvera --gid carvera \
    --groups video,render,input,dialout --shell /usr/sbin/nologin carvera
chroot "$target" usermod --password '*' --groups adm,systemd-journal --shell /bin/bash carvera-admin
chroot "$target" useradd --create-home --shell /bin/bash --password '*' kiosk-admin
install -d -m 0700 "$target/var/lib/carvera-system"
chroot "$target" python3 -c 'import json,pwd; from pathlib import Path; a=pwd.getpwnam("kiosk-admin"); Path("/var/lib/carvera-system/image-account.json").write_text(json.dumps({"uid":a.pw_uid,"home":a.pw_dir}))'
rm -f "$target/etc/sudoers.d/010_rpi-passwd" "$target/etc/sudoers.d/010_rpi-nopasswd"
install -d "$target"/{opt/carvera/maintenance,opt/carvera/releases,etc/carvera,var/lib/carvera/gcodes}
install -d -m 0755 "$target/var/lib/carvera-maint"
install -d -m 0700 "$target/var/lib/carvera-maint/uploads" "$target/var/lib/carvera-maint/exports"
chroot "$target" chown carvera-admin:carvera-admin /var/lib/carvera-maint/uploads /var/lib/carvera-maint/exports
mkdir -p "$target/opt/carvera/system-releases/$version"
tar -xzf "$payload/carvera-kiosk-system-$version.tar.gz" -C "$target/opt/carvera/system-releases/$version"
rmdir "$target/opt/carvera/maintenance"
ln -s "system-releases/$version" "$target/opt/carvera/system-current"
ln -s "system-current/runtime" "$target/opt/carvera/maintenance"
ln -s "system-current/system-ui" "$target/opt/carvera/system-ui"
install -d "$target/opt/carvera/releases/$version/wheels"
cp -a "$payload/wheels/." "$target/opt/carvera/releases/$version/wheels/"
cp "$payload/bundle.json" "$target/opt/carvera/releases/$version/"
chroot "$target" python3 -m venv "/opt/carvera/releases/$version/venv"
chroot "$target" "/opt/carvera/releases/$version/venv/bin/python" -m pip install \
    --no-index --find-links "/opt/carvera/releases/$version/wheels" "carvera-controller-community==$version"
chroot "$target" python3 -m venv "/opt/carvera/system-releases/$version/venv"
ln -s "system-current/venv" "$target/opt/carvera/recovery-venv"
chroot "$target" /opt/carvera/recovery-venv/bin/python -m pip install \
    --no-index --find-links "/opt/carvera/releases/$version/wheels" Kivy==2.3.1
python3 "$source/runtime/kiosk_touch.py" "$target/var/lib/carvera/recovery"
ln -s "releases/$version" "$target/opt/carvera/current"
rsync -a --chown=0:0 --chmod=D755,F644 "$source/overlay/" "$target/"
mkdir -p "$target/opt/carvera/updater-releases/bootstrap-1"
cp "$source/runtime/system_update.py" "$source/runtime/admin_accounts.py" "$source/runtime/kiosk_state.py" "$target/opt/carvera/updater-releases/bootstrap-1/"
cp "$payload/updater-bundle.json" "$target/opt/carvera/updater-releases/bootstrap-1/"
ln -s "updater-releases/bootstrap-1" "$target/opt/carvera/updater"
chmod 0755 "$target/opt/carvera/maintenance/"*.sh "$target/usr/local/sbin/carvera-maint" "$target/usr/local/sbin/carvera-recover" "$target/usr/local/sbin/carvera-system-update"
chmod 0755 "$target/etc/carvera/labwc/autostart"
chmod 0440 "$target/etc/sudoers.d/carvera" "$target/etc/sudoers.d/kiosk-admin"
chroot "$target" visudo -cf /etc/sudoers.d/carvera
chroot "$target" chmod -R go-w /opt/carvera
printf 'performance\n' > "$target/etc/carvera/cpu-governor"
printf '1920x1200\n' > "$target/etc/carvera/display-mode"
chroot "$target" chown -R carvera:carvera /var/lib/carvera
chroot "$target" systemctl enable carvera-provision.service carvera-cpu.service carvera-kiosk.service ssh.service NetworkManager.service avahi-daemon.service seatd.service
chroot "$target" systemctl mask getty@tty1.service
chroot "$target" systemctl mask apt-daily.timer apt-daily-upgrade.timer
chroot "$target" systemctl mask rpi-eeprom-update.service
chroot "$target" systemctl mask ModemManager.service systemd-networkd.service
chroot "$target" systemctl mask wayvnc.service
chroot "$target" systemctl enable getty@tty2.service carvera-system-recover.service
chroot "$target" dpkg-query -W > "$target/etc/carvera/packages.txt"
mkdir -p "$target/boot/firmware"
python3 - "$target/boot/firmware/carvera-image.json" "$version" <<'PY'
import json, sys
from pathlib import Path
Path(sys.argv[1]).write_text(json.dumps({"format": "carvera-kiosk-pi4-v2", "version": sys.argv[2], "provisioning_format": 2}))
PY
rm -f "$target"/etc/ssh/ssh_host_*
python3 "$source/verify_rootfs.py" "$target"
