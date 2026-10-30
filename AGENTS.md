# Instructions for agents

These instructions apply to the entire repository. Read them before running the
application, accessing a device, or making changes.

## Purpose and supported setup

This is Pat's Raspberry Pi touchscreen kiosk fork of the Community Carvera
Controller: `https://github.com/prdoring/Carvera_Controller`. This repository is
the controller application and kiosk image, not the mill's firmware.

The primary target is a Raspberry Pi 4 running the dedicated 64-bit Debian Trixie
image, with the XBONFIRE 10.1-inch 1920 × 1200 touchscreen at approximately 60 Hz.
The image runs Kivy through SDL2 on labwc/Wayland, with Raspberry Pi graphics
drivers and Mesa. It does not use a browser or an Android runtime. Android and
desktop builds remain supported by the shared application; preserve their paths.

Pat's documented machine is a Carvera Air (CA1) using Community Firmware 2.2.0c.
That is a reference setup, not evidence of the machine currently connected.
Carvera (C1) has a factory ATC; Carvera Air does not, although user modifications
exist. Both are Cartesian three-axis mills with an optional rotary A axis.
Confirm the actual model, firmware, accessories, connection and relevant machine
configuration before work depends on them. Bundled defaults do not establish the
effective configuration on a mill, which may include an SD-card overlay.

## Start here

1. Check the repository root, branch, revision, remotes, working-tree changes and
   applicable nested instructions. Preserve existing user edits and other chats'
   work. Never reset, clean, stash, switch branches or overwrite files just to
   make the checkout match an expectation.
2. Read `README.md`, `docs/development.md` and
   `assets/packaging/kiosk/README.md`. For Android-specific work, also read
   `docs/windows-android-development.md`. Consult `CONTRIBUTING.md` and the PR
   template before preparing an upstream contribution.
3. Use this fork's `main` as the default base for new fork work. Verify the current
   remote rather than assuming local `main` is current. Inspect remote files or
   use an isolated checkout when local work must be preserved. Do not silently
   substitute the community repository's `main` or `develop`.
4. Trace the relevant code, callers, configuration and tests. Existing classes,
   old audit documents and screenshots do not establish current runtime behavior.
   If a required helper is missing, check the revision before inventing a replacement.
5. Establish whether the task is local development, read-only device inspection,
   kiosk maintenance or mill operation. Follow the authorization rules below.

Keep edits narrowly tied to the request. Avoid unrelated cleanup, dependency
upgrades, mass formatting and platform rewrites. Use ordinary English in names,
comments and documentation. Update these instructions when a change makes them
inaccurate; do not turn them into a session log or a store of device credentials.

## Device safety and user approval

An SSH connection to the Pi and a controller connection to the mill are different
operations. Opening the mill's USB serial connection toggles DTR and resets the
mill. A serial-port probe, reconnect or baud-rate experiment is therefore not
read-only inspection.

The following permissions apply to agent actions through any route: application
UI, remote desktop, SSH, scripts, serial tools, network commands and test code.
Software checks supplement user approval; they do not replace it.

| Action | Authorization |
| --- | --- |
| Read source, edit local files, build locally, run isolated tests/simulation | Proceed within the requested task. |
| Inspect an identified Pi's existing status, logs and files without changing settings or opening a mill connection | Allowed within the task. Confirm the target and SSH identity first. |
| Export a preferences backup using the supported helper | Allowed within the task; protect its contents and avoid overwriting a local backup. |
| Start screen sharing or operate the live kiosk UI | Obtain explicit approval. Screen sharing can inject input. |
| Enter/leave maintenance, deploy, roll back, restart/stop the controller, reboot/shut down the Pi, or change live kiosk settings | Obtain explicit approval for the target and operation, even if the controller appears disconnected. |
| Connect/reconnect/disconnect the controller from the mill, open a serial port, change baud rate, or send diagnostic commands to the mill | Obtain explicit approval. Never open a second mill connection. |
| Jog, home, probe, calibrate, change tools, operate spindle/laser/vacuum/outputs, start/resume/pause/stop a job, or send G-code/MDI/macros | Obtain explicit approval for the specific operation or bounded test sequence. |
| Change work coordinates, offsets, tool data, motion limits, overrides, machine configuration, firmware, or files on the mill | Obtain explicit approval; describe effects on subsequent operation. |
| Flash/format a card, restore settings, replace credentials, or change network/access configuration | Obtain explicit approval and verify the exact target and recovery path. |

An explicit request to perform a named action can supply its approval. Do not ask
again for the same authorized action while its scope and conditions remain valid.
Approval to diagnose, fix code, build, deploy an app or inspect a screen does not
authorize mill motion or other machine commands. A generic request to test is not
permission to run a physical cutting, probing or spindle test.

Before a physical operation, establish the affected machine, operation, intended
travel/speed or program, tooling/workholding and operator readiness as relevant.
Have the user present at the mill with access to the physical emergency stop.
Ask only for missing facts that affect the operation. Unknown/stale status,
connection loss or a stopped controller must not be interpreted as idle.

Never bypass interlocks, maintenance guards, stale-status checks, firmware or
feature checks, confirmations or operating-system privilege restrictions to
complete a task. Never clear an alarm or resume operation automatically. Do not
retry a timed-out machine command blindly: it may have executed. Stop the test
and establish the actual state with the operator before continuing.

Do not use emergency stop as a routine test or cleanup action. If the user requests
an emergency stop, act on that request promptly through the established target;
do not delay it for another confirmation. Remote software is not a substitute
for the operator's physical emergency stop.

## Connecting to the Pi

Use `scripts/kiosk.py` from a source checkout for supported laptop operations.
From an extracted release laptop folder or `dist/kiosk/laptop`, use `python
kiosk.py` instead and keep its companion files together. All
device commands require an explicit `--host`. The documented example is
`carvera-admin@carvera-pi.local`; it is not an inventory of the user's devices.
Get the actual hostname/IP from trusted session context or Settings → System.

First-time SSH trust requires comparing the host fingerprint with the touchscreen
or another trusted source. Have the user verify it when you cannot. Preserve
strict host-key checking. Do not accept unknown/changed keys automatically,
remove known-host entries to silence errors, scan the LAN for a plausible mill,
or reuse an unrelated device's identity.

After verifying the target, these are the usual inspection commands:

```sh
python scripts/kiosk.py diagnose --host carvera-admin@carvera-pi.local
python scripts/kiosk.py logs --host carvera-admin@carvera-pi.local
python scripts/kiosk.py backup --host carvera-admin@carvera-pi.local preferences.tar.gz
```

Replace example hosts and output paths with verified values. Inspect the reported
app version, controller state, maintenance state, display and renderer before
deciding what needs changing. Diagnostics must use the controller's existing
status; never attach `minicom`, `screen`, pyserial or another controller to the
mill to discover its state. Do not stop the live application to free a serial port.

Keep private keys on the laptop. Do not print, commit or bake passwords, private
keys, provision files or backups into source, images, screenshots or logs.
The `carvera-admin` account has restricted maintenance privileges; do not expand
sudo rights or turn the touchscreen account into root for convenience.

For approved screen sharing, use the documented `screen --host ...` helper and
its laptop requirements. Keep viewer/tunnel listeners on localhost. Finish the
helper normally (Enter) and verify cleanup. Preserve any pre-existing viewer or
screen-sharing service that this chat did not start.

## Building and updating the kiosk

For installation, follow the README's release-download path when the required
assets are published. Verify actual release availability and checksums; a planned
release link is not evidence that an image exists. Git and Docker are needed for
source builds, not for using the downloaded laptop helper. Keep installation
instructions distinct from developer build prerequisites.

Use Python 3.11+ and Docker with Linux containers for the laptop build helper.
App dependencies follow `poetry.lock`. Read the kiosk Dockerfile and image layers
before changing the system SDL2/Kivy build: generic prebuilt Linux Kivy wheels
do not provide the required Wayland support. Preserve the pinned image-builder
version unless changing it is part of the task.

```sh
python scripts/kiosk.py build --version 1.0.0.dev1
python scripts/kiosk.py build --version 1.0.0.dev2 --app-only
```

Use a new version for each deployment; examples are placeholders, not versions
to reuse. Output is in `dist/kiosk`. Record the source revision and whether it was
dirty. An app bundle updates the application, not the OS, kernel, installed
system services or maintenance tools. Inspect image-installed versus bundled
files before claiming that an app-only deployment will deliver a change.

Before requesting deployment approval, complete the local implementation,
appropriate checks and bundle build. Present the exact host, source revision,
bundle/version, checks performed, expected interruption and rollback path.
Do not deploy an unreviewed bundle merely to make a proposal concrete.

For an approved update:

1. Inspect status and export preferences to a distinct laptop backup. Establish
   the current release and previous-release availability.
2. Confirm with the operator that the mill is idle and safe for interruption.
   Enter maintenance using the helper. `--confirm-machine-idle` represents the
   operator's actual confirmation; never add it merely to get past an error.
3. Require a successful maintenance acknowledgement before changing the system.
   Active jobs, jogging, probing, transfers and unknown connected states block
   maintenance. Do not manufacture status files, tokens or acknowledgements.
4. Deploy the versioned bundle using the helper. It verifies checksums, installs
   dependencies offline and requires healthy app startup in maintenance. Check
   the result and logs. A successful file upload alone is not deployment success.
5. On failure, inspect automatic restoration before doing anything else. Use
   approved rollback through the helper if needed. Do not repeatedly restart or
   reconnect the mill. Report the resulting release and any unresolved state.
6. Leave maintenance when the approved work is complete and its state is known.
   Verify that the app remains disconnected; reconnecting the mill requires its
   own authorization. If recovery is incomplete, report it and coordinate the
   safe handoff rather than leaving an unexplained maintenance state.

Command forms, after approval and operator idle confirmation:

```sh
python scripts/kiosk.py maintenance --host carvera-admin@carvera-pi.local enter --confirm-machine-idle
python scripts/kiosk.py deploy --host carvera-admin@carvera-pi.local dist/kiosk/carvera-kiosk-app-1.0.0.dev2.tar.gz
python scripts/kiosk.py maintenance --host carvera-admin@carvera-pi.local leave
```

`rollback --host ...` restores the previous application and its saved preferences;
it is not just a code switch. Maintenance authorization expires after 30 minutes;
use the supported leave/enter sequence with a fresh safety check if it expires.
Do not edit `/opt/carvera/current`, release directories or production preferences
by hand to bypass deployment. Releases live under `/opt/carvera`; application
data lives separately under `/var/lib/carvera`. Preserve user G-code and settings.

System changes use the supported `configure` operations in the kiosk guide.
Wi-Fi changes must be confirmed within 120 seconds or roll back; plan how the
user will find the new address and recover locally before applying them. The
recovery UI has its own environment and must remain usable after a bad app update.

Full OS/kernel changes use a replacement card image. Do not run an ad hoc
distribution upgrade or enable unattended updates on the working kiosk. Flash a
verified spare card and retain the old card for recovery. `prepare-card` writes
to the selected boot partition; verify its image identity and actual drive before
using it. Its temporary provisioning file contains Wi-Fi credentials until first
boot. Never commit it. Kiosk installation does not require reflashing the mill.

## Code structure and development rules

| Area | Main files |
| --- | --- |
| Application lifecycle and existing UI | `carveracontroller/main.py`, `carveracontroller/makera.kv`, `carveracontroller/custom_widgets.py` |
| Commands, machine state and transports | `carveracontroller/Controller.py`, `carveracontroller/CNC.py`, `carveracontroller/USBStream.py`, `carveracontroller/WIFIStream.py`, `carveracontroller/AndroidUSB.py`, `carveracontroller/protocols/` |
| Linux kiosk profile, maintenance and touch | `carveracontroller/runtime_profile.py`, `carveracontroller/kiosk_runtime.py`, `carveracontroller/kiosk_state.py`, `carveracontroller/kiosk_touch.py` |
| Shared touch UI and editing | `carveracontroller/ui/android_layout.py`, `carveracontroller/ui/mobile_*.py`, `carveracontroller/ui/touch.py`, `carveracontroller/ui/number_pad.py`, `carveracontroller/ui/editing.py`, `carveracontroller/ui/scrolling.py` |
| Theme and artwork | `carveracontroller/ui/theme.py`, `carveracontroller/ui/theme.kv`, `carveracontroller/data/theme/`, `carveracontroller/data/fonts/`, artwork scripts in `scripts/` |
| Image, services, deployment and recovery | `scripts/kiosk.py`, `assets/packaging/kiosk/` |
| Hardware-free UI development | `carveracontroller/simulation.py`, `tests/integration/conftest.py` |

Paths in the table are relative to the repository root.
Some files retain Android names while serving both touch platforms. Check runtime
profile selection instead of duplicating them or treating the kiosk as Android.

- Keep the `machine` layer Kivy-free and preserve import-linter's direction:
  UI may depend on machine code, not the reverse.
- Keep blocking network, file preparation and expensive calculations off the Kivy
  event loop. Schedule widget changes on the UI thread. Bound queues, logs and
  background work; clean up threads, callbacks and touch bindings on shutdown.
- Preserve disconnected kiosk startup and the block on automatic connections.
  Maintenance must block touch, keyboard and pendant machine controls while
  retaining emergency-stop access. Never introduce a second transport in a
  maintenance helper.
- Preserve protocol detection, framing, transfers and supported firmware variants.
  Validate actual capabilities and fresh status before enabling a control. Missing
  data must disable dependent actions rather than imply a permissive default.
- Keep units, axis signs, work/machine coordinates and relative/absolute modes
  explicit. A visual direction change must not silently change machine commands.
- Preserve user preferences and deliberately customized colors. Settings migration
  must be limited, repeatable and tested. Import only supported preference data;
  do not loosen archive path, file-type, size, link or checksum restrictions.
- Treat Pi memory, CPU, SD writes, startup time and input latency as constraints.
  Avoid permanent background services, heavy animations and repeated large
  renders. Preserve bounded logging, ModemManager masking, thermal protection and
  stock clock limits. Do not overclock or disable protection to improve a benchmark.

## Design language: Slate Workshop

Extend the established interface. Use `ui/theme.py`, `ui/theme.kv`, shared widgets
and the current fork screenshots as the design references. Reuse theme constants
instead of scattering new color literals through Python and KV files.

| Role | Existing color |
| --- | --- |
| Background / panel / field | `#222829` / `#303A3C` / `#151C1D` |
| Control / border | `#435053` / `#566365` |
| Main / secondary text | `#F0F0E8` / `#B7C3C1` |
| Accent / selection | `#D69963` / `#655343` |
| Danger / error / success | `#A3423E` / `#F18A73` / `#88B59B` |

- Use the bundled IBM Plex Sans for interface text and Plex Mono for numeric and
  code readouts through the existing font helpers. Preserve Unicode/CJK fallback.
  Keep font and icon licenses when adding or regenerating assets.
- Use restrained dark workshop panels, clear borders, consistent spacing and the
  existing corner treatment. Avoid decorative gradients, promotional cards,
  emoji controls and unrelated visual styles. Reuse the established icon family;
  do not replace familiar machine-operation symbols with ambiguous artwork.
- Reserve danger styling for hazardous/destructive actions and errors. Show
  active, pressed, selected, disabled and disconnected states distinctly. Do not
  rely on color alone for machine state, warnings or action meaning.
- Use short, ordinary labels and visible units. Distinguish preview, save/apply
  and machine execution. Confirmations should identify the action and consequence;
  do not make the dangerous action the accidental result of Enter or dismissal.
- Design first for 1920 × 1200 with the kiosk's default density of 1.5 and its
  adjustable interface scale. Use `dp`/`sp` and shared touch-target sizing; do not
  shrink targets below the existing 48 dp baseline to fit more controls. Check
  actual framebuffer geometry, font scaling and enlarged interface settings.
- Keep critical controls, selected field, units, validation message and confirmation
  buttons visible above the docked keyboard/number pad. Forms must scroll where
  necessary. Preserve signed decimal editing, cancel behavior and unsent drafts.
  Selecting history or entering a value must not execute a machine command.
- Touch must work without a mouse, hover or tooltips. Put important actions where
  they can be discovered. A drag/scroll must not become a tap on release. Retain
  gesture ownership and cancel pending actions on lost focus or context changes.
- Jogging has one controlling finger. Leaving the control cancels jogging;
  sliding back must not restart it. Preserve stop/cancel behavior on touch loss,
  disabled/detached controls and connection/state changes. Test multi-touch,
  cancellation and overlays whenever changing input dispatch.
- Keep 1920 × 1080 as the advertised comparison mode, subject to screen support.
  Do not claim other resolutions are supported without implementing and validating
  them. Check desktop and Android layouts affected by shared UI changes.
- Route user-facing strings through the existing translation system and update
  catalogs when changing them (`poetry run python scripts/update_translations.py`).
  Review generated changes; do not discard translations or customized settings.

## Local setup and validation

The shared app supports Python 3.9–3.13; Python 3.12 matches the quality workflow.
Keep shared code compatible with that range. The kiosk image currently installs
aarch64 Python 3.13 bundles; check the image and bundle metadata when changing it.
Use the existing environment and lockfile rather than global package installs.

```sh
poetry install --without ios-dev
poetry run pre-commit run --all-files
poetry run python -m pytest tests -q
```

Run focused tests while developing and the applicable broader checks before
handoff. The hooks cover Ruff checks/formatting, package Mypy, strict machine-layer
Mypy and import-linter. Do not apply a whole-repository formatter to unrelated work.
Linux GUI tests need display/OpenGL dependencies; the quality workflow uses:

```sh
xvfb-run -a -s "-screen 0 1920x1080x24 -nolisten tcp" poetry run python -m pytest tests
```

For manual local UI exploration, set `CARVERA_SIMULATION=1` and a fresh temporary
`KIVY_HOME` before launching `poetry run python -m carveracontroller`. Inspect the
current simulator's setup first; kiosk-profile runs also need temporary data,
runtime and maintenance directories through `CARVERA_DATA_DIR`,
`CARVERA_RUNTIME_DIR` and `CARVERA_MAINT_DIR`. Never point development runs at the
live kiosk's data or normal user settings. The simulator blocks physical
transports and records commands; verify those protections remain installed.
The normal app launch is not an isolated UI test.

For kiosk changes, use the documented container checks:

```sh
docker build -t carvera-kiosk-tests -f assets/packaging/kiosk/Dockerfile.test .
docker run --rm --init --network none carvera-kiosk-tests
docker run --rm --init --network none -e CARVERA_PROFILE=kiosk -e CARVERA_RUNTIME_DIR=/tmp/carvera-run -e CARVERA_MAINT_DIR=/tmp/carvera-maint carvera-kiosk-tests python assets/packaging/kiosk/run_checks.py tests/integration/test_kiosk.py -q
docker run --rm --init --network none -e CARVERA_PROFILE=kiosk carvera-kiosk-tests python assets/packaging/kiosk/run_checks.py tests/integration/test_kiosk_recovery.py -q
docker run --rm --init --network none -e PYTHONPATH=/src carvera-kiosk-tests python assets/packaging/kiosk/headless_check.py
```

Use `tests/unit/test_kiosk_*.py` for laptop/profile/maintenance changes and the
relevant shared touch, keyboard, settings or protocol tests for affected behavior.
Add regression coverage for changed safety guards, parsing, command generation,
migrations and update/recovery failures. Do not refresh screenshot baselines just
to hide a failure; visually inspect the change. Existing integration fixtures
default to 1080p, so their success alone does not validate native 1200p layout.

For UI changes inspect rendered screenshots, keyboard overlays, long labels,
disabled/alarm/disconnected states and enlarged scaling. For physical-device
validation obtain the approval described above. Verify V3D acceleration, actual
resolution/refresh, touch accuracy, keyboard behavior and relevant USB/network
behavior on the Pi. For deployment changes test failed startup, settings
preservation, rollback and recovery. Test safety-relevant machine behavior on the
affected machine with its operator before describing it as validated or ready
for review; if unavailable, state that limitation explicitly.

Compare performance with identical files/actions/settings. Separate Android
1080p comparison results from native Linux 1200p results. Measure load time,
interaction stalls, memory, temperature and throttling with screen sharing closed.
Recorded Android results in `docs/raspberry-pi-android-performance.md` do not prove
Linux kiosk performance. Builds, simulation and virtual displays do not establish
physical stop behavior or CNC safety.

## Temporary processes and final handoff

- Check existing listeners before starting a temporary development, preview, test,
  screen-sharing or helper server, including on port 3000. Choose another port
  when occupied. Track launcher PID/session, children, project and listening ports.
- Before yielding or the final response, stop this chat's temporary servers and
  children unless the user explicitly asked to keep a particular server running.
  Verify their listeners exited with successful IPv4 and IPv6 checks. Stopping
  only the launcher is not proof. Include remote screen services/tunnels you own.
- Never stop user/other-chat processes based only on matching paths or ports.
  If ownership is uncertain, leave them alone and report the uncertainty. An open
  preview is not permission to leave a temporary server running. Do not stop the
  production kiosk controller as cleanup.
- Review every changed line and the complete diff. Exclude credentials, generated
  builds, caches, unrelated edits and temporary plans/logs from the contribution.
  Preserve useful user-requested documentation and intentional artwork assets.
- Report what changed, relevant checks and results, checks not run and why, and
  any remaining hardware validation. After approved device work also report the
  target, resulting app version, connection/maintenance state and recovery outcome.
- Do not claim a build is a functional test or write contributor attestations on
  the user's behalf. Keep any required AI disclosure factual and brief. Follow
  the actual destination's contribution rules; upstream's `develop` convention
  does not change this fork's default base. Do not push, publish or open upstream
  issues/PRs merely because local work is complete.
