# Kiosk administration and recovery

The administrator-enabled image format is `carvera-kiosk-pi4-v2`. Use the image
and laptop tools from the same build. Published `kiosk-v1.0.0` assets use the old
format and restricted login; downloading that release does not add these features.
Build from source until an administrator-enabled release is published. A full
build exports image, app, system, updater and laptop artifacts with `SHA256SUMS`.
Verify every artifact you use against that file. An individual system/app build
also exports a checksum beside its bundle. Checksums detect corruption; obtain
packages from your own trusted build or a verified release download.

## Accounts and keys

| Account | Purpose | Access |
| --- | --- | --- |
| `carvera` | Touchscreen applications | Restricted local recovery helper |
| `carvera-admin` | Routine controller maintenance | Fixed maintenance commands |
| `kiosk-admin` | Whole kiosk administration | Full passwordless sudo |

Keep the existing maintenance key. Create the additional key on your laptop:

```powershell
ssh-keygen -t ed25519 -f "$HOME/.ssh/id_ed25519_carvera_kiosk_admin" -C carvera-kiosk-admin
```

Enter your own passphrase when prompted. Never put the private key on the card,
Pi, in a package or in a chat. In an elevated Windows PowerShell window, enable
the SSH agent once with `Set-Service ssh-agent -StartupType Automatic` and
`Start-Service ssh-agent`. Then, in your ordinary terminal, load the key:

```powershell
ssh-add "$HOME/.ssh/id_ed25519_carvera_kiosk_admin"
```

The owner enters the passphrase. Helpers run in batch mode and use the agent.
Use `--identity ~/.ssh/id_ed25519_carvera_kiosk_admin` with administrator commands.
If an IP address is already trusted under a hostname, consistently add
`--host-key-alias carvera-pi.local` to helper commands. For manual SSH use
`-o HostKeyAlias=carvera-pi.local`. Never disable host-key checking. Compare the
first host fingerprint with the touchscreen or another trusted record.

Full sudo deliberately gives root capability, including accounts, services and
operating-system settings. It is not a restriction to the kiosk updater. A
dedicated key does not isolate AI chats sharing the same laptop or SSH agent.
Authorize a bounded administration task for the identified Pi. Mill connections,
motion, probing, spindle operation, tool changes and firmware need separate
authorization. Keep the operator present for machine operations.

## Fresh image

Flash the matching image using Raspberry Pi Imager's custom-image option; skip
its customization. On the mounted boot volume run:

```powershell
python kiosk.py prepare-card --boot-dir E:/ --public-key ~/.ssh/id_ed25519.pub --admin-public-key ~/.ssh/id_ed25519_carvera_kiosk_admin.pub --hostname carvera-pi --ssid Workshop --country US
```

Use the actual drive and network. Omit `--ssid` and `--country` for Ethernet.
Repeat `--admin-public-key` to authorize additional owners (maximum 16). Only
single public-key records are accepted, without authorized_keys options. The
temporary provisioning file contains the Wi-Fi password. Protect it until the
Pi removes it after successful setup. New setup tools reject old image formats;
old setup tools reject the distinct v2 format. Initial setup cannot finish
without the administrator key.

On first boot, verify both logins using their respective keys. The controller
starts disconnected. Setup completion is root-owned outside app data and boot
files. Completed packages cannot be used to add keys again or reset passwords.

## Migrate an existing card

This workflow preserves the card, controller release, settings, host keys and
existing maintenance login. It does not repartition or flash the card. The
first physical validation is on the current card after verified backup; a spare
card rehearsal is not required. Keep the mill physically disconnected throughout
migration and recovery validation.

Commands below run in the extracted laptop folder. From source use
`python scripts/kiosk.py` instead of `python kiosk.py`. Keep the entire laptop
folder together, including `kiosk_admin.py` and `bootstrap/`. Python 3.11+, OpenSSH
client tools and enough laptop disk space for two whole-card images are required;
Git and Docker are not required for downloaded packages.

1. While the old Pi is online, prepare a target-specific package using the
   existing restricted login and key:

   ```powershell
   python kiosk.py admin-migration prepare --host carvera-admin@carvera-pi.local --identity ~/.ssh/id_ed25519 --admin-public-key ~/.ssh/id_ed25519_carvera_kiosk_admin.pub --output "C:/Kiosk Backup/admin migration"
   ```

   Save the returned target report: SSH fingerprint, image/controller versions,
   card capacity, boot UUID and partition identifiers. The package also retains
   the byte-exact original boot command line. Keep this local copy for undo.

2. Confirm with the operator that the mill is idle and safe to interrupt. Shut
   down normally through the kiosk's shutdown control or an already authorized
   full administrator. Confirm that this route exists before beginning: some
   legacy kiosks expose only reboot and restricted SSH. If no orderly shutdown
   route is available, stop for an operator-specific shutdown procedure; do not
   describe unplugging a running Pi as a normal shutdown.
   Wait for shutdown, disconnect power, and remove the card.

3. On Windows, download the full Windows USBImager build from the
   [official USBImager documentation](https://gitlab.com/bztsrc/usbimager/-/raw/master/README.md).
   Choose the normal read/write build, not the `wo` write-only variant. Run it
   as administrator if needed. Identify the physical card by capacity and device,
   and leave **Compress** unchecked. Select the card and click **Read**. Retain
   its resulting `.dd` file. Move/rename it to `card-first.dd` before reading again
   so a timestamp-based output name cannot overwrite it. Click **Read** again and
   move/rename that result to `card-second.dd` to obtain a second independent
   uncompressed whole-device read; do not copy the first file. The Verify option
   verifies writes and does not verify a read backup.

   ```powershell
   Get-Item "C:/Kiosk Backup/card-first.dd", "C:/Kiosk Backup/card-second.dd" | Select-Object Name,Length
   Get-FileHash "C:/Kiosk Backup/card-first.dd", "C:/Kiosk Backup/card-second.dd" -Algorithm SHA256
   ```

   Both lengths must equal the recorded physical capacity and both hashes must
   match. Retain the first image, its hash and target report. The staging helper
   repeats these checks and compares the backup's MBR partition identifiers and
   FAT volume identity with the captured Pi. It cannot establish that the owner
   actually performed two separate reads. The supported image uses an MBR card
   layout; an unexpected/custom layout stops for review.

4. Find the mounted boot partition, checking its physical disk/capacity against
   the report. A `bootfs` label alone does not identify a card. If Windows offers
   to format the Linux partition, cancel. Stage only on the identified boot drive:

   ```powershell
   python kiosk.py admin-migration stage --boot-dir E:/ --package "C:/Kiosk Backup/admin migration" --backup "C:/Kiosk Backup/card-first.dd" --verification-backup "C:/Kiosk Backup/card-second.dd"
   ```

   Expect a `staged` request ID, disk report and matching backup hash. This adds
   the bootstrap directory and dedicated boot arguments while retaining every
   existing boot argument. Changed boot files or a mismatching card stop staging.

5. Safely eject, reinstall and power the Pi with the mill disconnected. The
   dedicated systemd 257 migration boot runs before the normal kiosk session;
   the [systemd.run generator](https://www.freedesktop.org/software/systemd/man/257/systemd-run-generator.html)
   executes the payload with explicit reboot-on-success and poweroff-on-failure.
   The bootstrap verifies its payload, card and SSH identity before account
   changes. Success restores normal boot arguments and reboots normally.
   `kiosk-admin-migration-result.json` on the boot partition reports the outcome.
   A handled account/setup failure restores access policy and normal boot
   arguments, records the error and powers off. A failure before bootstrap
   execution or damaged media requires offline undo or whole-card restoration.

6. Verify the unchanged SSH host fingerprint and both logins. Test full access:

   ```powershell
   ssh -i ~/.ssh/id_ed25519_carvera_kiosk_admin -o StrictHostKeyChecking=yes kiosk-admin@carvera-pi.local sudo -n id -u
   python kiosk.py system-status --host kiosk-admin@carvera-pi.local --identity ~/.ssh/id_ed25519_carvera_kiosk_admin
   ```

   The first command must return `0`. Initially system status has no versioned
   System release; the old controller is still installed. Do not deploy the app
   as part of the administrator bootstrap.

7. Set and test the local fallback below, then bridge the first System update.
   The old maintenance helper accepts only `carvera-admin`; enter maintenance
   through a genuine connection using its preserved key:

   ```powershell
   python kiosk.py maintenance --host carvera-admin@carvera-pi.local --identity ~/.ssh/id_ed25519 enter --confirm-machine-idle
   python kiosk.py system-update --host kiosk-admin@carvera-pi.local --identity ~/.ssh/id_ed25519_carvera_kiosk_admin carvera-kiosk-system-VERSION.tar.gz --inspect
   python kiosk.py system-update --host kiosk-admin@carvera-pi.local --identity ~/.ssh/id_ed25519_carvera_kiosk_admin carvera-kiosk-system-VERSION.tar.gz
   ```

   Confirm idle before using the flag. Review compatibility, required/free bytes
   and interruption information from inspection. The updater uses the genuine
   existing maintenance lease; never spoof `SUDO_USER` or fabricate an ack.
   After successful activation both remote accounts can use maintenance. If
   rollback selects the legacy helper, use `carvera-admin` again. Full admin SSH
   remains available independently of that rollback.

## Local keyboard fallback

After administrator SSH works, the owner runs `sudo passwd kiosk-admin` in a
private interactive SSH terminal and enters a console password. SSH password
login and root SSH remain disabled. Connect a keyboard to the Pi, press
Ctrl+Alt+F2, log in as `kiosk-admin`, and run `sudo -n id -u`. Press Ctrl+Alt+F1
to return to the running kiosk without restarting it. Physically test this
before relying on it for recovery. Console access can repair services and
network configuration even when SSH is unavailable; it cannot repair dead media.

## System updates and rollback

Image, controller, System and updater versions are independent. `system-status`
reports each. Controller bundles use `bundle.json`; System bundles use
`system-bundle.json` and a separate upload route. App deployment and preferences
restore reject System/updater bundles. Both remote accounts retain caller-owned
transfer directories; the full account uses `/home/kiosk-admin/transfers/`.

System releases contain helpers, the independent System/recovery application,
its environment/assets and managed kiosk services. Releases are root-owned under
`/opt/carvera/system-releases/`, selected by `system-current`. The first update
captures hashes, services and the actual installed legacy layout, moving large
directories on the same filesystem instead of duplicating the recovery environment.
Unsupported layouts stop. Ordinary bundles/rollback do not change accounts, keys,
SSH/sudo policy, boot files, network profiles, app data or the stable updater.

Activation holds the same mutation lock as controller/touchscreen changes,
stops affected kiosk services while leaving SSH running, and requires fresh
process/version-bound System readiness and helper replies. Read-only health
does not acquire that lock. Pending network/display trials, queued operations,
expired maintenance and other updates block activation. Storage checks reserve
space for staging, the environment and copies on the existing 4 GiB root; updates
never delete the working or rollback release to fit. Interrupted activation is
recovered before provisioning or kiosk startup.

Normal mode requires a fresh controller main-thread maintenance acknowledgement
(maintenance protocol 1). For a broken controller, explicitly confirm physical
disconnection and use `--recovery --confirm-mill-disconnected`. Recovery does not
manufacture an acknowledgement or override fresh busy/connected status. A broken
controller may remain stopped after a successful System repair.

Inspect status after a lost SSH connection before retrying; submitted jobs run
independently of the laptop. Use `system-status --job REQUEST_ID` for their result.
For a supported rollback, enter maintenance and run:

```powershell
python kiosk.py system-rollback --host kiosk-admin@carvera-pi.local --identity ~/.ssh/id_ed25519_carvera_kiosk_admin
```

During migration, test rollback to the captured legacy release and verify both
SSH logins. Use `carvera-admin` for maintenance while its old helper is active.
Run `system-rollback` again through `kiosk-admin` to return to the new System
release, then verify its version, helper and tunneled viewer. Finally run
`python kiosk.py maintenance --host carvera-admin@carvera-pi.local --identity
~/.ssh/id_ed25519 leave` and confirm the controller remains disconnected.
System rollback preserves
admin access; controller rollback separately restores its saved preferences.

The stable updater and boot recovery live outside System releases. Upgrade it
only through `system-updater-install ... carvera-kiosk-updater-VERSION.tar.gz`
(inspect first with `--inspect`). It runs from a private worker snapshot,
self-tests a staged replacement, retains `updater-previous` and switches atomically.
If the launcher/runtime is damaged, full admin can run the retained implementation:

```sh
sudo /usr/bin/python3 -E -s /opt/carvera/updater-previous/system_update.py repair
```

Before the first updater upgrade, `updater-previous` does not exist. Inspect the
root-owned `bootstrap-*` directory under `/opt/carvera/updater-releases/` and run
that directory's `system_update.py repair` instead. Repair restores the stable
launcher and selects the retained implementation; it does not repair an
unbootable OS or replace account/network policy.

Do not perform a distribution/kernel upgrade as an ordinary System update. Those
need an explicit administration/recovery plan or replacement image.

## Screen access

Install `laptop-requirements.txt` in a laptop virtual environment, then run
`python kiosk.py screen --host kiosk-admin@carvera-pi.local --identity
~/.ssh/id_ed25519_carvera_kiosk_admin`. Use that environment's Python. The helper
starts WayVNC on `127.0.0.1:5901`, forwards it through verified SSH and opens noVNC
on a private laptop port. Its WebSocket requires the exact localhost Origin and
an automatically generated session token; no VNC password is needed. Keep the
token URL private. Press Enter in the launching terminal to clean up this
session's viewer, tunnel and owned remote server. Unrelated sessions are preserved.
Only one managed viewer session runs at a time. An existing session is left
alone; close its original viewer before starting another.

New images disable the distribution's automatic LAN VNC server. On the current
card, identify the existing server and verify the tunneled viewer first. With
explicit owner approval, disable the identified legacy unit (on the recorded
installation, `sudo systemctl disable --now wayvnc.service`). Do not stop an
unidentified or unrelated server. Confirm the legacy listener is gone on IPv4
and IPv6, then verify the on-demand localhost session and its cleanup.

## Recovery choices and key rotation

Offline boot undo restores the saved boot arguments; it does not revoke access
or reverse completed administration. Reinsert the card in the laptop and run:

```powershell
python kiosk.py admin-migration undo --boot-dir E:/ --package "C:/Kiosk Backup/admin migration"
```

Expect `boot_restored: true`. The matching staged directory is retained under an
`undone` name so it can be inspected and the same package staged again. Unexpected
boot edits stop undo instead of overwriting them. Keep retained payloads private.

Whole-card restoration is the disaster fallback. In USBImager select the retained
first uncompressed image, identify the exact target card by capacity/device,
enable Verify and click Write. This overwrites the entire selected card and
returns all files, credentials and settings to the backup time. Verify the
restored fingerprint and logins afterward. Never use this as normal migration.

Rotate keys through an already authenticated full administrator: validate the
new public key with `ssh-keygen -lf`, add it to the account's `authorized_keys`,
test a separate new SSH login with that key, then remove only the revoked key.
Preserve file ownership and modes (home `.ssh` 0700, `authorized_keys` 0600).
Provisioning/migration replays perform completion cleanup only; they do not add
revoked keys back or reset the console password. Removing a key does not close
established SSH sessions, tunnels or agent access. Close those sessions separately
when revoking access and unload keys with `ssh-add -d` as appropriate.

Remote recovery depends on a bootable OS, working network, SSH and storage.
Unbootable systems, damaged boot files and failed media retain an offline path.
Builds and automated boot tests do not replace physical validation of the Pi,
keyboard, touchscreen, rollback and viewer on the actual installation.
