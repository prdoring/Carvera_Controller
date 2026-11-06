# Raspberry Pi touchscreen kiosk

This build runs the shared Carvera controller directly on 64-bit Linux. It targets
a Raspberry Pi 4 with one 1920 × 1200 touchscreen. Android and desktop builds keep
their existing paths; the kiosk selects the same touch layouts, numeric pads and
UI scale controls as Android, with Linux services and a docked text keyboard.

The image uses Debian Trixie with Raspberry Pi firmware and Mesa, a small labwc
Wayland session, and SDL2. Kivy is compiled against the system SDL2 because its
prebuilt Linux wheel lacks Wayland support. There is no desktop environment,
browser, display manager or Android runtime. The CPU governor defaults to
`performance`; stock clock limits and thermal protection remain in effect.
The display uses an advertised mode near 60 Hz, defaulting to native 1920 × 1200.
Screen sharing runs only when requested. System logs have a size limit and
automatic package-update timers are disabled.
ModemManager is masked so it cannot probe the mill's serial port.

The controller starts disconnected. Tap Connect to open the machine connection;
opening USB resets the mill. USB is the default preferred method for fresh
settings, and network connections remain available.

## Install from a release

Use the main [graphical setup steps](../../../README.md#install-the-kiosk) or
[setup guide](../../../docs/kiosk-setup.md). A compatible full release has
`setup-release.json`, Setup and Screen Share packages for all three desktop
targets, a v3 image and separate update artifacts. An app-only release cannot
install a fresh card. Graphical users do not need Python, OpenSSH, Git, Docker or
another card-writing app.

## Build locally

See the [administration guide](../../../docs/kiosk-administration.md) for fresh
setup, migration without reflashing, backup/undo, System updates and recovery.
The graphical image format is `carvera-kiosk-pi4-v3`; request format 2 is retained.
Old v2 tools reject v3 cards. Matching new CLI tools still handle v2 preparation
and legacy migration through their separate paths.

Use Python 3.11 or newer, Git, and Docker Desktop with Linux containers. No Pi is
needed for the build. The first ARM build is slow under emulation; later builds
reuse dependencies. Run from the source checkout:

```powershell
python scripts/kiosk.py build --version 1.0.0.dev1
```

The equivalent existing build entry point is
`python scripts/build.py --os kiosk --version 1.0.0.dev1`.

Image builds produce the compressed image, controller, System and updater bundles,
laptop ZIP/folder, image metadata and component checksums. The trusted full-release
workflow adds the native desktop packages, complete metadata and checksum inventory.
See [desktop builds](../../../docs/development.md#kiosk-desktop-tools).
Use `build --system-only
--version VERSION` for independent System builds. The image builder uses a pinned
[rpi-image-gen release](https://github.com/raspberrypi/rpi-image-gen/tree/v2.9.0).
Application dependencies follow `poetry.lock`; the image records installed OS
package versions. OS package repositories can change between builds.

## Advanced CLI card preparation

Flash the `.img.xz` using Raspberry Pi Imager's custom-image option. Skip Imager's
OS customization and use the helper below for network/login setup. Keep the
existing Android card and use a spare card for initial testing. The image needs
an 8 GB or larger card. Before ejecting the flashed card, prepare its `bootfs`
partition from the laptop:

```powershell
python scripts/kiosk.py prepare-card --boot-dir E:/ --public-key ~/.ssh/id_ed25519.pub --admin-public-key ~/.ssh/id_ed25519_carvera_kiosk_admin.pub --hostname carvera-pi --ssid Workshop --country US
```

Select the actual drive, network name, country and SSH public-key file. The
helper verifies the image identity and prompts privately for the Wi-Fi password.
Omit `--ssid` and `--country` for Ethernet. The setup file contains the Wi-Fi
password until first boot; the Pi installs a root-readable network profile and
removes the setup file after successful provisioning. It also creates unique SSH
host keys. Credentials are not included in the built image.

An optional `--settings backup.tar.gz` imports preferences from an exported
Android application backup. Only INI/JSON preferences are copied to the card;
G-code, scripts and links are excluded. First boot translates Android storage
paths and clears Android-specific USB paths and input/display configuration.
Preference files remain separate from application releases.

Start the Pi and use Settings → System to see its network address and SSH
fingerprint. Once, connect with `ssh carvera-admin@carvera-pi.local`, compare the
fingerprint with the touchscreen, and accept that identity. Later helper commands
require that saved identity and refuse an unknown or changed host key. Use the
displayed IP address if the laptop cannot resolve `.local`.

## Laptop maintenance

The exported `laptop/kiosk.py` works without the source checkout. These examples
use the checkout copy. Every device command requires an explicit host:

```powershell
python scripts/kiosk.py diagnose --host carvera-admin@carvera-pi.local
python scripts/kiosk.py logs --host carvera-admin@carvera-pi.local
python -m venv .venv-kiosk
.venv-kiosk/Scripts/python -m pip install -r dist/kiosk/laptop/laptop-requirements.txt
.venv-kiosk/Scripts/python scripts/kiosk.py screen --host carvera-admin@carvera-pi.local
```

Screen opens a browser viewer through an SSH tunnel. Both laptop listeners bind
to localhost. Press Enter in the helper to stop its viewer, tunnel and the Pi
screen-sharing service it started. An existing screen-sharing session is left
running. Diagnostics include the renderer, framebuffer size, temperature, clock,
memory, pressure, background processes and running services.

Enter maintenance before updating or changing the system:

```powershell
python scripts/kiosk.py maintenance --host carvera-admin@carvera-pi.local enter --confirm-machine-idle
python scripts/kiosk.py configure --host carvera-admin@carvera-pi.local governor performance
python scripts/kiosk.py maintenance --host carvera-admin@carvera-pi.local leave
```

A connected controller must report idle and remain idle with controls blocked
before acknowledging maintenance. Jobs, jogging, probing, transfers and unknown
machine states block changes. With a stopped, disconnected or unresponsive
controller, the explicit idle confirmation is required. No maintenance tool
opens a second connection to the mill. Emergency stop remains available in the
maintenance screen. Maintenance expires after 30 minutes and must be entered
again before further changes.

Supported system settings are `governor performance|schedutil`,
`display 1920x1200|1920x1080`, `network`, `network-confirm`, `restart`, and `reboot`.
Display changes require a mode actually advertised by the attached screen; 1080p
is provided for matched performance comparisons. Wi-Fi changes roll back after
120 seconds unless confirmed. If the address changes, use Settings → System to
find it, reconnect, run `configure network-confirm`, then leave maintenance.
The touchscreen System screen can also set Wi-Fi and confirm the new network.

The `carvera-admin` account retains fixed maintenance commands. `kiosk-admin`
has a dedicated key and full passwordless sudo; it can update the independent
System application. The touchscreen account retains restricted recovery access.
Root/password SSH stay disabled. Set and test the local TTY2 console fallback
after administrator SSH works. See the administration guide for key setup,
agent loading, migration checkpoints, rollback and the first legacy update.
Disruptive actions require an idle confirmation and the
same maintenance acknowledgement as laptop operations. The recovery UI has its
own service, Kivy installation and a separate copy of the shared theme, fonts and language
catalogs, so an unsuccessful application update does not remove it.
System operations run in separate, bounded workers so closing or restarting the
interface does not terminate an update. Reopening shows the recorded operation
state; refresh its result before attempting a failed or interrupted action again.

## Touchscreen System settings

Settings → System opens an independent interface with Overview, Network, Display,
Maintenance and Power sections. It remains available while the controller is
restarting or unavailable. It never opens a connection to the mill.

Network supports WPA-personal networks and manual entry of hidden SSIDs. Open,
enterprise and WPA3-only networks are not supported by this form. Enter the
password, select Connect Wi-Fi, and confirm that the machine is idle. Keep the
network within 120 seconds or it reverts. The confirmation bar remains visible
when switching sections. Use Paste explicitly to insert clipboard text; touching
an action after editing must not paste text or require a second tap.

Display lists the supported modes advertised by the screen near 60 Hz. Preview a
mode and select Keep change within 20 seconds. A system timer restores the saved
mode if System closes, fails or receives no confirmation. Only confirmed modes
are saved for future starts.

Maintenance can export diagnostics and logs, back up preferences, install staged
application bundles, restore preferences, and restore the previous application
with its saved preferences. Failed update startup restores the previous release
and preferences. Restore creates a separate preferences backup before changing
files and restores that backup if controller startup fails. Read the confirmation
before proceeding. Reconnecting the mill is always a separate action.

Use the laptop helper to transfer files without starting an installation:

```powershell
python scripts/kiosk.py stage --host carvera-admin@carvera-pi.local carvera-kiosk-app-1.0.0.dev2.tar.gz
python scripts/kiosk.py stage --host carvera-admin@carvera-pi.local preferences.tar.gz
python scripts/kiosk.py fetch --host carvera-admin@carvera-pi.local EXPORTED_FILENAME preferences-copy.tar.gz
```

Use the actual host and exported filename displayed by System. In the extracted
laptop tools folder, use `python kiosk.py` instead. Stage and fetch use the
caller's transfer directories reported by the helper and
refuse to overwrite an existing local file. System shows the selected file's
name, size and checksum before an installation or restore. If it changes after
selection, refresh and review it again.

Use `carvera-admin` for files selected or exported on the touchscreen. The
`kiosk-admin` transfer area belongs to that account's laptop operations.

Power separates restarting the controller from restarting or shutting down the
Pi. The controller restarts disconnected. After shutting down, wait for the
display to turn off and disk activity to stop before removing power. Finish
laptop-owned maintenance from the laptop; System cannot take over that session.

These System tools, service behavior and independent presentation assets are
image-installed. An application-only bundle cannot replace those tools on an
older kiosk. Full OS updates still use replacement images.

### Existing images: application-only System screen

When the independent System tools are absent, the controller opens an
app-bundled System screen. It provides the shared touch styling, readable device
information, manual Wi-Fi entry, Keep network and Restart controller through
the older image's existing restricted helper. The existing independent emergency
recovery screen remains installed and unchanged. The app-bundled screen closes
when the controller restarts; it is not the independent System replacement.

This mode does not provide display preview, touchscreen app installation,
settings restore, shutdown, or the new background operation tracking. Continue
using the laptop helper for supported application updates. Installing the full
independent System tools requires a separately supported system-tools update
with administrator access, or a replacement image. Card access is not required
for this reduced application-only mode.

The older backend does not enforce the new cross-client maintenance ownership
rules. Do not perform laptop maintenance concurrently with changes from this
screen. The screen checks existing maintenance before an action and refuses
sessions it did not start; it cannot add an atomic ownership guarantee to the
installed helper.

The older helper can leave maintenance active after a Wi-Fi rollback. The
screen reports this condition rather than claiming maintenance has ended. Finish
through a deliberate controller restart after confirming machine idle, or have
the laptop operator leave maintenance. A countdown in the app is a conservative
local estimate; NetworkManager owns the actual network rollback.

Some early images also cannot export a laptop preferences backup because the
helper attempts to rename across filesystems. Their automatic deployment and
rollback snapshots use a different path. An app-only update does not repair the
installed backup helper; do not report a failed laptop export as a saved backup.

## Application updates and rollback

The main update dot checks this fork's published `kiosk-v` application releases.
Open the release page on your laptop and download the app archive and its
checksum. App-only releases provide a `.tar.gz.sha256` file; full releases use
`SHA256SUMS`. Verify the downloaded archive before deployment. Automatic checks
only report availability; they do not install or enter maintenance.

The extracted laptop helper uses `python kiosk.py`; source checkouts use
`python scripts/kiosk.py`. Keep the helper's companion files together. Back up
preferences before an update, confirm the actual target and an idle machine,
then follow the maintenance sequence below. Rollback restores previous
preferences as well as the previous app. Reconnecting the mill is a separate
operation; opening USB resets it.

An app bundle does not update the OS, services or image-installed maintenance
and recovery tools. Read release notes for separately required image/tool
updates. App-only releases do not replace the full-image installation downloads.
Community firmware update notices appear only in the Firmware tab; a firmware
version higher than the kiosk app version is not evidence of incompatibility.


Build a uniquely versioned application bundle without rebuilding the OS:

```powershell
python scripts/kiosk.py build --version 1.0.0.dev2 --app-only
python scripts/kiosk.py maintenance --host carvera-admin@carvera-pi.local enter --confirm-machine-idle
python scripts/kiosk.py deploy --host carvera-admin@carvera-pi.local dist/kiosk/carvera-kiosk-app-1.0.0.dev2.tar.gz
python scripts/kiosk.py maintenance --host carvera-admin@carvera-pi.local leave
```

Deployment verifies bundle checksums, installs dependencies offline as the
touchscreen user, saves preferences, then switches releases. The new app must
reach a healthy maintenance state. Failure restores the previous release and
preferences. The app remains disconnected after restarting.

The image retains the current and previous app releases, removing older app
files after a successful update. `rollback --host ...` switches to the previous app and its saved preferences
while in maintenance. `backup --host ... preferences.tar.gz` saves preferences
to the laptop. App updates preserve G-code files and the rest of application
data. OS/kernel upgrades require a separately scoped administration/recovery plan
or replacement image. System bundles do not provide unattended OS updates or OS
A/B rollback. Use a unique unused version for every build.

## Local checks and hardware validation

The file-backed boot tests run real Debian 13/systemd 257 without a Pi, network
or physical drives. From the source checkout in PowerShell:

```powershell
docker build -t carvera-kiosk-boot-tests -f assets/packaging/kiosk/Dockerfile.boot-test .
docker run --rm --init --network none --mount "type=bind,source=$PWD,target=/src,readonly" carvera-kiosk-boot-tests
```

They cover dedicated migration boot, real account/SSH/sudo validation, revoked-key
replay, normal startup and recovery before provisioning/CPU/kiosk after an
interrupted conversion. They do not validate the Pi's graphics, console, network
or touchscreen. Obtain operator readiness for physical acceptance tests.

```powershell
docker build -t carvera-kiosk-tests -f assets/packaging/kiosk/Dockerfile.test .
docker run --rm --init --network none carvera-kiosk-tests
docker run --rm --init --network none -e CARVERA_PROFILE=kiosk -e CARVERA_RUNTIME_DIR=/tmp/carvera-run -e CARVERA_MAINT_DIR=/tmp/carvera-maint carvera-kiosk-tests python assets/packaging/kiosk/run_checks.py tests/integration/test_kiosk.py -q
docker run --rm --init --network none -e CARVERA_PROFILE=kiosk carvera-kiosk-tests python assets/packaging/kiosk/run_checks.py tests/integration/test_kiosk_recovery.py -q
docker run --rm --init --network none -e PYTHONPATH=/src carvera-kiosk-tests python assets/packaging/kiosk/headless_check.py
```

These checks cover the shared application, keyboard/layout, maintenance guards,
settings import, failed updates, rollback, SDL Wayland startup and the VNC
protocol. The virtual-display checks stop their processes and check IPv4/IPv6
listeners. Containers cannot verify Pi graphics acceleration, touchscreen input,
USB behavior or performance.

On the actual Pi, first verify V3D rather than a software renderer, native size
and refresh, touch accuracy and multi-touch, the text/numeric keyboards, USB and
network connection behavior, Wi-Fi recovery, remote updates and rollback.
Compare the same representative G-code files and interactions with Android at
1080p, then judge native-resolution behavior separately. Record load times,
interaction stalls, memory, temperature and throttling with screen sharing
closed. A successful image build is not hardware or CNC validation.
