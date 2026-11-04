# Pi Kiosk @VERSION@: laptop setup and administration

Use all artifacts from the same trusted build/release:

- `carvera-kiosk-pi4-@VERSION@.img.xz`: fresh SD image (format v2).
- `carvera-kiosk-app-@VERSION@.tar.gz`: controller update.
- `carvera-kiosk-system-@VERSION@.tar.gz`: independent System/recovery update.
- `carvera-kiosk-updater-@VERSION@.tar.gz`: full-admin-only updater upgrade.
- `carvera-kiosk-laptop-@VERSION@.zip`: this complete folder.
- `SHA256SUMS`: hashes covering all five artifacts.

Obtain published builds from this fork's [releases](https://github.com/prdoring/Carvera_Controller/releases).
Until an administrator-enabled release is published, build current source. The
legacy `kiosk-v1.0.0` release does not provide this setup; its existing cards use
the migration procedure below. Verify every artifact you use with `SHA256SUMS`:
on Windows run `Get-FileHash FILENAME -Algorithm SHA256`; on Linux run
`sha256sum -c SHA256SUMS` beside all five downloads.

Keep this complete extracted folder together, including `kiosk.py`,
`kiosk_admin.py`, `bootstrap/`, `ADMINISTRATION.md`, requirements and `novnc/`.
Install Python 3.11+ and OpenSSH client tools. Open a terminal here. Git and
Docker are not needed for downloaded setup/migration packages.

Read [ADMINISTRATION.md](ADMINISTRATION.md) for the full instructions and expected
checkpoints: dedicated key creation, owner-entered passphrases, Windows SSH agent,
fresh setup, existing-card migration, two independent USBImager reads, offline
undo, console fallback, System updates/rollback, updater repair, tunneled screen
access, key rotation and whole-card disaster restoration.

For a fresh image, after creating/loading the keys and flashing in Imager with
OS customization skipped, use the actual boot drive and network:

```powershell
python kiosk.py prepare-card --boot-dir E:/ --public-key ~/.ssh/id_ed25519.pub --admin-public-key ~/.ssh/id_ed25519_carvera_kiosk_admin.pub --hostname carvera-pi --ssid Workshop --country US
```

For Ethernet omit `--ssid` and `--country`. Protect the temporary Wi-Fi setup
file. Verify first-time SSH fingerprints through a trusted source. The controller
starts disconnected; opening its USB connection resets the mill.

Routine inspection and backups keep the existing restricted account:

```powershell
python kiosk.py diagnose --host carvera-admin@carvera-pi.local
python kiosk.py backup --host carvera-admin@carvera-pi.local preferences.tar.gz
```

Whole-kiosk tasks use the separate `kiosk-admin` key and intentional full sudo.
Authorize a bounded administration task; mill operations need separate approval.
Do not proceed to a real card until automated gates and operator backup checkpoints
are satisfied. Physical migration validation is not implied by a build.
