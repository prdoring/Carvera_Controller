# Pi Kiosk @VERSION@: laptop setup and administration

For a new card, use the separate **Carvera Kiosk Setup** graphical download from
the matching full release. It flashes, configures and verifies first boot without
installing Python or OpenSSH. The separate **Carvera Kiosk Screen Share** app
opens its verified profile and maintenance key. Windows 11 x64 and Debian
12+/Ubuntu 24.04+ x64/ARM64 are the initial desktop targets. Windows packages are
unsigned prereleases. If no release includes `setup-release.json`, graphical
installation assets have not been published yet.

This ZIP contains the advanced command-line tools for maintenance and migration.
Keep these routes separate from graphical Configure, which accepts fresh v3
cards and matching prepared transactions only.

Use all artifacts from the same trusted build/release:

- `carvera-kiosk-pi4-@VERSION@.img.xz`: fresh SD image (format v3).
- `carvera-kiosk-app-@VERSION@.tar.gz`: controller update.
- `carvera-kiosk-system-@VERSION@.tar.gz`: independent System/recovery update.
- `carvera-kiosk-updater-@VERSION@.tar.gz`: full-admin-only updater upgrade.
- `carvera-kiosk-laptop-@VERSION@.zip`: this complete folder.
- `setup-release.json`: image identities, compatibility and companion downloads.
- `SHA256SUMS`: hashes covering the complete published inventory, including desktop packages.

Obtain published builds from this fork's [releases](https://github.com/prdoring/Carvera_Controller/releases).
Until a compatible full release is published, build current source. The
legacy `kiosk-v1.0.0` release does not provide this setup; its existing cards use
the migration procedure below. Verify every artifact you use with `SHA256SUMS`:
on Windows run `Get-FileHash FILENAME -Algorithm SHA256`; on Linux run
`sha256sum -c SHA256SUMS` beside the complete set, or compare the selected file's line.

Keep this complete extracted folder together, including `kiosk.py`,
`kiosk_admin.py`, `bootstrap/`, `ADMINISTRATION.md`, requirements and `novnc/`.
Install Python 3.11+ and OpenSSH client tools. Open a terminal here. Git and
Docker are not needed for downloaded setup/migration packages.

Read [ADMINISTRATION.md](ADMINISTRATION.md) for the full instructions and expected
checkpoints: dedicated key creation, owner-entered passphrases, Windows SSH agent,
fresh setup, existing-card migration, two independent USBImager reads, offline
undo, console fallback, System updates/rollback, updater repair, tunneled screen
access, key rotation and whole-card disaster restoration.

For advanced manual preparation of a fresh image, after creating/loading the keys and flashing in Imager with
OS customization skipped, use the actual boot drive and network:

```powershell
python kiosk.py prepare-card --boot-dir E:/ --public-key ~/.ssh/id_ed25519.pub --admin-public-key ~/.ssh/id_ed25519_carvera_kiosk_admin.pub --hostname carvera-pi --ssid Workshop --country US
```

For Ethernet omit `--ssid` and `--country`. Protect the temporary Wi-Fi setup
file. Verify first-time SSH fingerprints through a trusted source. The controller
starts disconnected; opening its USB connection resets the mill.
Old v2 images retain their original preparation path. Completed or applying v3
cards cannot accept replacement offline configuration. Preserve the same request,
keys and preferences on a prepared retry; after completion use authenticated
System settings. The GUI saves that transaction automatically.

The matching CLI viewer requires screen lease protocol 1 and an explicit
maintenance identity:

```powershell
python -m pip install -r laptop-requirements.txt
python kiosk.py screen --host carvera-admin@carvera-pi.local --identity ~/.ssh/id_ed25519
```

Trust the host in OpenSSH first by comparing its fingerprint through the
touchscreen. For an address already trusted under a hostname, add the same
`--host-key-alias` used by SSH/SCP. Press Ctrl+C to disconnect. The CLI uses
retained port-zero sockets and the same 20-second renewal/90-second expiry as the
graphical viewer. It rejects older screen servers before starting a session.

Routine inspection and backups keep the existing restricted account:

```powershell
python kiosk.py diagnose --host carvera-admin@carvera-pi.local
python kiosk.py backup --host carvera-admin@carvera-pi.local preferences.tar.gz
```

Whole-kiosk tasks use the separate `kiosk-admin` key and intentional full sudo.
Authorize a bounded administration task; mill operations need separate approval.
Do not proceed to a real card until automated gates and operator backup checkpoints
are satisfied. Physical migration validation is not implied by a build.
