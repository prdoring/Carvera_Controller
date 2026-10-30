# Pi Kiosk v@VERSION@: setup and laptop tools

Download the files from [Pi Kiosk v@VERSION@](https://github.com/prdoring/Carvera_Controller/releases/tag/kiosk-v@VERSION@):

- `carvera-kiosk-pi4-@VERSION@.img.xz`: Raspberry Pi 4 SD card image.
- `carvera-kiosk-laptop-@VERSION@.zip`: these laptop tools.
- `carvera-kiosk-app-@VERSION@.tar.gz`: application update for an existing kiosk.
- `SHA256SUMS`: SHA-256 hashes for all three downloads.

Compare the downloaded files with `SHA256SUMS` before using them. On Linux,
run `sha256sum -c SHA256SUMS` beside the three downloads. On Windows, use
`Get-FileHash <filename> -Algorithm SHA256` for each file and compare its hash.

Extract the laptop ZIP. Keep `kiosk.py`, `laptop-requirements.txt`, `README.md`,
and the complete `novnc` folder together in the extracted **laptop** folder.
Open a terminal in that folder for the commands below. Git and Docker are not
needed to install a downloaded image.

## Install a new kiosk

Install Raspberry Pi Imager, Python 3.11 or newer, and the OpenSSH client tools
(`ssh`, `scp`, and `ssh-keygen`) on your computer.

If you do not have an SSH key pair, run `ssh-keygen -t ed25519` and accept the
default file location. The setup helper uses `~/.ssh/id_ed25519.pub`. Keep the
private key on your computer; do not copy it to the card or Pi.

1. In Raspberry Pi Imager, choose the downloaded `.img.xz` as a custom image.
   Flash a spare SD card and retain the old card for recovery. Skip Imager's OS
   customization.
2. Before ejecting the card, configure its **bootfs** partition. Replace `E:/`
   with the actual drive or mount path, and change the key path, hostname,
   network name, and country as needed:

   ```powershell
   python kiosk.py prepare-card --boot-dir E:/ --public-key ~/.ssh/id_ed25519.pub --hostname carvera-pi --ssid Workshop --country US
   ```

   The helper prompts for your Wi-Fi password. For Ethernet, omit `--ssid` and
   `--country`. To import an exported Android preferences backup, add
   `--settings backup.tar.gz`. The temporary provisioning file contains the
   Wi-Fi password until first boot; protect the card. The Pi removes it after
   installing the settings and creates its own SSH host keys.
3. Insert the card in the Pi and power it on. Under **Settings -> System**, find
   its network address and SSH fingerprint. Connect once:

   ```sh
   ssh carvera-admin@carvera-pi.local
   ```

   Compare the fingerprint with the touchscreen before accepting it. Use the
   displayed IP address if `.local` does not resolve. Type `exit` to return to
   your computer's terminal.
4. The controller starts disconnected. Tap **Connect** and select USB or a
   network connection. Opening USB resets the mill; connect only when it is
   safe to interrupt it. Installing this kiosk does not reflash the mill.

## Maintain an existing kiosk

Use the same hostname or IP address you verified above:

```sh
python kiosk.py diagnose --host carvera-admin@carvera-pi.local
python kiosk.py logs --host carvera-admin@carvera-pi.local
python kiosk.py backup --host carvera-admin@carvera-pi.local preferences.tar.gz
```

App updates preserve user G-code and settings. With the mill idle and safe for
interruption, enter maintenance, deploy the app bundle, then leave maintenance:

```sh
python kiosk.py maintenance --host carvera-admin@carvera-pi.local enter --confirm-machine-idle
python kiosk.py deploy --host carvera-admin@carvera-pi.local carvera-kiosk-app-@VERSION@.tar.gz
python kiosk.py maintenance --host carvera-admin@carvera-pi.local leave
```

Startup failure restores the previous app. For manual rollback, enter
maintenance, run `python kiosk.py rollback --host carvera-admin@carvera-pi.local`,
then leave maintenance. The app remains disconnected after an update. Full OS
updates require a replacement SD card image.

Optional screen sharing needs the companion dependencies. Create a virtual
environment with `python -m venv .venv-kiosk`. On Windows, run:

```powershell
.venv-kiosk/Scripts/python -m pip install -r laptop-requirements.txt
.venv-kiosk/Scripts/python kiosk.py screen --host carvera-admin@carvera-pi.local
```

On Linux or macOS, use `.venv-kiosk/bin/python` instead. Press Enter in the
terminal when finished to close the viewer and tunnel.

See the [main README](https://github.com/prdoring/Carvera_Controller#install-the-kiosk)
and [kiosk guide](https://github.com/prdoring/Carvera_Controller/blob/main/assets/packaging/kiosk/README.md)
for supported display settings, network recovery, and development instructions.
