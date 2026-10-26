# Windows and Android development

Use Windows for editing, desktop UI development, and Android device access.
The preferred local Android build route is Docker Desktop, with Windows ADB
installing and launching the APK. A separate Ubuntu installation is optional.

**Status:** The repository has an Android build script and a GitHub Actions
build job. It does not yet have a project-specific Android Docker builder or
a PowerShell build/run wrapper. No local Android build or device installation
has been validated for this setup.

Source reference: community `main`, commit `e5623ec`, checked October 14, 2026.
Recheck the files below when updating this guide.

## Project and source files

The Android app belongs to **Carvera_Controller**. The sibling
**Carvera_Community_Firmware** repository builds the machine firmware.

The controller uses Python and Kivy. Buildozer invokes python-for-android to
package Python, native dependencies, and the UI into an Android APK.

| Area | Source |
| --- | --- |
| Application logic and Android handling | [main.py](../carveracontroller/main.py) |
| Main Kivy layout | [makera.kv](../carveracontroller/makera.kv) |
| Feature-specific UI | [addons](../carveracontroller/addons/) and [ui](../carveracontroller/ui/) |
| Android package configuration | [buildozer.spec](../buildozer.spec) |
| Build entry point | [scripts/build.py](../scripts/build.py) |
| Android launcher and custom recipes | [assets/packaging/android](../assets/packaging/android/) |
| Host dependencies and lockfile | [pyproject.toml](../pyproject.toml) and [poetry.lock](../poetry.lock) |
| CI build | [release.yaml](../.github/workflows/release.yaml) |

## Keep the checkout current

On this machine the checkout is:

```text
C:/Users/prdor/Documents/CodeProjects/Carvera_Controller
```

In PowerShell, inspect local changes and both remotes:

```powershell
Set-Location "C:/Users/prdor/Documents/CodeProjects/Carvera_Controller"
git status --short --branch
git remote -v
git fetch --all --prune
git rev-list --left-right --count HEAD...upstream/main
```

`origin` is the personal fork; `upstream` is the community repository.
A plain `git pull` on the current `main` follows `origin/main`, which can be
older than community `main`.

When on `main`, with local changes accounted for, update using:

```powershell
git merge --ff-only upstream/main
```

If Git reports divergence, inspect the commits before choosing how to reconcile
them. Preserve local edits and untracked CNC files. Updating the local checkout
does not update the GitHub fork.

For contributions, follow [CONTRIBUTING.md](../CONTRIBUTING.md): feature
branches normally start from `upstream/develop` and PRs target `develop`.
Do not merge community `main` into a feature branch just to run this update.

## Windows desktop development

Install Python and Poetry, then run from the controller root:

```powershell
poetry install --without ios-dev
poetry run python -m carveracontroller
```

The declared host Python range is 3.9 through 3.13. CI uses Python 3.12, which is
the preferred reference for a new build environment. The existing Windows
virtual environment was created with Python 3.13; check it before replacing it.

Installing `pyquicklz` may require the Visual C++ build tools.
Translation compilation requires gettext's `msgfmt` on PATH.

Use the desktop app for quick Python and Kivy layout iterations. Android
permissions, storage, touch behavior, and rendering still need device checks.
There is no configured Android live reload; changes require another APK build
and installation.

## Android build command

Run this inside a prepared Linux build environment, from the controller root:

```bash
poetry install --without ios-dev
poetry run python scripts/build.py --os android --version 2.2.0-DEV
```

The expected output is:

```text
dist/carveracontroller-community-2.2.0-DEV.apk
```

The version is an example. Use a version appropriate for the installed app.
The helper builds a debug APK even without its `--debug` option.

When ADB and the device are accessible from the same build environment, the
existing equivalent of a build/install/run/log command is:

```bash
poetry run python scripts/build.py --os android --version 2.2.0-DEV --debug
```

Here `--debug` adds Buildozer's `deploy run logcat` steps. For Docker on
Windows, build the APK in the container and use Windows ADB separately.

Use `scripts/build.py` rather than a bare Buildozer command. It supplies the
root `main.py`, compiles translations, sets version information, applies
`PIP_CONSTRAINT`, and renames the APK. `--automation` automatically accepts
SDK licenses and should be reserved for an intentionally configured build job.

Current Android settings:

| Setting | Value |
| --- | --- |
| Buildozer in the lockfile | 1.5.0 |
| python-for-android reference | `v2026.05.09` |
| Kivy in the APK | 2.3.1 |
| Target Android API | 34 |
| Architectures | `armeabi-v7a`, `arm64-v8a`, `x86_64` |
| Application ID | `org.carveracommunity.carveracontrollercommunity` |
| Python log filter | `*:S python:D` |

Keep the local recipes and [pip constraint](../assets/packaging/android/pip-constraints.txt).
The custom Cython recipe uses 3.1.8 and the constraint keeps pip below 26.
Host Python and the Python interpreter packaged by python-for-android are
separate; do not change the project's host Python range merely because an
Android recipe packages a newer interpreter.

The helper backs up version files under `scripts/backup` and restores them
after success. Failure or interruption can leave version edits and root
`main.py` behind, especially when stopping `--debug` during log streaming.
Inspect the diff and backups before restoring anything; a new build can
overwrite the previous backups.

## Docker route to implement

Docker Desktop is already installed on this machine. Docker runs Linux
containers from PowerShell without requiring a separate Ubuntu distribution;
its WSL backend manages its own Linux environment.

The existing [Dockerfile](../assets/packaging/Docker/Dockerfile) runs the Linux
desktop app through VNC. It is not an Android build image.

A project-specific Android builder should:

- Use a Linux environment with Python 3.12 and Java 17, matching CI's Python
  and Java versions. Include native build prerequisites and gettext.
- Install dependencies from the lockfile, excluding `ios-dev`.
- Copy the current Windows sources, including uncommitted edits, into a Linux
  working directory. Exclude Windows `.venv` and generated output.
- Invoke `scripts/build.py --os android`, preserving the pinned toolchain,
  pip constraint, and custom recipes.
- Retain SDK/NDK and native compilation caches in Docker volumes. Retain the
  debug signing key so subsequent builds can update the same installed app.
- Copy the completed APK to the Windows checkout's `dist` directory.
- Use Windows ADB for installation, launch, and logs, with an explicit device
  serial and checked exit codes.

A possible wrapper interface, **not implemented**, is:

```text
scripts/android.ps1 build -Version 2.2.0-DEV
scripts/android.ps1 run -Version 2.2.0-DEV -Device DEVICE_SERIAL
```

Do not present these as usable commands until the builder and wrapper exist
and have been tested. Avoid selecting an arbitrary latest Buildozer image:
this project needs its Poetry dependencies and packaging helper too.

## Install, launch, and read logs on Windows

On the Android device, enable Developer options and USB debugging. Connect
with a data-capable USB cable and accept the computer authorization prompt.

Windows ADB is installed here on this machine:

```powershell
$androidAdb = Join-Path $env:LOCALAPPDATA "Android/Sdk/platform-tools/adb.exe"
& $androidAdb devices -l
```

The device should appear with state `device`. If it is `unauthorized`, check
the device's authorization prompt. If absent, check the cable, USB debugging,
and the device's Windows USB driver.

Once an APK is in `dist`, replace the serial and APK filename below:

```powershell
$androidDevice = "DEVICE_SERIAL"
$androidApk = "dist/carveracontroller-community-2.2.0-DEV.apk"

& $androidAdb -s $androidDevice install -r $androidApk
# Continue only if installation reports Success.
& $androidAdb -s $androidDevice shell am start -S -n "org.carveracommunity.carveracontrollercommunity/org.kivy.android.PythonActivity"
& $androidAdb -s $androidDevice logcat "python:D" "*:S"
```

The launch command restarts the controller app. Ctrl+C stops log streaming.
Always specify the intended device when multiple devices or emulators exist.

`install -r` requests an update while retaining app data. A different signing
key or a lower version code can prevent installation. Inspect the failure
before acting; do not automatically uninstall the app or erase its settings.
A separate development application ID is an option if an installed release
must be kept alongside development builds.

For a crash with little Python output, also inspect Android errors:

```powershell
& $androidAdb -s $androidDevice logcat "AndroidRuntime:E" "python:D" "*:S"
```

## GitHub Actions alternative

Use GitHub-hosted Linux builds if local Linux containers are unwanted.
Edit on Windows, obtain the APK from an appropriate workflow run, then use
the Windows ADB commands above.

The existing release workflow builds Android on Ubuntu 22.04 with Python 3.12
and Java 17. It triggers on pushes to `develop` and version tags, builds
multiple platforms, and includes publishing jobs. It has no manual
`workflow_dispatch` trigger. A normal feature-branch push does not trigger it.

For development, add a separate manual Android-only workflow before using
`gh workflow run`. Keep release publication out of that workflow. Do not push
a release tag or update `develop` solely to obtain a development APK.

To inspect and download an existing run, use PowerShell:

```powershell
$androidBuildRepo = "prdoring/Carvera_Controller"
gh run list --repo $androidBuildRepo --workflow release.yaml --limit 10 --json databaseId,headSha,headBranch,status,conclusion
$androidBuildRun = Read-Host "Workflow run ID"
gh run view $androidBuildRun --repo $androidBuildRepo
gh run download $androidBuildRun --repo $androidBuildRepo --name android-assets --dir dist
```

Choose the repository and run deliberately. Check that the run's commit matches
the intended sources; a remote build does not include uncommitted local edits.
The `android-assets` artifact has a two-day retention period. When SignPath is
enabled, the build initially uploads `android-unsigned`; `android-assets`
arrives after successful signing.

## Checks for developers and agents

- Read this guide, the README, CONTRIBUTING.md, and any applicable AGENTS.md.
  Confirm the controller checkout, branch, remotes, and local changes.
- Use the requested Windows/Docker workflow. Installing a separate Linux
  distribution is optional and requires an explicit request.
- Recheck the current build script and configuration before changing tool
  versions, paths, or package identifiers. Prefer the project's pinned settings
  over generic latest-version instructions.
- Check device model, Android version, architecture, and serial before device
  work. For machine behavior changes, establish the actual machine, firmware,
  configuration, and affected feature before issuing commands.
- Run the repository's relevant quality checks and tests; verify Android-specific
  changes on the device. An APK build alone does not establish correct machine
  behavior. Record what was actually tested.
- Preserve local files and app data. Do not push, publish releases, or uninstall
  an existing app as an incidental setup step.
- Before starting temporary servers, record existing listeners. Track each
  server or helper started by this chat, its process tree, and listening ports.
  Stop owned temporary servers and verify IPv4 and IPv6 listeners have exited
  before yielding, unless the user explicitly requested they stay running.
  Preserve servers belonging to the user or other chats, including an existing
  ADB server; leave uncertain ownership alone and report it.

For code changes, the current repository checks include:

```powershell
poetry run pre-commit run --all-files
poetry run python -m pytest tests -q
```

## External references

- [Buildozer installation and WSL guidance](https://buildozer.readthedocs.io/en/latest/installation/)
- [Buildozer build/deploy commands](https://buildozer.readthedocs.io/en/latest/quickstart/)
- [Docker Desktop's WSL backend](https://docs.docker.com/desktop/features/wsl/)
- [Android Debug Bridge](https://developer.android.com/tools/adb)
- [GitHub CLI: list runs](https://cli.github.com/manual/gh_run_list)
- [GitHub CLI: download artifacts](https://cli.github.com/manual/gh_run_download)
