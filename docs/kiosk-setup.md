# Carvera Kiosk Setup

Setup installs a complete Raspberry Pi 4 kiosk on a new card. Screen Share is a
separate download for an already verified kiosk. Routine controller/System
updates and existing-card administrator migration remain in the
[administration guide](kiosk-administration.md).

## Downloads

Choose a full release containing `setup-release.json`, the image and all three
desktop targets. App-only update releases are not installation images. Windows
11 x64 and Debian 12+/Ubuntu 24.04+ x64/ARM64 are the initial desktop targets.
Windows packages are unsigned prereleases until signing is implemented. Download
from [this fork's releases](https://github.com/prdoring/Carvera_Controller/releases)
and verify the files you use against `SHA256SUMS`.

Windows has a normal-user installer and portable ZIP. Linux has a `.deb` and a
portable archive. The portable folder must stay together. Linux needs a desktop
with X11 or XWayland, fontconfig and the standard X11 libraries. Card permission
prompts use polkit; a working desktop authorization agent is required. The `.deb`
declares its system dependencies. Installers never start an elevated GUI or
install a permanent privileged service.

## New card

1. Open Setup from your ordinary desktop account. Insert the new card and keep
   the working card unchanged.
2. Choose **Install on a new card**. Refresh and select the card by its device
   identity and capacity. Find a compatible full release; preview releases are
   included by default while Windows downloads are unsigned.
3. Enter a valid lowercase kiosk name and select Ethernet or WPA-personal Wi-Fi.
   Wi-Fi needs a two-letter country and an 8–63 byte password. Enterprise,
   captive-portal and open Wi-Fi are outside this setup flow.
4. Choose preferences if needed. Imports accept supported INI/JSON preferences,
   validate the entire archive and exclude executables and machine programs.
5. Enter and confirm a nonempty key passphrase. Setup generates two distinct
   encrypted keys. Advanced reuse accepts selected encrypted keys with separate
   passphrases, and still requires distinct maintenance/administrator identities.
6. Review and prepare installation. Approve the native UAC/polkit card prompt.
   The worker verifies both compressed and decompressed image hashes and exact
   lengths before it offers the final card confirmation.
7. Check that final physical card and capacity. Approve **Erase and install**.
   Removal/replacement invalidates the held media check. Wait through flashing,
   read-back verification, configuration and ejection.
8. Insert the card into the Pi and power on with the mill disconnected. Keep it
   powered while first-boot storage growth and setup finish.

The GUI, encrypted keys and saved profile belong to the original desktop user,
including when a different administrator approves UAC. Private keys never go to
the Pi. The private local transaction file includes Wi-Fi settings so identical
retries can succeed; protect the whole key folder and do not share that file.
The profile and copied connection details exclude passwords and private request
digests. First-boot verification removes the laptop's private setup transaction
and staged preferences, retaining nonsecret release metadata. Downloaded images
are cached separately from the key folder. The card's setup payload contains the Wi-Fi password until successful
first boot removes it.

## Offline or already flashed

For offline installation, download the Setup package, matching image,
`setup-release.json` and `SHA256SUMS` while online. Select **Open offline release
metadata** and the corresponding image file. The same verification and card
confirmation apply.

If another tool already flashed a fresh `carvera-kiosk-pi4-v3` image, choose
**Configure an already-flashed card** and its matching metadata. Skip that
tool's OS customization. Graphical Configure does not migrate v1/v2 installations
or replace credentials on completed cards. Existing CLI tools retain their
documented v2 preparation and legacy migration routes; old distributed v2 tools
reject the new v3 marker before writing.

## First-boot verification

Choose **Check first boot** and the original `profile.json`. Enter the kiosk
hostname or address and the key passphrases. Compare the displayed fingerprint
with the kiosk touchscreen before accepting it. An existing saved host key is
never replaced automatically. A hostname/address change is allowed only with
the exact same trusted public key.

Verification checks the installation operation ID, image source, controller,
System and updater versions, the installed role keys and full administrator
sudo. Trust is saved only after those checks pass. The controller starts
disconnected. Setting a local recovery password does not enable SSH password
login. Test TTY2 login with a physical keyboard, then return to TTY1; see
[local keyboard fallback](kiosk-administration.md#local-keyboard-fallback).

The finish screen provides **Show key folder**, **Copy connection details** and
**Download Screen Share**. If Setup cannot find the matching public download, it
opens the fork's releases page and shows the version to look for. Draft assets
require signing into GitHub with access to the draft. Keep the encrypted keys
and profile with your backups. Their passphrases are not saved, and losing both
keys and authenticated administrator access may require offline recovery.

## Incomplete setup

| Result | Next step |
| --- | --- |
| Download or image verification failed | Check the release/image pairing and retry; erasure has not started. |
| Flashing or read-back verification failed/cancelled | Keep the saved profile; explicitly select and install the card again. |
| Configuration incomplete after verified flashing | Reopen **Resume saved card setup** with the original profile and retry configuration; the same keys/request are retained. |
| Pi reports interrupted setup | Use **Retry the same setup** on its limited screen. It resumes only the journaled transaction. |
| Card is applying, complete or unknown | Do not replace its offline configuration. Resume the identical transaction on the Pi, use authenticated System settings, or explicitly reflash. |
| Setup/storage state is corrupt or no screen appears | Shut down safely if possible. Inspect the bounded `carvera-setup-diagnostic.json` receipt; restore the working card or explicitly reinstall the new card. |

Do not format Windows' unfamiliar Linux partition. A setup error never grants
password SSH, a shell on the limited touchscreen screen, or a mill connection.
Completed setup replay reconciles its nonsecret receipt and cleans payloads; it
does not restore revoked keys or rewrite network settings, preferences or console
passwords. Root completion is authoritative if power fails before FAT cleanup.

## Screen Share

Open the separate Screen Share app, choose the verified profile, enter the
maintenance key passphrase and click **Connect**. It checks the same installation
ID and trusted host key. It never falls back to administrator credentials, an
SSH agent or implicit SSH configuration commands. Click **Disconnect** before
closing the session. Screen sharing permits touchscreen input; it does not
authorize machine operations by an AI session.

The local browser connection uses an ephemeral session token and exact localhost
Origin checks. Both local listeners retain their dynamically assigned sockets.
The server lease renews every 20 seconds and expires after 90 seconds without a
renewal. A lost connection or killed viewer cannot take over another session.
Only the matching owned session is cleaned up. Older clients/servers receive a
compatibility error before starting an unsupported managed session.
