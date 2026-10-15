# Android touch support audit

Date: October 14, 2026.

Application: Carvera Community Controller, version 2.2.0.

Source reference: release tag `v2.2.0`; checkout commit
`e5623ece10309597d43a708dde35ae41c7854cb8`.

User environment: Android on a Raspberry Pi with a touchscreen. The user
reported difficulty editing text, including backspace failing, and requested
an audit of touch support across the application.

Status: implementation in progress on `android-improvements`; live Android
and machine validation remain outstanding.

## Main findings

Touch support has several demonstrable input-handling defects, along with
mouse-oriented interaction choices and inconsistent Android text entry.
Continuous-jog cancellation is the highest-priority finding. The largest
everyday improvements concern keyboard editing, touch target size, gesture
ownership, and feedback.

The audit covered all 28 custom `on_touch_*` handlers, 264 text-input
declarations in Kivy layouts, Android packaging and startup configuration,
shared widgets, dialogs, lists, splitters, and viewer controls. Relevant touch
implementations were compared with the 2.2.0 release sources. Unrelated USB
changes were present in the working tree during the audit.

Seven problematic behaviors were reproduced by executing source methods with
mocked touch events and dependencies. These checks establish the relevant
callback and state behavior. They do not reproduce Android event delivery,
keyboard behavior, or physical machine motion. No application changes were
made, and the application and machine connection were not started for the
checks. No Android build or full application test suite was run.

The initial audit did not establish the backspace cause. The packaged-device
diagnosis and implementation results appear below.

## Findings and improvements

### 1. Continuous jogging can miss the stop request

Priority: highest. Evidence: confirmed callback defect.

Jog buttons start movement through `on_press` and stop through `on_release`.
Kivy's default `ButtonBehavior` skips `on_release` when the finger lifts outside
the button and `always_release` is false. The affected jog buttons do not
override that behavior.

An isolated check reproduced both paths:

- Press inside and lift inside: `on_press`, then `on_release`.
- Press inside and lift outside: `on_press` only.

This pattern appears in the main controls, probing controls, and CMM jog
controls. It matters when continuous jogging is enabled. The controller's
status-polling path sends keepalives while `continuous_jog_active` is true and
`_continuous_jog_stopping` is false. Missing the stop callback leaves that
state active. The resulting physical machine behavior was not tested.

The Android application pause handler also has no explicit jog cancellation.
Multiple buttons share the same stop operation without tracking which finger
started the active jog.

Improvement:

- Use a dedicated jog touch handler that owns the controlling finger.
- Stop on release anywhere, cancellation, loss of focus, popup closure, and
  application pause.
- Define behavior for a second finger, a disabled control, and lost input.
- Use ordinary completed-tap semantics for other actions.
- Validate the stop behavior on a real machine with continuous jogging enabled.

Sources: [main layout](../carveracontroller/makera.kv),
[probing layout](../carveracontroller/addons/probing/ProbingPopup.kv),
[CMM layout](../carveracontroller/addons/cmm_workbench/ui/CMMWorkbenchPopup.kv),
[Controller.py](../carveracontroller/Controller.py), methods `jog`,
`startContinuousJog`, `stopContinuousJog`, and `viewStatusReport`, and
[main.py](../carveracontroller/main.py), `MakeraApp.on_pause`.
See [Kivy's button release implementation](https://kivy.org/doc/stable/_modules/kivy/uix/behaviors/button.html).

### 2. Touch targets are small, and Android sizing uses screen resolution

Priority: high. Evidence: confirmed configuration and layout issue.

Android startup replaces Kivy's density with a value calculated from screen
width and height. This fits the UI into an approximately 1000 by 550 coordinate
space. Screens with the same pixel resolution receive the same scaling even
when their physical sizes differ.

Examples of declared sizes:

| Control | Size |
| --- | --- |
| G-code and console rows | 20dp high |
| G-code context-menu actions | 26dp high |
| Common text fields | 28–40dp high |
| File-browser rows | 40dp high |
| Splitter handles | 5dp wide |

These are the application's overridden Kivy units. They cannot be assumed to
represent normal Android density-independent measurements. Android recommends
touch targets of at least 48 by 48dp.

Improvement:

- Establish minimum physical touch sizes using Android display density.
- Keep a separate user-adjustable interface scale.
- Increase row heights and spacing, particularly for machine controls, text
  fields, and context-menu actions.
- Enlarge splitter grab areas independently of their visible divider width.
- Let dense forms scroll instead of shrinking all controls to fit.

Sources: [main.py](../carveracontroller/main.py), Android density initialization,
[makera.kv](../carveracontroller/makera.kv), and
[Android touch target guidance](https://developer.android.com/guide/topics/ui/accessibility/views/apps-views).

### 3. Backspace has a plausible keyboard-composition failure path

Priority: high. Evidence: candidate cause requiring Android confirmation.

The Android build pins Kivy 2.3.1. In that version, `TextInput.do_backspace`
returns without deleting when `_ime_composition` contains text: the input
method is expected to handle deletion during composition. Keyboard unbinding
does not explicitly clear that state. A mismatch between composition and focus
provides a credible path to typing working while backspace has no effect.

The application's custom `MDITextInput` keyboard handler does not consume
backspace. Its special handling concerns command submission and history arrows.

Upstream reports describe Android backspace problems after validation or
refocusing. They support investigating the dependency boundary; they do not
establish the cause on this device or prove applicability to the exact build.

Improvement:

- Reproduce the symptom in a minimal field using the packaged configuration.
- Trace key events, composition events, and focus transitions through typing,
  keyboard dismissal, and refocusing.
- Compare the default `null` input type with explicitly configured text and
  numeric fields.
- Select a dependency patch or keyboard configuration only after reproducing
  and confirming the cause.
- Check for double deletion before introducing custom backspace handling.

Sources: [buildozer.spec](../buildozer.spec),
[main.py](../carveracontroller/main.py), `MDITextInput`, and Kivy 2.3.1's
`TextInput.do_backspace` and `_unbind_keyboard` implementations.
Related [upstream backspace report](https://github.com/kivy/kivy/issues/8267).

### 4. Android keyboard behavior is inconsistent across fields

Priority: high. Evidence: confirmed configuration gaps.

The application sets `has_onscreen_keyboard` to true only for iOS. Android
therefore follows the branch that automatically focuses MDI when switching to
the console, potentially opening the keyboard before the user chooses to type.

The layout inventory found:

- 174 text-input declarations inherit their keyboard type.
- 29 facing-wizard fields have numeric filters without an explicit numeric
  keyboard type.
- The 65 CMM numeric fields inherit a shared definition that filters floats but
  does not request a numeric keyboard.
- No field declarations explicitly configure `keyboard_suggestions`.

Inheritance is valid, but these choices have not been made consistently for
Android. Kivy 2.3.1's inherited input type is `null`; absence of an explicit
type does not automatically mean a field requests a predictive text keyboard.

Improvement:

- Apply a shared policy for numbers, filenames, ordinary text, and G-code.
- Ensure numeric entry exposes minus and decimal keys on the tested keyboard.
- Preserve exact G-code text without unwanted correction or capitalization.
- Recognize Android onscreen keyboards and focus fields intentionally.
- Retain existing Kivy selection handles and clipboard support while validating
  their behavior; those facilities are already available.

Sources: [main.py](../carveracontroller/main.py), `has_onscreen_keyboard`,
[makera.kv](../carveracontroller/makera.kv), MDI navigation,
[facing layout](../carveracontroller/addons/facing/FacingWizardPopup.kv), and
[CMM layout](../carveracontroller/addons/cmm_workbench/ui/CMMWorkbenchPopup.kv),
`CMMWorkbenchFieldInput`.

### 5. Delayed select-all can interfere with editing and accumulate callbacks

Priority: medium. Evidence: repeated binding reproduced; cursor interference
needs device testing.

The shared focus helper schedules `select_all()` 100ms after focus. It does not
cancel the action when focus changes or the user starts placing the cursor.
Each call attaches another focus listener. Some popup paths invoke it every
time they open.

Calling the helper three times produced three delayed selection callbacks for
one focus event. Advanced calibration already guards repeated binding, so the
problem is not uniform across all popup implementations.

Improvement:

- Bind once per input widget.
- Cancel delayed selection when focus is lost.
- Avoid overriding an intentional cursor-placement gesture.
- Select the initial value when replacement is appropriate, while allowing
  subsequent taps to edit part of it normally.

Sources: [widget_helpers.py](../carveracontroller/ui/widget_helpers.py),
`bind_auto_select_to_text_input`,
[set-position popups](../carveracontroller/ui/popups/set_position/set_position.py),
`ToolPopup.on_open`, and [main.py](../carveracontroller/main.py),
`OriginPopup.on_open`.

### 6. The 3D viewer does not manage multiple fingers or gesture ownership

Priority: high. Evidence: shared-state corruption reproduced.

Each new touch overwrites the same rotation and pan starting state. In an
isolated check, placing a second finger caused an unmoved first finger to
produce a 20-degree rotation on its next movement event.

Ordinary viewer interactions do not return a handled result or capture the
touch. Movement is processed only while the finger remains inside the viewer.
There is no pinch-distance or two-finger pan calculation.

Improvement:

- Track active fingers individually and give gestures a clear owner.
- Support one-finger orbit, two-finger pan, and pinch zoom where the touchscreen
  and Android input provider support multitouch.
- Retain visible pan and zoom controls for single-touch panels.
- Handle leaving and re-entering the viewer without corrupting the gesture.
- Return a handled result for interactions claimed by the viewer.

Source: [GcodeViewer.py](../carveracontroller/GcodeViewer.py),
`GCodeViewer.on_touch_down`, `on_touch_move`, and `on_touch_up`.

### 7. The playback slider handles unowned finger movements

Priority: medium. Evidence: reproduced.

The custom movement handler calls Kivy's slider handler and then updates the
viewer whenever the touch lies inside the slider. This occurs even when Kivy
rejected the touch because the slider does not own it. An unowned finger
movement updated the viewer and returned a handled result in the check.

Dragging an owned finger outside the slider can also change its underlying
value without running the custom viewer update. The custom `on_value` handler
does not synchronize the viewer, and there is no custom release handler to
perform the final synchronization.

Improvement:

- Update playback only for the captured slider gesture.
- Follow that gesture outside the slider's bounds.
- Synchronize the final position on release.
- Increase the scrubbing target and provide precise step controls.

Source: [main.py](../carveracontroller/main.py), `GcodePlaySlider`.

### 8. Tap, drag, and long-press recognition is unreliable

Priority: medium. Evidence: rapid-drag and returning-drag cases reproduced.

Viewer controls toggle when a touch lasts less than 150ms, regardless of the
distance moved. A quick drag can hide or show the controls, while a stationary
tap lasting slightly longer does nothing.

G-code long presses compare only the starting and ending positions. A finger
can move away, return, and still qualify. State belongs to the row instead of a
particular finger. Long-press actions appear after release rather than when the
hold threshold is reached. Legend-row tap recognition similarly compares the
end position with the start without recording maximum travel.

Improvement:

- Use elapsed time, maximum movement, and finger identity together.
- Cancel pending holds once dragging begins.
- Trigger and show hold feedback when the threshold is reached.
- Provide an always-visible viewer-controls toggle and visible row menu action.
- Standardize gesture thresholds in appropriate display units.

Sources: [main.py](../carveracontroller/main.py), `FloatBox`, `SelectableLabel`,
and `GCodeRow`, and
[GcodeColorSchemePanel.py](../carveracontroller/ui/GcodeColorSchemePanel.py),
`LegendRow`.

### 9. Context-menu dismissal allows the touch to propagate underneath

Priority: medium. Evidence: reproduced propagation behavior.

An outside touch dismisses the G-code context menu and returns false. The
dismissal touch is therefore allowed to reach widgets beneath the menu. Which
underlying action occurs depends on the current layout and event dispatch.

Improvement:

- Consume the dismissal gesture through release.
- Commit ordinary menu actions on a completed tap so sliding away cancels them.
- Keep immediate press handling for controls that require holding.

Sources: [main.py](../carveracontroller/main.py),
`GCodeLineContextMenu.on_touch_down`, and
[makera.kv](../carveracontroller/makera.kv), context-menu bindings.

### 10. File selection and drawing interactions remain mouse-oriented

Priority: medium for file workflows; lower for drawing enhancements.
Evidence: confirmed interaction limitations.

File selection implements Ctrl/Shift range and additive selection. Without
those modifiers, tapping clears the prior selection. Directory navigation and
file activation also rely on double taps.

The CMM sketch already has enlarged feature hit radii, which is useful. It
selects the nearest feature immediately on touch-down and has no touch pan or
zoom handling. Crowded geometry has no explicit choice between overlapping
selection candidates.

Improvement:

- Add a visible file selection mode, checkboxes, and a selected-item count.
- Provide explicit Open, Upload, and Delete actions.
- Make folder navigation usable with single taps.
- Commit row selection after distinguishing a tap from scrolling.
- Add sketch zoom controls and a way to choose overlapping features.

Sources: [main.py](../carveracontroller/main.py),
`SelectableBoxLayout.select_with_desktop_modifiers` and `on_touch_down`,
[LocalFilePicker.kv](../carveracontroller/ui/LocalFilePicker.kv), and
[sketch.py](../carveracontroller/addons/cmm_workbench/ui/sketch.py),
`CMMWorkbenchPreviewSketch.on_touch_down`.

### 11. Help and press feedback need touch equivalents

Priority: medium. Evidence: confirmed design gap.

Tooltips are driven by mouse position. Android retains those hover bindings
without a consistent finger-operated route to the same explanations and
illustrations. Several transparent controls style active and disabled states
without an equally clear pressed state.

Improvement:

- Offer visible information buttons or an explanation panel.
- Keep help activation separate from motion buttons.
- Give immediate visual feedback when a touch is accepted.
- Distinguish accepted input from completion of the requested machine action.

Sources: [Tooltips.py](../carveracontroller/addons/tooltips/Tooltips.py),
[Tooltips.kv](../carveracontroller/addons/tooltips/Tooltips.kv), and
[makera.kv](../carveracontroller/makera.kv), transparent button definitions.

### 12. Keyboard-visible dialogs and Android navigation need a common policy

Priority: medium. Evidence: confirmed implementation gaps; resulting layout
and navigation behavior require device testing.

The application globally uses `Window.softinput_mode = "below_target"`.
Many dialogs combine fixed spacers and small fields without a layout designed
for the space remaining above the keyboard.

There is no consistent application-level Android Back navigation. Many dialogs
disable automatic dismissal, so Back does not naturally close them. Safe-area
handling is implemented for iOS without equivalent Android inset handling.

Improvement:

- Keep the edited field and its confirmation controls reachable above the
  keyboard.
- Define Back behavior for keyboard dismissal, dialogs, unsaved changes, and
  page navigation.
- Account for Android system bars and changing window bounds.
- Test popup layouts with the packaged SDL2 build. Kivy documents that simply
  choosing `resize` does not currently work with SDL2 on Android.

Sources: [main.py](../carveracontroller/main.py), `load_constants`,
`Makera._global_keyboard_keydown`, and `MakeraApp._update_safe_area_padding`,
[makera.kv](../carveracontroller/makera.kv), dialog definitions, and
[Kivy keyboard layout documentation](https://kivy.org/doc/stable/api-kivy.core.window.html#kivy.core.window.WindowBase.softinput_mode).

### 13. UI blocking can make touch and typing feel unreliable

Priority: medium. Evidence: confirmed blocking work; latency was not measured.

Probing settings rewrite their configuration file on every text change,
including intermediate edits. This places storage work on the typing path and
persists partially edited values.

Applying machine settings sleeps for 100ms per setting in the UI callback.
G-code page population and viewer updates also perform substantial work in
scheduled UI callbacks. Some parsing and loading work already runs in workers;
the remaining UI work should be measured individually.

Improvement:

- Keep draft input separate from committed settings.
- Allow incomplete numeric drafts while editing and validate completed values.
- Save after editing or with a short debounce.
- Replace blocking UI sleeps with scheduled steps.
- Profile page creation and viewer updates on the Raspberry Pi.
- Move calculations to workers and limit work applied per frame, keeping
  graphics operations on the appropriate UI thread.

Sources:
[SingleAxisProbeSettings.py](../carveracontroller/addons/probing/operations/SingleAxis/SingleAxisProbeSettings.py),
`setting_changed`,
[ConfigUtils.py](../carveracontroller/addons/probing/operations/ConfigUtils.py),
`save_config`, and [main.py](../carveracontroller/main.py),
`apply_machine_setting_changes`, `load_page`, and `load_gcodes`.

## Reproduced source-level behaviors

These checks extracted the source methods and supplied mock widgets, fingers,
clocks, and application dependencies. They executed without launching Kivy's
application window or connecting to a CNC. The temporary checks were not added
as repository tests.

| Check | Observed result |
| --- | --- |
| Jog button lifted outside its bounds | Press callback fired; release callback did not |
| Unowned finger moved across playback slider | Viewer update fired and movement was consumed |
| Fast viewer drag | Viewer controls toggled despite substantial travel |
| Second finger entered viewer | First finger's rotation origin was overwritten |
| Row drag moved away and returned | Release qualified as a long press |
| Outside context-menu touch | Menu dismissed and handler returned false |
| Focus helper attached three times | One focus event scheduled three select-all callbacks |

## Recommended implementation order

1. Correct continuous-jog release and cancellation, including application
   lifecycle and multiple-finger cases.
2. Stabilize keyboard editing, focus, selection, and numeric entry.
3. Correct viewer, slider, menu, and list gesture ownership.
4. Introduce consistent touch sizing, navigation, help, and feedback.
5. Reduce UI blocking and add Android regression coverage.

## Validation needed for changes

Existing tests include MDI history and desktop screenshot coverage. They do not
establish Android touch, composition, or keyboard correctness.

| Area | Required scenarios |
| --- | --- |
| Jogging | Release inside/outside, slide away, lost touch, multiple fingers, disabled controls, popup closure, background/resume, interrupted connection |
| Text entry | Backspace and held deletion, selection replacement, cursor placement, paste, minus/decimal input, composition, dismissal/refocus, repeated popup openings |
| Keyboard configuration | Default/null, explicit text and number types, configured system and virtual keyboard modes, the user's keyboard app |
| Viewer and slider | One/two fingers, leaving/re-entering bounds, pinch where supported, controls visibility, final slider synchronization |
| Lists and menus | Slow taps, fast drags, long presses, drag away and return, scrolling without actions, menu dismissal without activating underlying widgets |
| Layout | Actual Pi touchscreen, different display scales, keyboard-visible dialogs, Android bars, reachable Apply/Cancel/Stop controls |
| Responsiveness | Typing, settings application, large G-code files, repeated navigation, UI frame stalls on the Pi |

Any change affecting jogging or machine behavior needs validation on a real
C1 or CA1 with the affected feature enabled. Record the machine, effective
configuration, firmware, Android image, keyboard, display, and results. A build
or mock event check does not demonstrate correct machine behavior.

## Notes for later sessions

- Use the packaged-device findings below for the confirmed backspace cause;
  the original composition explanation was a hypothesis.
- The Pi touchscreen delivered two independent contacts. Other Android input
  providers still need their own verification.
- Preserve unrelated working-tree changes and inspect current source before
  editing. This audit is anchored to the 2.2.0 release, and source locations may
  move as other work continues.
- Follow callers and runtime configuration before selecting a fix. Several
  existing controls already use standard Kivy scrolling, selection handles,
  keyboard types, and explicit pan/zoom actions.
- The original findings describe the audited release. The implementation and
  validation results below describe the Android improvements branch.

## Implementation and validation

The main, probing, and CMM jog controls now use one finger-owned handler.
Slide-off beyond the movement tolerance, release anywhere, disabling, focus
loss, application pause, or removing the control requests a stop. Re-entry
requires a fresh press. The existing firmware stop acknowledgement still
prevents starting another continuous jog while stopping.

Shared tap/hold tracking cancels holds after maximum travel and suppresses
release activation after dragging. G-code and console selection uses completed
taps, and context-menu dismissal captures the outside gesture through release.
The Android input bridge preserves cancellation separately from SDL2 release
and keeps the existing launcher activity.

Kivy dispatch tests cover outside release, slide-off/re-entry, a second finger,
disabling, popup removal, lost connection, pending stop, cancelled button
activation, and drag-away/return. Physical machine results are recorded separately
from widget simulation below.

The packaged keyboard diagnostic reproduced missing deletion events after
refocusing explicit text, G-code and numeric fields. The native SDL editor was
empty while Kivy retained its text; composition was empty. The SDL input
connection now emits deletion only for that empty-editor case. Normal Android
composition and deletion keep their existing path. On the Pi, normal text and
G-code reopened and deleted once, signed decimal entry worked, and held deletion
cleared the field. The user repeated the test and confirmed all four fields work.
Two simultaneous touchscreen contacts also reached Kivy independently.

Shared editing policies configure signed/decimal keys and preserve exact G-code
and filename text. Initial numeric selection is bound once and cancelled by
editing or blur. Probe settings retain incomplete drafts without saving them;
preview validates them before generating commands. Valid saves are coalesced.
The existing probe storage location and probe defaults are unchanged.

Viewer fingers now have independent captured state. Finger-count changes rebase
without applying a movement delta. The viewer retains orbit/pan controls and adds
an always-visible Controls toggle. Scrubbing owns one finger, follows release
outside the slider, and synchronizes the selected line. Previous/Next line
buttons provide precise stepping. G-code rows expose their menu button; recycled
rows cancel pending holds. Menu dismissal consumes the outside gesture.

Android file lists use completed single taps for folders and selection. The
remote list exposes selection mode, checkboxes, count and existing Open/Delete
actions; local Open/Upload retain their existing workflow and confirmations.
CMM sketch controls provide zoom/Fit, captured pan/pinch, completed feature
selection and an overlap chooser. Host widget checks cover slider ownership and
outside release, menu dismissal, completed toggles, cancelled holds and
finger-count transitions. The physical CA1 results appear below.

Android sizing now uses display density with a separate interface-size setting;
an explicit old density override migrates to the equivalent scale. Controls and
actionable rows have a minimum 48 Android dp target. Splitter grab areas have a
thin visible divider. Dialogs reserve keyboard space and expose scrolling forms,
wrapping action rows and touch-accessible help. Back dismisses the keyboard
first, then idle dialogs/navigation, and confirms unapplied coordinate edits or
exit. Active operations retain their explicit cancellation controls.

The constrained desktop preview exposed compressed A/Z jog step selectors in
probing. Their fractional height competed with spacer labels. Selectors now use
fixed touch heights inside full-height rows. The probing jog panel stays outside
the form scroll view and is hidden/disabled during keyboard editing. Tests check
selector alignment and parent bounds, in addition to six keyboard-visible forms.
Packaged checks on the Pi also exposed an infinite parent walk when a field
received focus: Kivy's Window is its own parent. The scrolling helper now stops
at Window, and the regression test focuses a real field through the scheduled
reveal callbacks. Facing and CMM help buttons now have explicit Android sizes;
inheriting a wrapping action row's height created a circular sizing dependency.

Machine settings are sent through scheduled callbacks at the existing 100ms
interval. Apply cannot start twice. Disconnect, pause, cancellation or transport
failure retains unsent changes, including newer edits made during a send. The
completion message says settings were sent; it does not claim a firmware
acknowledgement. Probe settings construct the visible tab on a later frame and
reuse it. The other eight settings panels are deferred until needed.

### Coverage of the 13 findings

| Finding | Implementation | Validation and limits |
| --- | --- | --- |
| 1. Continuous jog | Captured owner, permanent slide-off cancellation, lifecycle cleanup, existing stop gate | Real Kivy dispatch covers outside release, re-entry, second finger, disable, popup removal, pause-related cancellation, disconnect and stop acknowledgement. Physical CA1 check is recorded below. |
| 2. Touch sizing | Android density, separate interface scale, 48dp minimum targets, wider splitter grabs, scrolling forms | Pi display density 1.5 gives a 72px target at normal size; constrained host dialog checks cover alignment and keyboard clearance. |
| 3. Backspace | Empty-native-editor fallback for one backward deletion only | Reproduced on the Pi after keyboard dismissal/refocus; normal text, G-code, signed decimals and held deletion passed, including user repetition. Native composition keeps its original path; other IMEs are unverified. |
| 4. Keyboard policy | Shared text/filename/G-code/integer/decimal policies, signed/decimal native flags, intentional focus | Packaged keyboard diagnostic passed; MDI navigation no longer focuses its field automatically. |
| 5. Selection | One cancellable initial selection binding | Tests cover repeated binding, blur and later editing without overriding subsequent selection. Full physical keyboard/IME combinations remain unverified. |
| 6. Viewer | Independent contacts, captured orbit/pan/pinch, count-change rebasing, visible controls toggle | Two simultaneous Pi contacts verified; widget/transform tests cover ownership and rebasing. |
| 7. Playback | Owning finger, outside capture/final synchronization, larger target and line steps | Real-widget dispatch verifies unrelated fingers cannot scrub and outside release synchronizes the final position. |
| 8. Tap/hold | Maximum-travel tracking, Android tolerance/timeout, completed toggles/tab headers, hold suppression | Real widget dispatch covers drag-away/return, cancellation, delayed callbacks and recycled rows. |
| 9. Menu dismissal | Modal dismissal consumes the outside gesture through release | Widget dispatch verifies no underlying activation. |
| 10. Files/CMM | Android single-tap navigation/selection, visible remote selection mode/count/actions; CMM zoom/Fit, captured pan/pinch and overlap chooser | Host tests cover completed selection, capture and chooser; packaged file/CMM layouts checked on the Pi. Desktop selection modifiers retained. |
| 11. Feedback/help | Pressed feedback and touch-accessible existing help | Shared controls and row feedback exercised in widget tests and Pi layout checks; feedback timings below cover a limited injected-touch sample. |
| 12. Keyboard/Back | Native insets/keyboard bridge, scrolling and reserved keyboard space, keyboard-first Back, idle-dialog/navigation/discard/exit policy | Six host dialogs tested above a simulated keyboard. Active machine-operation dialogs keep explicit cancellation. |
| 13. Blocking work | Paced settings sends, valid draft commits/coalesced persistence, deferred probing panels, optional bounded timing recorder | Full tests pass. Pi measurements still show multi-second large-preview stalls; this work does not meet a universal 100ms response guarantee. |

### Pi measurements

The device is a Pi 4 Model B with 8GB RAM, KonstaKANG AOSP 16 build from
June 17, 2025, a 1920x1080 display at density 240, and the existing system IME.
Its TSTP MTouch touchscreen reports independent contacts to the packaged SDL2
provider. Testing used the existing performance governor and USB connection.

The before build was Android package 2.2.0.4 with the earlier performance fixes.
The after code is 2.2.0.8. A temporary, local-only driver opened dialogs, typed
into an unapplied coordinate field and loaded a synthetic preview. It never
started a program, applied coordinates or sent motion. The timing recorder was
identical in both builds. Times below are small practical samples, not a
statistical benchmark.

| Measurement | Before | After |
| --- | ---: | ---: |
| App-side touch feedback, p95, 40 injected touches | 41.9ms | 85.2ms |
| App-side touch feedback, maximum | 4,941ms | 89.6ms |
| Touch samples over 100ms | 1 / 40 | 0 / 40 |
| Event-loop cadence, p95 | 80.3ms | 104.4ms |
| Longest event-loop interval | 6,516ms | 3,028ms |
| Intervals over 100ms | 61 / 1,839 | 122 / 2,259 |
| First probing constructor/open call | 1,963ms | 742ms |
| 100,002-line preview, observed completion | 30.0s | 32.7s |

Touch feedback measures Kivy motion dispatch to the next frame flip; it excludes
hardware, Android input latency and IME-owned key processing. It is not a
measurement of every control or popup becoming usable. The after p95 is higher
even though this sample stays below the 100ms target. Overall event-loop p95 and
stall frequency also increased in this run. Layout/keyboard work and rendering
remain material costs; no overall speedup is claimed from these numbers.

Preview completion includes host polling overhead. Both runs completed loading
with 100,002 lines, 398,207 preview vertices and a 10,000-row text page. This
does not measure machining or establish a preview speedup. Facing and CMM had
already been opened during the final layout inspection, so their subsequent warm
open calls are not compared with the baseline's first construction.

The complete host suite passed **377 tests**, with 15 screenshot comparisons
skipped because their reference images were absent. The locale deprecation
warning is unchanged. Additional dialog regressions were checked after the
device-discovered focus and wrapping-help fixes.

The actual Pi also opened settings, files, probing, facing, CMM and coordinate
dialogs at 125% interface size (90px targets). In the coordinate dialog, the
focused field and confirmation actions remained above the keyboard. One Back
dismissed the keyboard while retaining the dialog; the next closed the dialog.
The normal-size probing selectors were checked visually after correction.

### Machine validation

The connected machine reports **CA1**, firmware **2.2.0c**, `FuncSetting=1`, over
FTDI USB serial `A50285BI`. The downloaded SD-card overlay advertises MD5
`75a1a27b83afac1095a9fd558fa60674` (5,700 bytes). Relevant configured values include
X/Y maximum 3,000mm/min, Z maximum 2,000mm/min, acceleration 150mm/s², and enabled
soft endstops. These are the downloaded user overlay, not a complete dump of
every firmware default or runtime override. No firmware or machine configuration
was changed.

On the normal 2.2.0.8 installation, the user manually tested continuous jogging
on **X and Y at Jog Speed: Max**. They confirmed that sliding clearly off the
button stopped motion, sliding back without lifting did not restart it, touching
another direction with a second finger preserved the original direction, and
releasing the original finger stopped motion. The captured application log
contains the corresponding `$J -c` starts on X/Y without an explicit F value.
No motion was injected remotely. Stop distance/time was not instrumented, and
the firmware's raw `^Y` acknowledgement is consumed rather than written to this
log. Repeated successful fresh starts are consistent with the acknowledgement
gate clearing; they are not a direct capture of each acknowledgement.

Pause/focus loss, popup removal, disabled controls, interrupted connection and
competing keyboard/pendant starts have automated coverage. They were not all
repeated during physical motion on the machine. Z/A jogging, other firmware,
other keyboards and extended thermal/load testing remain unverified. A final
sample recorded 75.958°C, 1.8GHz and `throttled=0x80000`: no active limit in the
low bits, but a historical soft-temperature-limit event. Its timing is unknown;
see the [performance report](raspberry-pi-android-performance.md#android-touch-update).
