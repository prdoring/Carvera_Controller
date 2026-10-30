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

The project uses [Ruff](https://docs.astral.sh/ruff/) (linting), [Mypy](https://mypy-lang.org/) (type checking), [import-linter](https://import-linter.readthedocs.io/) (architectural boundaries), and pytest for the repeatable quality gate. Ruff covers application code, tests, and project-owned Python scripts with rules for syntax/name errors, imports, bug-prone patterns, return consistency, comprehensions, and Python-version-aware modernization. Mypy checks the controller application and shared package modules with core type/name/attribute/call errors enabled, and runs a separate strict check for `carveracontroller/machine/`. Addon packages are linted and tested; package-level mypy does not include them because their Kivy plugin surfaces rely heavily on runtime-bound ids and controller objects. import-linter checks package architecture, including the rule that `machine` stays Kivy-free.

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
python scripts/kiosk.py build --version 1.0.0
~~~

The first build can be slow because it builds ARM software under emulation. Output goes to `dist/kiosk`: the compressed SD image, app bundle, checksums, version information, and a `laptop` folder containing the setup helper and screen-sharing files. The version labels the kiosk build, not the machine firmware.

To follow the [installation instructions](../README.md#install-the-kiosk), use your generated image and open a terminal in `dist/kiosk/laptop`. You do not need a release ZIP when using your own build.

For application-only builds, image details, and validation steps, see the [kiosk guide](https://github.com/prdoring/Carvera_Controller/blob/main/assets/packaging/kiosk/README.md).
