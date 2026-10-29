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

## Build locally

Use Python 3.11 or newer, Git, and Docker Desktop with Linux containers. No Pi is
needed for the build. The first ARM build is slow under emulation; later builds
reuse dependencies. Run from the source checkout:

```powershell
python scripts/kiosk.py build --version 1.0.0.dev1
```

The equivalent existing build entry point is
`python scripts/build.py --os kiosk --version 1.0.0.dev1`.

Outputs in `dist/kiosk` include the compressed SD image, an application bundle,
checksums, package/version information, and a `laptop` folder containing the
maintenance helper and noVNC viewer. The image builder uses a pinned
[rpi-image-gen release](https://github.com/raspberrypi/rpi-image-gen/tree/v2.9.0).
Application dependencies follow `poetry.lock`; the image records installed OS
package versions. OS package repositories can change between builds.

## Prepare a card

Flash the `.img.xz` using Raspberry Pi Imager's custom-image option. Skip Imager's
OS customization and use the helper below for network/login setup. Keep the
existing Android card and use a spare card for initial testing. The image needs
an 8 GB or larger card. Before ejecting the flashed card, prepare its `bootfs`
partition from the laptop:

```powershell
python scripts/kiosk.py prepare-card --boot-dir E:/ --public-key ~/.ssh/id_ed25519.pub --hostname carvera-pi --ssid Workshop --country US
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
The touchscreen recovery screen can also set Wi-Fi and confirm the new network.

The `carvera-admin` account has key-based SSH and fixed maintenance commands,
without a general root shell. The touchscreen account can only recover Wi-Fi and
restart the controller after an idle confirmation. The recovery UI has its own
Kivy installation so an unsuccessful application update does not remove it.

## Application updates and rollback

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
data. Full OS/kernel updates require a replacement card image; this version
does not provide unattended updates or OS A/B rollback.

## Local checks and hardware validation

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
