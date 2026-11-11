![Jog screen before and after](docs/screenshots/fork/jog-before-after.png)

# Carvera Controller: Pat’s Raspi 4 Kiosk Fork

A [Community Carvera Controller](https://github.com/Carvera-Community/Carvera_Controller) fork for running a **Raspberry Pi 4 touchscreen kiosk** beside a Carvera or Carvera Air. It boots directly into the controller and includes an on-screen keyboard, numeric entry pads, and laptop maintenance tools.

Built around Pat’s **1920 × 1200 touchscreen**, with a redesigned interface and improvements to touch controls. Desktop and Android builds are also available from source.

I use and test this fork on my **Carvera Air**. Your mileage may vary on other machines.

[Set up a kiosk](#install-the-kiosk) · [Hardware](#hardware) · [Firmware](#firmware) · [Features](#controller-improvements) · [Other platforms](#desktop-and-android) · [Development](docs/development.md)

## Raspberry Pi kiosk

- Boots into the controller on 64-bit Debian Linux.
- Provides touch jogging, numeric pads, a text keyboard, and adjustable interface size.
- Supports laptop diagnostics, logs, backups, and optional screen sharing over SSH.
- Preserves preferences during app updates and restores the previous release if startup fails.

![Probing screen with the on-screen number pad](docs/screenshots/fork/kiosk-probing-number-pad.png)

### Hardware

| Part | Target setup |
| --- | --- |
| Computer | Raspberry Pi 4 |
| Display and enclosure | [XBONFIRE 10.1-inch HDMI touchscreen/enclosure](https://www.amazon.com/dp/B0DDL5VMZF) |
| Resolution | 1920 × 1200 (16:10), approximately 60 Hz |
| Storage | SD card, 8 GB or larger |

**The kiosk targets this display resolution.** Its display tools accept 1920 × 1200 and a 1920 × 1080 comparison mode, both near 60 Hz. The screen must advertise the selected mode. Other resolutions need changes to the display setup and may need layout adjustments.

For another resolution, [open an issue](https://github.com/prdoring/Carvera_Controller/issues) with your display model and resolution. Support can be added on request; further work will follow demand.

### Firmware

**Built for use with [Carvera Community Firmware 2.2.0c](https://github.com/Carvera-Community/Carvera_Community_Firmware)**, the version used on Pat’s Carvera Air (CA1).

This fork does not require its own machine firmware. Installing the kiosk does not by itself require reflashing the mill. The [recorded device tests](docs/raspberry-pi-android-performance.md) cover the Android controller on 2.2.0c.

Features depend on the firmware reported by the machine. Higher USB baud rates require community firmware 2.1.0 or newer. Live vacuum-power controls require firmware that reports external-output state and power.

## Install the kiosk

You'll need a Raspberry Pi 4, a touchscreen, a microSD card and reader, and a
Windows or Linux computer. If you already have a working kiosk, set its card
aside and use a spare. Setup erases the card you select.

### 1. Download and open Carvera Kiosk Setup

Choose a release with Setup installers from [this fork's releases](https://github.com/prdoring/Carvera_Controller/releases).
App-only releases contain updates for an existing installation. The filenames
below use `<version>` for the release's version number.

- **Windows 11 x64** — `carvera-kiosk-setup-<version>-windows-x64.exe` (unsigned preview).
- **Debian 12+ / Ubuntu 24.04+** — `carvera-kiosk-setup-<version>-linux-x64.deb`
  or `carvera-kiosk-setup-<version>-linux-arm64.deb`, matching your computer.

Open **Carvera Kiosk Setup** from your normal desktop account. Setup can download
the kiosk software for you. See the [setup guide](docs/kiosk-setup.md) for checking
your download, portable packages, or installing offline. Developer builds are
described in [development](docs/development.md#kiosk-desktop-tools).

### 2. Write the microSD card

1. Insert the card into your computer. Choose **Install on an SD card**, select
   the card by its reader name and capacity, and choose **Download kiosk software**.
2. Name your Pi and choose how it will join your network. If you choose Wi-Fi,
   enter the network name and password. Create an access key passphrase and save
   it somewhere private. You'll use it when connecting from your computer later.
3. Review your choices and click **Prepare card**. Allow the computer's
   card-access prompt. When Setup shows **Erase and write card**, check the
   reader name and capacity again before confirming.
4. Keep the card inserted until Setup says **Safe to remove the card**. If
   Windows asks to format the card during setup, click **Cancel**.

### 3. Start the Pi

Put the card in the Pi. If you chose Ethernet, plug in the network cable. Leave
the mill disconnected and power on the Pi. First startup can take several
minutes. Wait for the controller screen to open.

In Setup, choose **Check laptop access** if you plan to use Screen Share or
maintain the Pi from your computer. You can also choose **Finish later** and
come back through **Continue a saved setup**.

### 4. Connect the mill when you're ready

The controller starts disconnected. Opening a USB connection resets the mill.
When the mill is idle and you're ready to connect, tap **Connect** on the
touchscreen and choose USB or a network connection to the mill.

### Use Screen Share from your computer

1. With your computer and Pi on the same network, choose **Check laptop access**
   in Setup. Try the suggested Pi address. If it doesn't work, find the Pi's
   address on the touchscreen under **Settings → System → Overview → Laptop access**.
2. On that same touchscreen page, find **SSH identity**. Compare the `SHA256:…`
   fingerprint with the one Setup shows on your computer. Continue only if they
   match exactly. Enter the access key passphrase you saved when preparing the card.
3. When Setup says **Laptop access verified**, choose **Download Screen Share**.
   Open **Carvera Kiosk Screen Share**, select your kiosk, enter the passphrase,
   and click **Connect**. The touchscreen opens in your browser. Click
   **Disconnect** in Screen Share when you're done.

If Setup stops partway through, reopen it and choose **Continue a saved setup**.
See the [setup guide](docs/kiosk-setup.md) for card errors, interrupted first
startup, separate key passphrases, and offline recovery.

## Laptop maintenance

From the extracted laptop folder, use the same hostname or IP address you used for SSH:

~~~bash
python kiosk.py diagnose --host carvera-admin@carvera-pi.local
python kiosk.py logs --host carvera-admin@carvera-pi.local
python kiosk.py backup --host carvera-admin@carvera-pi.local preferences.tar.gz
~~~

The backup command saves preferences to your computer.

For an **existing card**, follow [migration without reflashing](docs/kiosk-administration.md#migrate-an-existing-card):
capture identity online, shut down safely, make two independent verified whole-card
backups, stage on the identified boot partition and run the dedicated migration
boot. Do not use `prepare-card` on an already provisioned installation.

The [administration guide](docs/kiosk-administration.md) covers separate System
updates, rollback, local-console recovery, keys and SSH-tunneled screen access.
Updates require maintenance and operator readiness; broken-controller recovery
requires physical disconnection. Failed storage retains an offline recovery path.

## Controller improvements

### Interface and touch controls

The Slate Workshop theme adds dark panels, consistent controls, new icons, and redrawn probing illustrations. Touch layouts cover job setup, probing, facing, CMM, settings, and file browsing.

- Enter signed decimal values with the number pad.
- Keep fields and confirmation buttons above the keyboard.
- Jog with one controlling finger. Sliding off stops movement; sliding back does not restart it.
- Viewer gestures, scrolling, and playback scrubbing stay with the finger that started them.
- Find file actions directly in the browser and adjust the interface size to suit the display.

![G-code preview with a loaded facing toolpath](docs/screenshots/fork/desktop-preview.png)

More screenshots: [compact jog screen](docs/screenshots/fork/touch-control.png), [touchscreen preview](docs/screenshots/fork/touch-preview.png), [probing](docs/screenshots/fork/touch-probing.png), and [facing wizard](docs/screenshots/fork/touch-facing.png).

### Connections and responsiveness

Android has native USB serial support, including the FTDI adapter in Pat’s Carvera Air setup, and can reconnect using a saved adapter identity.

Network connection setup and G-code preparation run in the background. Optional dialogs load when first opened to reduce startup work. Large previews can still cause pauses.

### Vacuum controls

The spindle dropdown provides **50–100%** live vacuum-power adjustment when compatible firmware reports that the external output is on. The control is disabled when status is missing or stale.

Carvera Air settings also expose the default vacuum power for **Auto Ext. Out**. Reset the machine after applying that default.

## Community features

The fork retains advanced 3D probing, WHB04-family pendant support, keyboard jogging, work coordinate management, configurable autolevel areas, job setup backgrounds, custom tool numbers, facing, CMM tools, and a rotary-aware G-code preview.

Availability depends on the machine, firmware, and accessories. Advanced 3D probing needs a suitable touch probe. Tool-changing features need ATC hardware; a factory Carvera Air does not have an ATC.

## Desktop and Android

### Run from source on Windows, Linux, or macOS

Install **Python 3.9–3.13**, **Git**, and [Poetry](https://python-poetry.org/docs/#installation). Python 3.12 matches CI. On Debian/Ubuntu, install these dependencies first:

~~~bash
sudo apt-get install python3-dev build-essential libhidapi-hidraw0 mtdev-tools
~~~

On Windows, the `pyquicklz` dependency may need Visual C++ build tools to compile.

~~~bash
git clone https://github.com/prdoring/Carvera_Controller.git
cd Carvera_Controller
poetry install --without ios-dev
poetry run python -m carveracontroller
~~~

### Build for Android

From the checkout, in a prepared Linux build environment:

~~~bash
poetry install --without ios-dev
poetry run python scripts/build.py --os android --version 2.2.0-DEV
~~~

Install the resulting `dist/carveracontroller-community-2.2.0-DEV.apk` on the device. USB connections need USB host support, a data cable or adapter, and device permission.

The [Windows and Android guide](docs/windows-android-development.md#android-build-command) covers build prerequisites, installation, and signing. Back up preferences before replacing an existing app; a different signing key can prevent an in-place update.

## Build a kiosk image

To build from source, see [Raspberry Pi kiosk image](docs/development.md#raspberry-pi-kiosk-image). This requires Git and Docker Desktop with Linux containers.

## Development and support

[Development and packaging](docs/development.md) covers checks, translations, and packaging. Use [this fork’s issue tracker](https://github.com/prdoring/Carvera_Controller/issues) for bugs or requests. For bugs, include your platform, controller revision, machine model, firmware version, and steps to reproduce.

The [community documentation](https://carvera-community.gitbook.io/docs/controller/about) covers shared features. [CONTRIBUTING.md](CONTRIBUTING.md) is the community contribution guide.

Thanks to Makera and the Carvera Community contributors. See [LICENSE](LICENSE), [NOTICE](NOTICE), and [Privacy](PRIVACY.md).
