# Raspberry Pi Android controller performance

Investigated October 14, 2026 using controller 2.2.0 and the connected Pi.

## Findings

The largest verified device configuration problem was slow CPU frequency
scaling. The `ondemand` governor sampled CPU demand every 6.44 seconds. Short
CPU workloads generally remained at 600 MHz even though the existing maximum
frequency was 1.8 GHz. Selecting the image's supported `performance` governor
improved the median duration of the same short CPU workload from 336 ms to
119 ms, approximately 2.8 times faster. This is a CPU benchmark result, not a
measurement of whole-application speedup.

Before application changes, the original installed controller took approximately
17.6 seconds from the launch command to Kivy starting its main loop, even with
the CPU governor corrected. It built many optional interfaces and repeatedly
attempted failed probing-settings saves during startup. Large G-code files also
caused work on the UI thread.

The application performance changes below are now implemented and installed as
**Carvera Performance Test**. A comparison using the separate test package and
the same saved preferences reduced startup from 19.589 to 13.467 seconds,
approximately 31 percent. This measures application main-loop startup, not
Android boot or the completion of machine connection setup. The probing-settings
storage issue remains deferred at the user's request.

## Device and installed application

| Item | Observed value |
| --- | --- |
| Hardware | Raspberry Pi 4 Model B Rev 1.5, 8 GB RAM |
| Android image | KonstaKANG AOSP 16, built June 17, 2025 |
| Android build | `BP2A.250605.031.A2`, `userdebug` |
| Kernel | `6.12.30-g6e1f4bf8ddb1-v8`, aarch64 |
| Controller | `2.2.0.0`, arm64, debuggable APK |
| Bundled Python | 3.14.2 |
| Kivy | 2.3.1 |
| Application graphics | Broadcom V3D 4.2.14.0, OpenGL ES 3.1, Mesa 25.1.3 |
| Display | 1920 x 1080, 60 Hz, Android density 240 |
| Storage | Android data on `mmcblk0p4`; approximately 10 GB available |
| Available memory before app launch | Approximately 6.1 GiB |
| Connected mill | Carvera Air, model `CA1`, community firmware `2.2.0c` |

The controller's own graphics log confirms hardware acceleration. Android's
SurfaceFlinger renderer agrees. Software rendering and insufficient idle RAM
were not supported by these measurements.

The installed Python version is newer than the host Python range declared in
`pyproject.toml` (`>=3.9,<3.14`). Android's interpreter comes from its separate
python-for-android recipe. This difference is relevant to compatibility;
it was not established as the cause of slow startup.

## CPU configuration and measurements

Original values:

```text
persist.cpufreq.governor = ondemand
scaling_governor = ondemand
scaling_min_freq = 600000 kHz
scaling_max_freq = 1800000 kHz
ondemand/sampling_rate = 6442450 microseconds
ondemand/up_threshold = 95 percent
cpuinfo_transition_latency = 4294967295 nanoseconds
```

The Linux kernel documents `sampling_rate` as the interval between governor
worker invocations, in microseconds. The unusually large reported transition
latency is consistent with the large default sampling interval. The underlying
driver or device-tree reason for that latency value was not investigated.

The benchmark used the application's bundled Python interpreter and five runs
of `sum(i*i for i in range(300000))`, with 0.3 seconds between runs. It did not
open the controller UI or connect to the mill.

| Governor | Median duration | Observed frequency |
| --- | --- | --- |
| `ondemand` | 0.336486 seconds | Usually 600 MHz; 800 MHz in the final sample |
| `performance` | 0.118685 seconds | 1.8 GHz for every sample |

A subsequent 20-second single-core workload maintained 1.8 GHz and reached
71.088 degrees C. Firmware reported `throttled=0x0` afterward. The running
controller later measured approximately 68 degrees C, also with
`throttled=0x0`. These checks do not establish temperatures during prolonged
combined CPU and GPU load. Existing hardware thermal protection was retained.

Use `vcgencmd measure_temp` or the `cpu-thermal` sysfs sensor for CPU
temperature. This image's Android thermal HAL exposed battery and skin
readings around 30 degrees C while the CPU was above 60 degrees C.

## Settings applied

| Setting | Before | After |
| --- | --- | --- |
| `persist.cpufreq.governor` | `ondemand` | `performance` |
| Global `window_animation_scale` | `1.0` | `0` |
| Global `transition_animation_scale` | `1.0` | `0` |
| Global `animator_duration_scale` | Not set | `0` |
| Secure `screensaver_enabled` | `1` | `0` |

The existing 1.8 GHz maximum was retained. The persistent governor setting is
handled by `/vendor/etc/init/hw/init.konstakang.rc`; its active and stored
values were read back successfully. No reboot was performed to test it.

That init file already selects `performance` during Android initialization,
then applies the saved governor after boot completes. Therefore the CPU change
addresses application/runtime response; an improvement in initial Android
boot duration was not established. Retained Android boot statistics reported
`boot_complete=39`, but a fresh power-on measurement was not performed.

Android animations affect system transitions. They do not disable Kivy's own
animations. Controller feature preferences, display resolution, Wi-Fi power
saving, and mill configuration were not changed by this audit.

Existing power settings were suitable for a dedicated controller:

- Battery saver was off.
- Android deep and light device-idle modes were disabled.
- The controller's standby bucket was 5, with background operations allowed.
- Staying awake on AC power was enabled.

Original settings, final measurements, a screenshot, and a restore script were
saved locally under:

```text
C:/Users/prdor/.codex/visualizations/2026/10/14/01a13c63-1a6c-7c50-8bda-d425aba59926/
  pi-controller-settings-before.json
  pi-controller-settings-after.json
  pi-controller-after-settings.png
  restore-pi-controller-settings.ps1
```

The restore script checks the device serial before restoring the five changed
settings. Its syntax was checked; it was not executed.

## Application performance findings

The initial application source matched release `v2.2.0`. The following baseline experiments
used Windows, Python 3.13.5, and Kivy 2.3.1. Their timings must not be presented
as Pi measurements or scaled into predicted Pi timings.

### Startup constructs optional interfaces eagerly

`Makera.__init__` constructs 40 explicit dialogs, menus, and viewer objects.
They expand into approximately 3,500 widgets, including 225 tooltip objects.
Controller, viewer, and pendant settings comprise 75 settings definitions.

The desktop startup profile attributed much of the work to widget construction
and Kivy layout rules. The probing popup accounted for approximately 0.83
seconds of profiled startup. These measurements motivated constructing
substantial optional interfaces on first use, as described below.

Source: [main.py](../carveracontroller/main.py), `Makera.__init__` and the
configuration-panel loaders.

### Probing settings use an unwritable Android path

The original saved Pi log contained 105 errors:

```text
Error saving configuration: [Errno 13] Permission denied: '/data/.kivy/'
```

The error repeated during the measured launch after tuning.
`ConfigUtils.CONFIG_DIR` uses `os.path.expanduser("~/.kivy/")` instead of the
app's working Android configuration directory. Probing settings initialization
calls save operations while default values and text bindings are being set.
This is a confirmed persistence bug. Its individual contribution to startup
duration was not isolated.

Source: [ConfigUtils.py](../carveracontroller/addons/probing/operations/ConfigUtils.py)
and the probing operation settings classes.

### Wi-Fi operations can block the UI thread

Machine discovery schedules a Kivy callback every 0.1 seconds, but its socket
receive has a one-second timeout. An isolated invocation with no response took
1.005 seconds. Startup Wi-Fi availability checks and Wi-Fi connection setup
also execute synchronously from UI callbacks.

USB connection setup already uses a worker thread in this release.

Sources: [WIFIStream.py](../carveracontroller/WIFIStream.py), `MachineDetector`,
and [main.py](../carveracontroller/main.py), connection handlers.

### G-code pages generate unnecessary list notifications

`load_page` appends up to 10,000 individual records to Kivy's observable list.
A desktop experiment observed approximately 10,000 data-change notifications
for one page. Preparing a synthetic page took 184 ms with syntax highlighting
and 54 ms without it, excluding subsequent rendering.

Preparing the records separately and assigning the complete list once is a
candidate improvement. Neither highlighting nor other viewer features were
disabled on the Pi during the audit.

Source: [main.py](../carveracontroller/main.py), `load_page`.

### Geometry work still runs in UI callbacks

G-code parsing runs in a worker, but batches of 10,000 input lines are passed
to UI callbacks for geometry processing. Final geometry preparation traverses
the accumulated vertices, computes distances, constructs meshes, and creates
graphics instructions.

An isolated desktop test using the original geometry definitions took 394 ms
to generate mesh data for 500,000 synthetic vertices, excluding GPU upload and
drawing. Input processing took another 870 ms across the vertex work. Input
line counts and generated vertex counts are different quantities.

Sources: [main.py](../carveracontroller/main.py), `load_gcodes` and its worker
handoff, and [GcodeViewer.py](../carveracontroller/GcodeViewer.py), `MeshManager`.

### Tooltip initialization and event fanout

Startup created 225 tooltip objects and 225 mouse-position subscriptions even
when tooltips were disabled before construction. In a desktop experiment,
mouse-position dispatch took approximately 2 ms per event with tooltips enabled
and 0.16 ms disabled, excluding drawing. Touch-only event behavior on the Pi
was not separately measured.

Source: [Tooltips.py](../carveracontroller/addons/tooltips/Tooltips.py).

### Idle viewer callbacks are cheap

The viewer's 60 Hz callback already returns early for empty or unchanged static
scenes. Ten thousand empty-viewer callbacks took approximately 2.6 ms total in
the desktop experiment. The timer alone was not supported as an explanation
for high idle CPU use.

Preview movement advances per callback rather than elapsed time. Lowering
Max FPS can therefore change simulated preview speed. It was left at 60.

Source: [GcodeViewer.py](../carveracontroller/GcodeViewer.py), `_on_frame_tick`.

### Android packaging

The normal Android build path invokes `buildozer -v android debug`. The
installed APK confirmed the `DEBUGGABLE` flag. A release-build comparison has
not been performed, so its performance impact is unquantified.

Source: [scripts/build.py](../scripts/build.py).

### APK updates can remove settings stored with unpacked application files

Replacing the separate USB test APK caused its unpacked `files/app` directory
to be replaced, including `.kivy/config.ini` and its logs. Its preferences
returned to defaults. Restoring the saved test configuration after that first
launch recovered the settings, and ordinary subsequent launches retained them.
The original installed controller used a different package and was preserved.

The pinned python-for-android SDL2 bootstrap calls
`PythonUtil.unpackAsset(..., "private", app_root_file, true)`. Its cleanup path
recursively deletes the target directory when the packaged private-data version
changes. Persistent settings should live outside the unpacked application
directory, with migration of existing settings. This is a separate persistence
issue discovered during USB testing, not a measured cause of slow interaction.

Sources: python-for-android
[PythonActivity.java](https://github.com/kivy/python-for-android/blob/v2026.05.09/pythonforandroid/bootstraps/sdl2/build/src/main/java/org/kivy/android/PythonActivity.java)
and
[PythonUtil.java](https://github.com/kivy/python-for-android/blob/v2026.05.09/pythonforandroid/bootstraps/common/build/src/main/java/org/kivy/android/PythonUtil.java).

## Recommended application work

1. Fix the probing-settings directory on Android and measure startup again.
   This is a confirmed settings-persistence defect, although its share of the
   startup delay remains unmeasured.
2. Construct optional dialogs and settings interfaces when first opened.
   Widget construction was a substantial startup cost in the desktop profile;
   measure the improvement on the Pi before assigning a speedup estimate.
3. Move discovery and connection socket waits off the UI thread. The current
   one-second discovery timeout can directly freeze a scheduled UI callback.
4. Replace individual G-code page appends with one list assignment, then
   profile geometry processing with representative files on the Pi.

Keep full-application startup, touch response, and file-loading measurements
separate from the short CPU benchmark. A reboot test and prolonged thermal
test are still needed to quantify boot behavior and sustained performance.

## Wi-Fi and USB connection findings

Wi-Fi signal was strong, approximately -41 dBm, at 5 GHz with a 433 Mbps link
rate. An eight-packet ping sample to the idle mill had no packet loss and
averaged approximately 13 ms. Wi-Fi power saving was enabled and left unchanged.

The measured controller launch initially encountered repeated peer resets
while another controller was connected. After the user disconnected that
controller, the Pi connected successfully, received the CA1 model and firmware
version, downloaded the machine configuration with a matching MD5, and showed
`Idle` over Wi-Fi. This was a connection check, not a machining test.

USB had two independently verified blockers:

1. Android enumerated an FT232R USB UART, VID:PID `0403:6001`, but the running
   kernel has `CONFIG_USB_SERIAL_FTDI_SIO` disabled. No `/dev/ttyUSB*` or
   `/dev/ttyACM*` node existed.
2. The installed pySerial 3.5 failed port enumeration under
   `sys.platform == "android"`, raising an unsupported-platform `ImportError`.
   An Android USB serial backend was not installed.

The existing controller discovers desktop-style serial ports and opens them
through pySerial. Native Android USB host access can communicate without the
missing Linux FTDI driver, but requires application changes for discovery,
permission handling, and the serial transport. The follow-up implementation
and its validation are recorded below.

## Native Android USB follow-up

Native USB support was added in [AndroidUSB.py](../carveracontroller/AndroidUSB.py),
with Android discovery in `Utils.py` and transport selection in `USBStream.py`.
It uses `usb-serial-for-android` 3.8.1, compatible with the application's existing
Android API 34 target. Desktop serial access continues through pySerial.
Permission checks happen before switching connections. Incoming USB data is
buffered by a reader thread; checking available bytes does not wait for USB I/O.

Android USB callback proxies and the Java objects that accept those proxies are
constructed on Android's UI thread. Constructing them directly in a Python
worker failed to resolve APK interfaces through JNI. Blocking permission waits
and transport operations remain in the connection worker. This Android thread
requirement is separate from keeping geometry calculations off Kivy's interface
thread.

The build was installed as a separate **Carvera USB Test** application,
package `org.carveracommunity.carveracontrollercommunityusbtest`, preserving
the original controller and its settings. Its preferences were copied from
the original, then set to reconnect by USB. The original controller was stopped
to avoid competing connections.

Verified on this Pi and CA1 at 115200 baud:

- Discovery identified FT232R adapter `0403:6001`, serial `A50285BI`.
- The native driver opened the device without a Linux FTDI serial driver or
  `/dev/ttyUSB` node.
- The controller received the CA1 model, firmware `2.2.0c`, positions, and
  the machine's current `Sleep` status over USB.
- The rebuilt standalone APK automatically connected using the saved USB
  identity on app launch. The temporary source patch used during debugging
  was removed before this check; only the APK's packaged module remained.
- All 308 unit tests passed, including binary buffering, driver write errors,
  discovery/reconnect identity, and permission grant/denial/timeout cases.
  Ruff and the Git whitespace check passed.

This image's existing `android:bool/config_disableUsbPermissionDialogs`
resource was `true`; access was already allowed and no permission prompt was
displayed. That policy was not changed. Permission-prompt behavior on other
Android images still needs device testing.

The mill entered sleep before USB validation. Its reset confirmation was left
untouched. No motion, homing, job execution, or wake/reset command was sent.
Configuration/file transfers, higher baud rates, physical cable removal, and
C1 hardware were not validated in this follow-up. USB status and identity
communication are verified; this is not a complete machining validation.

The USB validation arm64 debug APK is saved alongside the measurement artifacts as
`controller-2.2.0-android-usb-test.apk` (51,759,866 bytes).
Its SHA-256 is:

```text
d9b441a94c33d5dfd17ed98a16828bc840c6a2eb03ee81600db5c779a70aca66
```

Original-app backups in that same local directory are
`controller-original-2.2.0.apk` and `controller-original-app-data.tar`.
The final screenshot is `pi-usb-final-connected.png`.

## Application performance changes

The performance build retains native Android USB support and changes four
application modules: `main.py`, `WIFIStream.py`, `GcodeViewer.py`, and
`addons/tooltips/Tooltips.py`.

### Work moved out of the interface thread

Wi-Fi discovery now uses a nonblocking UDP socket. Each scheduled check reads
only available packets, handles malformed announcements, and limits the number
processed per frame. The three-second discovery period uses a monotonic clock.
Closing or reopening the menu releases the discovery socket and scheduled check.
An empty network no longer produces a one-second socket wait in the interface.

Wi-Fi connection setup and protocol detection now run in a worker. Results,
preferences, messages, and status updates return through Kivy's clock. A shared
connection-in-progress check prevents overlapping Wi-Fi and USB attempts. The
extra preliminary TCP availability connection was removed; the actual connection
attempt determines success.

The G-code parser's worker now also prepares preview vertices, rapid/feed
bridges, bounds, normalized geometry, distances, mesh chunks, and color ranges.
The interface receives the completed data and creates the Kivy graphics
instructions. Run-time estimates and legend duration totals are computed in a
worker too. Progress updates are limited to roughly one per percentage point on
large files. Clearing or replacing a preview invalidates results from older time
estimate workers.

G-code text pages are highlighted in a worker and installed as one list update,
replacing up to 10,000 observable list appends. Generation checks discard stale
page results. File line counts and the loaded-tool list are assigned on the
interface thread. Waiting for a progress update checks cancellation and shutdown
rather than waiting indefinitely.

### Startup construction

The probing, facing, and advanced-calibration dialogs are constructed when first
opened and reused afterward. Probing initialization still uses its existing
settings and storage behavior; the storage error was not repaired or suppressed.
The first opening pays the dialog's construction cost.

Controller, viewer, and pendant settings defaults are still loaded immediately,
but their widgets are created when settings open or machine configuration needs
its panels. This retains the existing tab order. Machine-configuration panel
construction itself remains synchronous.

Tooltip content is constructed on its first valid hover. Disabled tooltips have
no mouse-position subscription. Turning tooltips off or moving away cancels a
pending display. Text, images, and generated textures continue to support updates
before the first hover.

### Pi startup comparison

Both builds used the test package, identical saved preferences, USB reconnect,
the performance governor, and the existing Android installation. Each measurement
stopped the application process and launched it again. Android was already
running; storage caches were not cleared. Times use device monotonic logcat
timestamps from immediately before launch to `Start application main loop`.

| Build | Launch to main loop |
| --- | ---: |
| USB test before application performance changes | 19.589 s |
| First performance build, first repeat | 13.518 s |
| First performance build, second repeat | 13.533 s |
| Final performance build, code 20203 | 13.467 s |

The final result is 6.122 seconds shorter, approximately 31 percent. There was
one baseline run and three subsequent performance runs, including two builds;
this is a small practical sample, not a statistical performance guarantee.
The original application's earlier 17.6-second result is a separate observation
and was not used as this comparison's baseline.

Connection setup continues after the main loop starts. In the final launch,
protocol selection was logged approximately 19.8 seconds after launch and CA1
model/firmware information approximately 25.7 seconds after launch. The
13.467-second measurement does not imply that all connection metadata was ready
at that time.

### Desktop preview comparison

The saved before-change source and final source were run sequentially on the
same Windows host with Python 3.13.5 and Kivy 2.3.1, with mocked hardware. The
synthetic input contained 100,002 lines and generated 398,207 preview vertices.
These timings are desktop measurements, not Pi results.

| Measurement | Before | After |
| --- | ---: | ---: |
| Live widgets after startup, deduplicated by widget ID | 3,544 | 1,298 |
| Tooltip content objects at startup | 225 | 0 |
| Mouse-position observers with tooltips enabled | 225 | 83 |
| Total interface time in geometry/progress callbacks | 2.613 s | 0.134 s |
| Longest geometry/progress callback | 637 ms | 134 ms |
| Text-page request callback | 189 ms | 12 ms |
| Installing the prepared text-page list | Included above | 0.36 ms |
| Longest legend refresh | 304 ms | 0.062 ms |
| Median event-loop iteration during loading | 117 ms | 31 ms |
| Event-loop iterations exceeding 100 ms | 12 | 2 |
| Longest event-loop iteration | 651 ms | 355 ms |
| Preview completion including time estimate | 3.717 s | 2.781 s |

Both runs produced the same vertex count, normalized path distance
`998.0115891208441`, and estimated duration `3982.066240626284` seconds.
That confirms equivalence for this input; it is not a validation of every
G-code dialect or machine operation. The normalized distance is an internal
preview quantity, not the physical path length in millimeters.

Large previews still have a noticeable final frame. Graphics instruction
creation and rendering remain on the interface thread; moving CPU preparation
to a worker does not eliminate graphics upload or drawing costs. The remaining
355 ms maximum was observed at the event-loop level; its full cost was not
separately attributed. The Pi's large-file preview timing was not measured.

### Validation and installed result

The complete suite passed **328 tests**: 317 unit tests and 11 performance
integration tests. Fifteen visual-regression comparisons were skipped because
their reference screenshots were absent. The run reported a locale deprecation
warning. Ruff and the Git whitespace check passed.

The added tests cover nonblocking discovery, malformed packets, repeated scans,
packet floods, path geometry and mesh boundaries, legend totals, worker/interface
thread separation, overlapping connection attempts, lazy dialogs and tooltips,
batched page updates, and rejection of stale page/time-estimate results. The
optional dialogs were opened and reused against mocked hardware.

On the actual Pi, the final APK started, automatically reconnected over native
USB, selected the Makera protocol, and received CA1 firmware `2.2.0c`. Its screen
showed `Sleep` and `USB`. No Python error or traceback appeared in the captured
final process log. The original controller remained stopped. The reset
confirmation was left untouched, and no motion, homing, or machining test was
performed.

The governor remained `performance`. The final temperature sample was 75 degrees
C after repeated launches, with `throttled=0x0`. Prolonged combined CPU/GPU
thermal behavior is still unverified. Android boot time was not remeasured.
The frame limit remains 60; no release-build speedup is claimed.

The updated test app is labeled **Carvera Performance Test** and retains package
`org.carveracommunity.carveracontrollercommunityusbtest`, version code `20203`.
The original controller's package and data were preserved. Its test-app
preferences were restored after the Android bootstrap replaced the unpacked
application directory during the APK update.

The final APK is `controller-2.2.0-android-performance-test.apk`, 51,751,918 bytes,
saved in the local measurement directory listed above. SHA-256:

```text
2b43a81c4b6df1ccd4826abfb07619a0c065d80dd870c70f1c25483bd243ad18
```

Supporting local files include `performance-final-startup.json`,
`performance-desktop-before.json`, `performance-desktop-after.json`,
`performance-final-tests.log`, `performance-final-pi-validation.json`,
`performance-final-pi-log.txt`, and `performance-final-pi.png`.

## References

- [Linux CPU frequency scaling](https://docs.kernel.org/admin-guide/pm/cpufreq.html)
- [Android USB host API](https://developer.android.com/develop/connectivity/usb/host)
- [Android startup analysis](https://developer.android.com/topic/performance/appstartup/analysis-optimization)
- [Android rendering measurement limitations](https://developer.android.com/topic/performance/issues/render)
- [KonstaKANG AOSP 16 for Pi 4](https://konstakang.com/devices/rpi4/AOSP16/)

The KonstaKANG page now describes a newer image than the one installed on the
Pi. Installed build and kernel details above came from the device itself.
