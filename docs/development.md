# Development and packaging

Run the commands below from the repository root unless a step says otherwise. For the fork’s features and installation overview, see the [README](../README.md).

## Prerequisites

* Ensure you have [Python](https://www.python.org/downloads/) installed on your system (version 3.9–3.13; Python 3.12 matches CI).
* [Poetry](https://python-poetry.org/) is required for dependency management. Poetry simplifies packaging and simplifies the management of Python dependencies.
* One of the python dependencies [QuickLZ](https://pypi.org/project/pyquicklz/) will be compiled by Poetry when installed. Ensure that you have a compiler that Poetry/Pip can use and the Python headers. On a debian based Linux system this can be accomplished with `sudo apt-get install -y python3-dev build-essential`. On Windows installation of (just) the Visual C++ 14.x compiler is required, this can be accomplished with [MSBuild tools package](https://aka.ms/vs/17/release/vs_BuildTools.exe).
* [Squashfs-tools](https://github.com/plougher/squashfs-tools) is required if building Linux AppImages. On Debian based systems it's provided by the package `squashfs-tools`. This is only required if packaging for linux.
* [linuxdeploy](https://github.com/linuxdeploy/linuxdeploy) is required for building Linux AppImages. These must be installed and available in your PATH before building. You can install them using `scripts/install_linux_prereqs.sh` or by following the instructions on their GitHub page.
* [gettext](https://www.gnu.org/software/gettext/) is required for language file generation. [gettext-iconv-windows](https://mlocati.github.io/articles/gettext-iconv-windows.html) project has a version with Windows packages.
* For building iOS app, you need a working XCode installation as well as the build tool that can be installed with `brew install autoconf automake libtool pkg-config`
* Building the Android app needs a Linux host. The prerequisites can be found here: [buildozer prerequisites](https://buildozer.readthedocs.io/en/latest/installation.html). A script to install them is provided in `scripts/install_android_prereqs.sh`. Be aware that buildozer downloads/installs multiple GB of Android development tooling.

For Windows development and Android device testing, see the [Windows and Android development guide](windows-android-development.md).

## Installing Poetry

Follow the official installation instructions to install Poetry. The simplest method is via the command line:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

or on Windows:

```bash
(Invoke-WebRequest -Uri https://install.python-poetry.org -UseBasicParsing).Content | py -
```

Once installed, make sure Poetry is in your system's PATH so you can run it from any terminal window. Verify the installation by checking the version:

```bash
poetry --version
```

## Setting Up the Development Environment

Once you have Poetry installed, setting up the development environment is straightforward:

1. **Clone the repository**

   ```bash
   git clone https://github.com/prdoring/Carvera_Controller.git
   cd Carvera_Controller
   ```

2. **Install the project dependencies**

   ```bash
   poetry install --without ios-dev
   ```

   For iOS development on macOS, include the ios-dev group by running `poetry install`.

   This command will create a virtual environment (if one doesn't already exist) and install all required dependencies as specified in the `pyproject.toml` file.

3. **Activate the virtual environment** (optional, but useful for running scripts directly)

   ```bash
   poetry env activate
   ```

   This step is usually not necessary since `poetry run <command>` automatically uses the virtual environment, but it can be helpful if you want to run multiple commands without prefixing `poetry run`.

## Running the Project

You can run the Controller software using Poetry's run command without installation. This is handy for iterative development.

```bash
poetry run python -m carveracontroller
```

To run the iOS app, you first need to build its dependencies using the Local Packaging instructions below. The build script will open Xcode for you, or you can open the project manually by finding it in `assets/packaging/ios/carveracontroller-ios`.

## Quality Checks

The project uses [Ruff](https://docs.astral.sh/ruff/) (linting), [Mypy](https://mypy-lang.org/) (type checking), [import-linter](https://import-linter.readthedocs.io/) (architectural boundaries), and pytest for the repeatable quality gate. Ruff covers application code, tests, and project-owned Python scripts with rules for syntax/name errors, imports, bug-prone patterns, return consistency, comprehensions, and Python-version-aware modernization. Mypy starts with the controller application and shared modules, checks imported addon interfaces, and runs a separate strict check for `carveracontroller/machine/`. Its Python 3.9 target matches the oldest supported application runtime. Use the tools from `poetry.lock`; a newer checker can have different runtime support or diagnostics. import-linter checks package architecture, including the rule that `machine` stays Kivy-free.

Run all configured hooks with pre-commit:

```bash
poetry run pre-commit run --all-files
```

To run the same checks automatically on every `git commit`, install the hooks once:

```bash
poetry run pre-commit install
```

Run individual checks with Poetry:

```bash
poetry run ruff check carveracontroller tests scripts
poetry run ruff format --check carveracontroller tests scripts
poetry run mypy carveracontroller --config-file pyproject.toml
poetry run mypy carveracontroller/machine --config-file pyproject.toml --strict
poetry run lint-imports --config pyproject.toml
poetry run python -m pytest tests -q
```

To format checked Python files, run:

```bash
poetry run ruff format carveracontroller tests scripts
```

## Local Packaging

The application is packaged using PyInstaller (except for iOS). This tool converts Python applications into a standalone executable, so it can be run on systems without requiring management of a installed Python interpreter or dependent libraries. An build helper script is configured with Poetry and can be run with:

```bash
poetry run python scripts/build.py --os os --version version [--no-appimage]
```

The options for `os` are windows, macos, linux, pypi, ios or android. If selecting `linux`, an appimage is built by default unless --no-appimage is specified.
For iOS, the project will be open in XCode and needs to be built from there to simplify the signing process.

The value of `version` should be in the format of X.Y.Z e.g., 1.2.3 or v1.2.3.

## Setting up translations

The Carvera Controller UI natively uses the English language, but is capable of displaying other languages as well. Today only English and Simplified Chinese is supported. UI Translations are made using the string mapping file `carveracontroller/locales/messages.pot` and the individual language strings are stored in `carveracontroller/locales/{lang}}/LC_MESSAGES/{lang}.po`. During build the `.po` files are compiled into a binary `.mo` file using the *msgfmt* utility.

If you add or modify any UI text strings you need to update the messages.pot file and individual .po files to account for it. This way translators can help add translations for the new string in the respective .po language files.

Updating the .pot and .po strings, as well as compiling to .mo can be performed by running the following command:

``` bash
poetry run python scripts/update_translations.py
```

This utility scans the python and kivvy code for new strings and updates the mapping files. It does not clear/overwrite previous translations.

## Collected Data & Privacy

See [the privacy page](../PRIVACY.md) for more details.

## Raspberry Pi kiosk image

Use Python 3.11 or newer, Git, and Docker Desktop with Linux containers. Start Docker Desktop, then run:

~~~bash
git clone --branch main https://github.com/prdoring/Carvera_Controller.git Carvera_Controller-kiosk
cd Carvera_Controller-kiosk
python scripts/kiosk.py build --version 1.1.0.dev1
~~~

The first build can be slow because it builds ARM software under emulation.
`dist/kiosk` contains the image, controller bundle, separate System bundle,
administrator-only updater bundle, laptop ZIP/folder and `SHA256SUMS` covering
all five artifacts. Image, controller, System and updater versions are reported
separately; none is the mill firmware version.

Use `build --system-only --version VERSION` for an independent System build and
`build --app-only --version VERSION` for a controller build. Build a new version
rather than replacing an installed one. System releases declare maintenance
protocol compatibility and include recovery UI assets/environment independently
of the active controller.

The [administration guide](kiosk-administration.md) documents provisioning,
existing-card migration, full administration, recovery and updater repair.
Test the laptop ZIP outside the repository, including a path containing spaces.
Access and update changes need Linux account-policy tests and Debian 13/systemd
257 boot tests with separate boot/root filesystems. Physical Pi validation is
still required; simulation does not validate the console, touchscreen or CNC.

The image build emits `image-metadata.json`. The full release workflow combines
that with all desktop packages into `setup-release.json` for Setup's offline
picker. A component build alone does not produce full-release metadata. The
laptop CLI remains available in `dist/kiosk/laptop` for advanced provisioning
and existing-card migration.

For application-only builds, image details, and validation steps, see the [kiosk guide](https://github.com/prdoring/Carvera_Controller/blob/main/assets/packaging/kiosk/README.md).

## Kiosk desktop tools

The independent desktop package is `kioskdesktop/`. It uses Python 3.12, Tk/ttk,
AsyncSSH and PyInstaller, without importing Kivy or controller transports. Its
colors, button artwork and IBM Plex fonts come from the kiosk theme; the bundled
Noto CJK fallback has its own redistribution license.

Build Windows packages natively with Qt 6.9.3/MinGW 13.1 and NSIS 3.13. Build
Linux x64 and ARM64 packages natively in the Debian 12 containers. The publication
workflow contains the exact dependency setup. These are developer prerequisites;
downloaded tools include their runtime and require no Python, Git, Docker or SSH
installation.

```sh
python scripts/kiosk_desktop_assets.py dist/kiosk/desktop-assets/noto
python scripts/kiosk_novnc.py dist/kiosk/novnc-desktop
python scripts/build_kiosk_writer.py --qt PATH_TO_QT --work dist/kiosk/writer-work --output dist/kiosk/writer
```

On Windows, add the matching MinGW and CMake/Ninja tools to the build environment.
The writer builder uses Windows short path aliases where available to avoid a
MinGW resource-preprocessor quoting defect. Otherwise choose a build folder with
no spaces. This restriction does not apply to the installed or portable tools.

Set `RELEASE_VERSION` and `RELEASE_COMMIT` to the version and full source SHA, then
run the native package gate:

```sh
python scripts/kiosk_desktop_check.py --output dist/kiosk/native --writer dist/kiosk/writer
```

Use a fresh output directory for each gate run; existing reports and packages
are preserved.

This checks both frozen executables, actual fonts, packaged server workers,
portable paths containing spaces and Unicode, and Windows per-user installation
and removal. Linux installed/portable checks also run in `Dockerfile.desktop-clean`,
which contains no development tools. Tk requires X11 or XWayland. Review the
captured setup, erase-confirmation and viewer screens beside the kiosk references;
check keyboard focus, enlarged text, resizing and display scaling on each target.

Run the desktop unit tests separately from controller tests when using the minimal
desktop environment. Controller tests require the application's development
dependencies. The disposable Debian 13 boot tests use `Dockerfile.boot-test` and
`tests/boot/kiosk_setup_boot.py`; they exercise real filesystem growth, setup
failure routing and replay without exposing host disks or a network.

Native UAC/polkit approval and denial, alternate-administrator UAC, a real removable
card and the Pi 4 remain physical/manual release checks. Mocks, Xvfb and ARM
emulation do not establish those results. Keep the old card and disconnect the
mill during the new-card hardware check.

## Fork releases

Fresh installations default to English. An explicitly saved supported language
choice is preserved.

Fork release tags use `kiosk-vX.Y.Z`, `kiosk-vX.Y.Z.devN`, or `kiosk-vX.Y.ZrcN`.
Create an explicit tag on a reviewed mainline commit, then dispatch **Kiosk
release** from `main` with that tag and `full` or `app-only` mode. Ordinary pushes
do not publish. Both modes serialize by tag and resolve one immutable commit for
all builds. Only the final publisher has write access. It rechecks the tag,
verifies the exact asset inventory and embedded identities, uploads a complete
draft, and checks downloaded bytes before optional publication. Never reuse a
version or replace published assets. Windows tools are unsigned prereleases;
stable full releases are rejected until signing is implemented.

Full releases include the image, controller/System/updater bundles, laptop CLI,
Windows installers and portable ZIPs, both Linux `.deb` and portable packages,
`setup-release.json`, image metadata, notices and checksums. App-only releases
contain the controller archive, its `.sha256` and versioned bundle metadata.
Changes to the OS, system services or installed maintenance/recovery tools need
separately supplied image or tool downloads; deploying an app bundle cannot
install them.

The shared controller checks published `kiosk-v` releases in this fork, never
community controller versions or inherited tags. Stable builds see stable
releases; development and RC builds also see prereleases. Only a release with
an asset for the installed platform/architecture can light the main update dot.
Kiosk releases also need either the archive's `.sha256` file or a full release's
`SHA256SUMS`. Other platform packages may be attached using the existing build
output names; the app-only workflow does not build them. Numeric Android package
versions remain separate from the canonical controller release version.

Firmware updates retain their own tab marker. The Firmware tab describes the
reported firmware and the CA1/2.2.0c reference setup without certifying every
machine or feature. Controller release numbers do not establish firmware
compatibility. Actual firmware capability checks still determine feature access.
