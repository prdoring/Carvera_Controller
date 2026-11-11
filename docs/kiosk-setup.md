# Carvera Kiosk Setup

Carvera Kiosk Setup prepares an SD card for a Raspberry Pi 4 touchscreen kiosk.
Keep your working card for recovery and use a spare for installation. Setup
checks the selected card's capacity against the image before writing it.

## Download Setup

Choose a full kiosk release with Setup installers from
[this fork's releases](https://github.com/prdoring/Carvera_Controller/releases).
App-only releases update an existing installation. Windows 11 x64 and Debian
12+/Ubuntu 24.04+ x64/ARM64 are supported desktop targets.

| Computer | Installer | Portable package |
| --- | --- | --- |
| Windows 11 x64 | `carvera-kiosk-setup-VERSION-windows-x64.exe` (unsigned preview) | Matching `.zip` |
| Linux x64 | `carvera-kiosk-setup-VERSION-linux-x64.deb` | Matching `.tar.gz` |
| Linux ARM64 | `carvera-kiosk-setup-VERSION-linux-arm64.deb` | Matching `.tar.gz` |

Replace `VERSION` with the release's version number. Keep an extracted portable
folder together. Open Setup from your normal desktop account. It includes its
Python runtime and card writer. Linux needs X11 or XWayland, fontconfig, the
standard X11 libraries, and a desktop polkit authorization agent for card-access
prompts. The `.deb` declares the system dependencies.

### Check your download

Download `SHA256SUMS` from the same release. Calculate the SHA-256 checksum of
the downloaded installer or archive, then compare it with the line bearing that
exact filename in `SHA256SUMS`. For Windows PowerShell use the actual filename
in place of `INSTALLER.exe`.

```powershell
Get-FileHash -Algorithm SHA256 .\INSTALLER.exe
```

On Linux, with `SHA256SUMS` and the packages you downloaded in the same folder,
run the following. Confirm that every downloaded package reports `OK`.

```sh
sha256sum --check --ignore-missing SHA256SUMS
```

If a checksum differs, download the file again from the trusted release before
opening it. Windows packages are unsigned previews, so Windows may display an
unrecognized-app warning. Check the source and checksum before deciding to run it.

## Write the card

Follow **Choose a card → Set up your Pi → Write the card → Start the kiosk**.

1. Insert your spare card and choose **Install on an SD card**. Select it by
   reader name, capacity and device path. Refreshing or removing a card clears
   the selection, so you must select it again. If Windows offers to format the
   card's Linux partition, choose **Cancel**.
2. Choose **Download kiosk software** and select a compatible version. Setup
   searches automatically; use **Find compatible versions** to retry. Preview
   releases are included by default while Windows packages are unsigned.
3. Enter a lowercase Pi name using letters, numbers and hyphens. Setup shows
   the resulting `.local` address. Choose Ethernet or Wi-Fi. Wi-Fi requires a
   WPA-personal network, a two-letter country code, and an 8–63 byte password.
   Open, enterprise, captive-portal and WPA3-only networks require another
   network setup route.
4. If needed, expand **Restore a settings backup (optional)** and choose an
   exported preferences archive. Setup validates INI/JSON preferences and
   excludes programs, executables and links.
5. Create and confirm an **Access key passphrase**. Save it privately. Setup
   creates two distinct encrypted keys, for maintenance and full Pi
   administration. Screen Share uses the maintenance key. The passphrase
   unlocks the local keys when you connect from this computer.
6. Choose **Review setup**, check your choices, then **Prepare card**. Setup
   saves your profile and keys before downloading and checking the software.
   Approve the native card-access prompt when your computer asks.
7. At **Erase this card?**, check the physical card and capacity again, select
   the approval checkbox, then choose **Erase and write card**. Removing or
   replacing the card invalidates this confirmation.
8. Wait through writing, checking what was written, saving Pi settings and
   ejection. Remove the card when Setup says **Safe to remove the card**.

### Use downloaded files

Before going offline, download Setup, the matching `.img.xz` image,
`setup-release.json` and `SHA256SUMS` from one full release. Check the downloads.
In **Choose a card**, select **Use downloaded files**, then **Choose downloaded
files**. Select the metadata and matching image. The same
image checks and final card confirmation apply.

### Use existing access keys

Expand **Use existing access keys (advanced)**. Choose encrypted keys and enter
each key's passphrase. Maintenance and administrator keys must be distinct.
Setup creates a new key for any role you leave empty, using the new access key
passphrase. Original key files are retained.

If your administrator key has a different passphrase, expand **Separate
administrator passphrase** during **Check laptop access**. In Screen Share, always enter the maintenance key's passphrase.

### Configure an already-written card

From the home screen, expand **Advanced options** and choose **Configure an
already-written card**. Select a fresh `carvera-kiosk-pi4-v3` card and its matching
release metadata. For an offline setup, choose **Use downloaded files** and
select `setup-release.json`; an image file is unnecessary for configuration.
If another imager wrote the card, skip that imager's OS customization.

Completed installations use authenticated settings. Existing v1/v2 cards use
the [administration and migration guide](kiosk-administration.md).

## Start the kiosk

Insert the card into the Pi. Connect Ethernet if selected, leave the mill
disconnected, and power on. First startup prepares storage and applies settings;
this can take several minutes. Keep the Pi powered and wait for the controller
screen to open. An interrupted setup may show a limited setup screen with
**Retry the same setup** and **Shut down**.

The controller starts disconnected. When the mill is idle and you are ready,
tap **Connect** on the touchscreen. Opening a USB connection resets the mill.

## Check laptop access

Choose **Check laptop access** in Setup after the controller screen opens.
The current setup carries forward automatically. You can choose **Finish later**
and reopen **Continue a saved setup** to select your kiosk by name. Use **Browse
for profile** if its original `profile.json` is in a different folder.

1. Keep your computer and Pi on the same network. Try the prefilled hostname.
   On the Pi, open **Settings → System → Overview → Laptop access** for its
   current network addresses and **SSH identity**.
2. Choose **Compare fingerprint** in Setup. Compare the entire `SHA256:…`
   fingerprint with the touchscreen's SSH identity. Select the confirmation
   checkbox only for an exact match, then choose **Continue**.
3. Enter your access key passphrase. If your administrator key uses another
   passphrase, expand that option and enter it. Choose **Check laptop access**.
4. Wait for **Laptop access verified**. Setup checks the installation ID, image,
   controller, System and updater versions, both installed role keys, and full
   administrator access before saving trust.

A changed saved host key blocks the check. An address change is accepted only
with the exact trusted public key. Screen Share requires successful laptop
verification. Completing the card write alone does not verify laptop access.

### Keep your setup folder

Choose **Open setup folder** after verification and keep the folder with your
backups. Expand **Connection details** and choose **Copy connection details**
to copy addresses, public fingerprints and key locations. Keep the passphrases
separately. Setup does not save them.
Losing both keys and authenticated administrator access may require offline recovery.

Keys and profiles belong to the original desktop user, including when another
administrator approves UAC. They live under `~/.ssh/carvera/INSTALLATION_ID/`.
The local private transaction contains Wi-Fi settings until successful laptop
verification removes it and staged preferences. Downloaded images are cached
separately. The card contains its temporary Wi-Fi payload until successful Pi
setup removes it. Protect setup folders, cards and backups accordingly.

### Set up offline recovery

After laptop verification, choose **Set up offline recovery (optional)** to set
a local password for `kiosk-admin`. Enter the administrator key's passphrase
and confirm the new local recovery password. With a physical keyboard at the
Pi, press **Ctrl+Alt+F2**, log in as `kiosk-admin` with that password, then press
**Ctrl+Alt+F1** to return to the kiosk. This password is for the local console;
SSH uses the access keys. See [local keyboard fallback](kiosk-administration.md#local-keyboard-fallback).

## Resume or recover

Reopen Setup and choose **Continue a saved setup**. Select the kiosk by name.
If its card is in the Pi, wait for the controller screen and choose **Check
laptop access**. For an interrupted card operation, choose the offered retry
and select the card again. The original keys and saved request are reused.

| What happened | What to do |
| --- | --- |
| Preparation stopped before erase confirmation | The card has not been erased. Check the files or card permission prompt, select the card again and retry. |
| Writing or read-back checking failed or was cancelled | The card is not ready to boot. Select it again and explicitly approve erasing it to write again. |
| Pi settings could not be saved after writing | Choose **Retry saving settings** with the original setup. Select the same card again. |
| Settings saved but ejection failed | Wait for Setup to release card access. Close applications using the card and use your computer's Eject or Safely Remove control. After safe removal, choose **I safely removed the card**. |
| Pi startup was interrupted | Use **Retry the same setup** on its limited screen. Keep it powered while storage preparation finishes. |
| Pi reports storage or setup corruption, or no screen appears | Shut down safely if possible. Inspect the card's `carvera-setup-diagnostic.json`, retain the original profile, and use the working card or explicitly reinstall the spare. |
| Laptop cannot reach the Pi | Check power, network and the address under **Laptop access** on the Pi. Retry the connection check. |
| Access key will not unlock | Re-enter its passphrase. Existing administrator keys may have a different passphrase. |
| SSH identity changed or installation checks fail | Check the Pi and original profile. Saved trust is retained. |

Applying, completed, missing-journal and unknown cards cannot accept replacement
offline credentials. Resume the original setup on the Pi, use authenticated
System settings, or explicitly reinstall. Root completion remains authoritative
when power fails before cleanup; replay reconciles receipts and removes temporary
payloads without restoring revoked keys or changing settings again.

## Screen Share

Choose **Download Screen Share** after **Laptop access verified**, then open
the separate **Carvera Kiosk Screen Share** app. Select the verified kiosk by
name, enter its maintenance key passphrase and click **Connect**. Its touchscreen
opens in your browser and allows input. Click **Disconnect** in Screen Share
when finished. An unverified setup directs you back to **Continue a saved setup**
and **Check laptop access** in Setup.

The app checks the exact installation and host key with maintenance credentials.
Its browser listeners use localhost, an ephemeral session token and exact Origin
checks. The server lease renews every 20 seconds and expires after 90 seconds
without renewal. Cleanup releases only that session. A compatibility error
requires matching System tools before a managed session can start.
