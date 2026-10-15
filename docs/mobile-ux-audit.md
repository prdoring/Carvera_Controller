# Mobile and small-touchscreen UX audit

Date: October 14, 2026.

Application: Carvera Community Controller 2.2.0.

Source reference: `v2.2.0`, with checkout base
`e5623ece10309597d43a708dde35ae41c7854cb8`. The main layout, probing, facing,
CMM layouts, and custom settings widgets matched the release sources.
Unrelated USB work was present in the checkout and was preserved.

Related report: [Android touch support audit](android-touch-audit.md).

Status: audit complete. UI implementation, live mobile testing, and physical
machine validation remain outstanding.

## Main conclusion

The application scales a desktop interface to fit the display. It rarely
changes the arrangement or amount of information shown as usable space
decreases. This keeps many controls on screen at the cost of readable text,
clear choices, and room to complete a task.

The most important improvements are:

1. Keep setup options and motion-related choices readable and reachable.
2. Adapt navigation and panel arrangements to available space.
3. Provide mobile layouts for files, job setup, probing, CMM, and facing.
4. Standardize dialogs, editing, validation, and progress feedback.
5. Respect text scaling and preserve useful machine context during workflows.

Some problems are visible at the application's default Android scale. Others
appear when enlarging the interface for readability. Increasing the UI scale
alone does not solve the underlying layout constraints.

## Scope and evidence

This report covers layout, navigation, information hierarchy, readability,
task completion, editing, recovery, and platform differences. The separate
touch report documents pointer ownership, jogging release, keyboard
composition, and gesture defects in more detail.

The source inventory covered all 23 Kivy layout files, their 116 widget rules,
Python-built dialogs, shared widgets, configuration schemas, and Android/iOS
packaging. Representative local renders captured 36 distinct views. Coverage
below distinguishes rendered examples from source-only variants.

Rendering used the current Kivy widgets in a hidden local desktop process.
Background Python workers and network connections were disabled, reconnect
was disabled, and application settings were isolated to temporary directories.
Dialogs were opened directly with disconnected or synthetic data. No motion,
transfer, update, or connection action was invoked.

The Raspberry Pi, its Android connection, its application, and its settings
were not accessed or changed. Another session was working on that device.

The principal comparison was an 800 by 480 framebuffer with Kivy density 0.8,
which matches the Android startup density formula for an 800 by 480 display.
A density-1.0 comparison examined the consequences of a larger UI scale.
Windows display scaling was accounted for to capture the requested framebuffer
dimensions. These are local layout renders, not screenshots from an Android
APK. Native keyboards, permission screens, mobile lifecycle, actual font
preferences, and device input were not tested.

Existing documentation screenshots showing older releases were inspected for
context but were not used as evidence of the current UI.

## Screen coverage

**R** means a representative current widget layout was rendered and inspected.
It does not mean every state, tab, or platform branch was exercised.
**S** means source inspection, including variants of a shared rendered layout.

| Screen or surface | Coverage | Main mobile improvement |
| --- | --- | --- |
| Application status bar and bottom action bar | R + S | Prioritize essential values, explain coordinate modes, and keep status readable |
| Main navigation menu and side page switch | R + S | Visible destination names and current-page indication |
| Manual control and jog controls | R + S | Compact arrangement with clear jog mode, step, speed, and separated actions |
| Connection/status menus, Wi-Fi and USB selection | S | Explicit connection state, labeled choices, and recovery guidance |
| X/Y/Z/A menus | S | Bounded action sheets with units and clear consequences |
| Coordinate-system dropdown | S | Explicit active workspace and readable activation/edit actions |
| Feed, spindle, laser, tool and collet menus | S | Readable overrides, units, distinct actions, and capability-aware content |
| File/viewer page | R initial + S loaded state | One useful pane at a time on compact layouts; clear preview-versus-run context |
| MDI console | R + S | A usable editor above the keyboard, visible send/history controls |
| Remote file browser | R + S | Fewer simultaneous toolbar actions, selection mode, metadata beneath names |
| Local file browser | R + S | Explain View, Upload, and Upload and Select; simplify path navigation |
| Local load/save picker and directory shortcuts | S | Mobile file import/export, bounded breadcrumbs, keyboard-aware save controls |
| Config and Run / Margin / ZProbe / Leveling | R representative + S variants | Scrollable or staged setup, readable review, reachable options |
| Origin configuration | R + S | Short vertical choices with explicit coordinate context |
| Z-probe and XYZ-probe dialogs | R + S | Legible numeric entry and clear probe-direction/context labels |
| Auto-level configuration | R + S | Bounded content; grid and offsets must stay inside the dialog |
| Set X/Y/Z/A, Move A, Set Tool, Change Tool | R Set X/Set Tool + S variants | Shared numeric editor with units, validation and explicit action names |
| WCS settings | R + S | Workspace list/detail editing; visible validation and activation semantics |
| Rotation dialog | R + S | Clearly labeled degrees, reference frame, and completed-value validation |
| Probing: Outside Corners, Inside Corners, Single Axis, Bore/Pocket, Boss/Block, Angle, ProbeTip, Calibration, 4th Axis | R initial tab + S all tabs | Discoverable operation chooser and readable parameters; preserve feature restrictions |
| Probe preview/execution console | R + S | Operation summary, readable output, persistent Halt and progress |
| Advanced calibration | R + S | Readable purpose, numeric fields, and a clear Run Calibration action |
| CMM: Manual, Touch, Bore, Boss, Corner in, Corner out, Angle | R Manual + S all tabs | Separate capture, preview, and construction on compact displays |
| CMM jog overlay | R + S | Preserve width bounding; cap height and retain reliable motion cancellation |
| CMM feature rows, rename, construction and exports | S | Feature detail actions, disambiguation, visible save state, platform export parity |
| Facing: Stock, Cutting, Z probe grid, Tool / Misc. | R Stock + S all tabs | Step-based entry, concise help, review on demand, visible generation state |
| Facing presets and G-code output menus | S | Preserve existing bounded dialogs; clarify output destination and next step |
| Diagnostics | R + S | Grouped outputs with readable labels, state and reasons for disabled controls |
| Settings: Controller, G-Code Viewer, Pendant, Machine Basic/Advanced/Restore/Backup | R initial Controller + S other categories | Compact category selection, search, readable value editors, mobile availability |
| Color picker and macro editors | S; settings-row layout R | Prevent value/action overlap; provide simple colors and keyboard-aware G-code editing |
| Pendant/gamepad configuration and permission error | R gamepad + S variants | Larger binding rows, explicit listening state, clear save/cancel and recovery |
| Generic input, manual Wi-Fi, password and language dialogs | R representative + S callers | Full-width entry, field purpose, password controls and keyboard-aware actions |
| Confirmation, unlock and probe-selection dialogs | R + S | Fully readable choices and explicit consequences |
| Wireless probe pairing | R + S | Readable state/countdown; preserve C1-only navigation condition |
| Message, progress and reconnection dialogs | R + S | Scrollable details, clear progress/cancel state, recovery action |
| Controller/firmware updates and compatibility warnings | R update tabs + S dynamic warnings | Explain platform restrictions and distinguish checking, download and installation |
| Camera panel, image adjustments and legend overlays | S | Separate from the compact viewer; preserve capability gating |
| `SettingPage` placeholder | S | Label-only legacy page; actual Settings navigation opens `ConfigPopup` |

Rendered conditional dialogs are examples of layout, not proof that a feature
is supported or reachable on a particular machine. Preserve C1/CA1 differences,
reported ATC and rotary capabilities, firmware requirements, and camera
availability. An Air with user-installed hardware must follow its actual
configuration rather than assumptions based only on its model name.

## Prioritized findings

### UX-01: Use layout changes as space decreases

Priority: high. Evidence: source and renders.

Android startup replaces Kivy density using screen width and height, fitting a
roughly 1000 by 550 layout. iPhone startup has a similar scaling path. Most
screens retain the same columns, tabs, and toolbar actions. Proportional sizes,
scrolling, and a bounded CMM jog width exist, but there is no shared policy
that changes the main arrangements for compact windows.

Introduce compact, medium, and expanded arrangements based on usable window
space and readable control sizes. Compact layouts should usually present one
main task pane; larger layouts can retain simultaneous views. Handle short
landscape windows as well as narrow widths. Use real display units rather than
the overridden density to classify space.

Android and the checked iOS packaging declare landscape orientations. Keep
landscape kiosk use working. Portrait support needs an explicit product
decision and a corresponding layout before enabling rotation.

Sources: [main.py](../carveracontroller/main.py), startup density handling;
[makera.kv](../carveracontroller/makera.kv);
[buildozer.spec](../buildozer.spec);
[iOS orientation configuration](../assets/packaging/ios/carveracontroller-ios/carveracontroller-Info.plist).
Design reference: [Android adaptive navigation](https://developer.android.com/develop/ui/views/layout/build-responsive-navigation).

### UX-02: The status bar cannot simply grow for readability

Priority: high. Evidence: rendered comparison and source.

The top bar keeps many status cells in one row. `TopDataView` has a 90dp minimum
width; the row also contains gaps and the menu button. At 800 by 480 with
density 1.0, cells overflow the right edge and the menu is lost. At density 0.8,
the row fits by displaying very small secondary values.

Work coordinates are the main values and machine coordinates are the secondary
values, but the distinction is not labeled in the compact cells. Important
information should remain understandable without remembering the order.

Keep connection/state and the most useful coordinates visible. Move secondary
values and overrides to a labeled detail panel or additional row. Clearly label
Work and Machine coordinates, units, the active WCS, and applicable rotation.
Reserve navigation space rather than giving it whatever remains.

Sources: [makera.kv](../carveracontroller/makera.kv), `TopDataView` and `TopBar`;
[main.py](../carveracontroller/main.py), status updates.
Evidence: [default scale](mobile-ux-audit-images/control-default.png),
[larger scale](mobile-ux-audit-images/control-larger-scale.png).

### UX-03: Primary navigation depends on unlabeled icons and an arrow

Priority: high. Evidence: rendered and source.

The function menu renders as a vertical strip of icons. Most entries have an
empty `text` value and explain their destination through a hover tooltip.
The page switch is a side button labeled only `<` or `>`. It also occupies
content space while providing no destination name or selected-page indication.

Provide visible navigation labels such as Control, Files and More, with a clear
current destination. Present secondary tools in a labeled menu. Separate page
navigation from job execution controls so both remain understandable.
Centralize Back and dialog navigation while preserving draft input and scroll
position. Pointer and Android Back issues are also covered by the touch audit.

Sources: [makera.kv](../carveracontroller/makera.kv), `FuncDropDown`, `IconButton`
and the side page-switch button.
Evidence: [navigation menu](mobile-ux-audit-images/navigation-menu.png).

### UX-04: The control screen uses space unevenly

Priority: medium. Evidence: rendered and source.

Large axis-control areas surround a much denser central group containing
macros, machine actions, tool access and jog configuration. Percentage-sized
spacers coexist with minimum-height groups. Enlarging the UI can push the
central actions behind the status bar while the axis panels remain visible.

Create a compact control layout with an intentional balance between axis
buttons and settings. Keep jog mode, step, speed and active input source close
to the controls they affect. Group setup, machine-state actions and custom
macros separately. Explain why disabled actions are unavailable rather than
requiring users to infer the machine state or feature restriction.

Source: [makera.kv](../carveracontroller/makera.kv), `ControlPage`.

### UX-05: Job setup options overflow before the user can review them

Priority: high. Evidence: rendered and source.

Config and Run reserves a fixed 200dp column beside the workspace illustration.
Its many fixed-height sections have no surrounding scroll container. In the
800 by 480, density-0.8 render, the column extends above the dialog and beyond
the screen. Auto-level configuration also renders content beyond its nominal
dialog bounds.

All relevant settings must be reachable before committing the operation. Use a
scrollable setup body or staged steps with a final review. Present the selected
file, origin/WCS, enabled margin/probing/leveling operations, relevant tool and
resume line together. Treat the illustration as expandable supporting content
on compact displays. Keep the action footer inside the available window.

Sources: [makera.kv](../carveracontroller/makera.kv), `CoordPopup`,
`AutoLevelPopup`, and related origin/probe configuration;
[main.py](../carveracontroller/main.py), corresponding configuration classes.
Evidence: [job setup](mobile-ux-audit-images/job-setup.png),
[auto-level](mobile-ux-audit-images/auto-level.png).

### UX-06: Different motion choices have overlapping labels

Priority: high. Evidence: rendered at the default-equivalent scale.

The unlock dialog places Cancel, Unlock and Stay in Position, and Unlock and
Move to Safe Z in one row inside a half-width dialog. The latter labels overlap
and become hard to distinguish. Probe selection similarly places long tool
choices in one row, with text spilling into adjacent buttons.

Use vertically arranged, full-width choices with wrapping labels and a short
explanation of the effect. Name the consequential action explicitly. Keep
Cancel separate and consistently positioned. Apply the same principle to
tool-change, clearing, reset, restore and resume confirmations.

Sources: [makera.kv](../carveracontroller/makera.kv), `UnlockPopup` and
`SelectAndCalibrateProbePopup`.
Evidence: [unlock](mobile-ux-audit-images/unlock.png),
[probe selection](mobile-ux-audit-images/select-probe.png).

### UX-07: File workflows carry too many desktop controls at once

Priority: high. Evidence: rendered and source.

The remote browser puts location, Rename, Delete, New Folder and Upload File in
one fixed-width toolbar. The local browser simultaneously presents View,
Upload, Upload and Select, and Close. Both retain separate date/size columns
and breadcrumb/search rows. Long names and paths compete with these controls.

Use readable filename rows with secondary metadata underneath on compact
layouts. Move less common actions to a labeled overflow menu. Show a clear
selection mode and selected-item count. Shorten breadcrumbs visually while
preserving access to the complete path.

Clarify whether a file is on this device or on the mill, whether it is preview
only, and what is selected for execution. Keep the existing Upload and Select
workflow, but make its purpose and next step obvious. An empty list should
distinguish no files from loading, filtering, disconnection or an access failure.

Sources: [makera.kv](../carveracontroller/makera.kv), `FilePopup`;
[main.py](../carveracontroller/main.py), local/remote file selection and transfer.
Evidence: [remote browser](mobile-ux-audit-images/remote-files.png),
[local browser](mobile-ux-audit-images/local-files.png).

### UX-08: Preview, console and overlays need compact alternatives

Priority: medium. Evidence: initial page rendered; loaded states source-inspected.

The File page keeps a list/console pane beside the viewer, with a narrow
splitter. Viewer controls, a fixed-width legend, and conditional camera
controls can occupy additional space. Displaying all of these together reduces
the useful area for each task.

Allow compact users to choose Preview, Lines or Console, preserving their
position between views. Keep a visible way to show viewer controls. Move the
legend and camera adjustments into an expandable panel when space is limited.
Retain the existing split view and resizable panes for larger windows.

The camera is conditional on detected support. Do not infer its availability
on the user's C1 or CA1 from the existence of the panel. Loaded toolpaths,
legends and camera streams need later device validation.

Sources: [makera.kv](../carveracontroller/makera.kv), `FilePage`;
[GcodeColorSchemePanel.kv](../carveracontroller/ui/GcodeColorSchemePanel.kv);
[CameraControls.kv](../carveracontroller/addons/camera/CameraControls.kv).

### UX-09: MDI needs a mobile editing workflow

Priority: medium. Evidence: rendered and source; native keyboard untested.

The console editor is a small part of the split File page. Its hint advertises
Control+Enter, while history navigation relies on arrow keys. A Send button
exists, but the surrounding layout offers limited room for a software keyboard
and multiline commands.

Provide an expandable editor that remains useful above the keyboard, a visible
Send action and touch-accessible history. Preserve drafts when moving between
console and preview. Display command status and validation near the editor.
Suspend motion shortcuts during editing. Implement keyboard/focus fixes from
the touch audit alongside the new layout.

Sources: [makera.kv](../carveracontroller/makera.kv), `ManualCMDPage`;
[main.py](../carveracontroller/main.py), `MDITextInput`.

### UX-10: WCS editing mixes a dense grid with unclear validation semantics

Priority: high. Evidence: rendered and source.

WCS settings keeps eight columns for workspace selection, offsets, rotation,
clearing and descriptions. It is vertically scrollable, but it does not reflow
into readable workspace details on compact displays.

There are also two different commitment models: tapping a WCS name executes an
activation command immediately, while numeric edits wait for Save/OK. Invalid
numeric values are skipped by `apply_changes`; the OK binding then dismisses
the dialog without field-specific feedback. Clear All changes the draft
values, so its effect should be explained in that same editing model.

Use a workspace list and a detail editor. Label activation as an immediate
action, distinguish active workspace from the one being edited, and show units.
Validate all edited values before applying, retain invalid drafts with an
inline explanation, and keep the dialog open until the user resolves them.
Preserve existing change tracking and discard labels.

Sources: [makera.kv](../carveracontroller/makera.kv), `WCSSettingsPopup`;
[main.py](../carveracontroller/main.py), `apply_changes`, `activate_wcs`,
`clear_all_wcs`, and `check_for_changes`.

### UX-11: Probe operation discovery and parameter entry compete for space

Priority: medium. Evidence: first tab rendered; all nine tab layouts inspected.

Probing offers nine horizontal operation tabs and shows direction diagrams,
parameters and jog controls in the same dialog. Several tabs are off screen
until horizontal scrolling. Dense parameter rows use small text, abbreviated
names and G-code parameter letters. Increasing scale causes label clipping.

Use a discoverable operation chooser and separate selection, parameter entry,
and review where space requires it. Show descriptive names and units first,
with parameter codes as supporting information. Keep jog access available
without permanently allocating a large portion of every operation screen.
Preserve tool, firmware and optional-axis restrictions.

Sources: [ProbingPopup.kv](../carveracontroller/addons/probing/ProbingPopup.kv),
[ProbingControls.kv](../carveracontroller/addons/probing/ProbingControls.kv),
and the nine [operation settings layouts](../carveracontroller/addons/probing/operations/).
Evidence: [probing](mobile-ux-audit-images/probing.png).

### UX-12: Motion workflows need a clearly reachable software Halt

Priority: high. Evidence: source; physical behavior untested.

Modal views intercept touches outside their content, including the application
Stop control visible behind them. Probe preview supplies its own Halt action
while running, which is a useful existing pattern. CMM instead exposes Close,
then a confirmation to discard the result; that confirmation cancels the probe
operation. This makes stopping dependent on a less obvious, multi-step route.

Provide a clear, persistent Halt/Cancel Operation action in an active operation
view, with feedback that distinguishes stopping from stopped. Separate stopping
motion from leaving the screen or discarding data. Keep controls inside the
visible bounds during keyboard and window changes.

This concerns software control accessibility. No physical stop behavior was
tested. Motion cancellation defects in the touch audit remain prerequisites.

Sources: [makera.kv](../carveracontroller/makera.kv), application Stop;
[ProbingPreviewPopup.kv](../carveracontroller/addons/probing/preview/ProbingPreviewPopup.kv);
[CMMWorkbenchPopup.py](../carveracontroller/addons/cmm_workbench/ui/CMMWorkbenchPopup.py),
`dismiss` and `_confirm_dismiss_while_probing`;
Kivy 2.3.1 `ModalView` touch dispatch.

### UX-13: CMM needs separate capture, preview and construction views

Priority: high. Evidence: rendered and source.

CMM keeps seven operation tabs on the left and preview, eight construction
actions and feature rows on the right. Several tabs are hidden horizontally.
The manual form's position/load row has fixed widths; larger UI scaling clips
it. Construction button labels are cramped even before a session contains data.
Load, Save as, Copy as, Reset, Jog, Close and Help share a footer.

On compact displays, separate capture from the feature list/preview. Put
construction actions with selected features and explain selection requirements.
Use readable feature details and a clear save state. Keep Jog as a bounded
overlay; its existing width limit is useful, but its height follows content
without a corresponding available-height cap.

Sources: [CMMWorkbenchPopup.kv](../carveracontroller/addons/cmm_workbench/ui/CMMWorkbenchPopup.kv),
[CMMWorkbenchPopup.py](../carveracontroller/addons/cmm_workbench/ui/CMMWorkbenchPopup.py).
Evidence: [CMM](mobile-ux-audit-images/cmm.png).

### UX-14: Facing starts with help instead of the required inputs

Priority: medium. Evidence: rendered and source.

Facing keeps four tabs and a sketch in a narrow left pane, while an initially
empty G-code preview occupies the larger right pane. In the default-equivalent
render, the Stock tab's long help paragraph fills the initial viewport and
pushes its required fields below it. Some explanatory text is only 9dp.

Present Stock, Cutting, optional Probing, and Tool/Output as clear steps. Put
essential fields first, offer concise contextual help, and expand diagrams or
the program preview on demand. Make generated/current/out-of-date state visible
before the user chooses an output action. Preserve the existing stale-program
confirmation and viewport-bounded preset dialogs.

Sources: [FacingWizardPopup.kv](../carveracontroller/addons/facing/FacingWizardPopup.kv),
[FacingWizardPopup.py](../carveracontroller/addons/facing/FacingWizardPopup.py).
Evidence: [facing](mobile-ux-audit-images/facing.png).

### UX-15: Settings needs compact navigation and consistent value editors

Priority: medium. Evidence: rendered and source.

Settings uses Kivy's fixed 200dp sidebar. The remaining width must fit setting
titles, descriptions, values and custom action buttons. The rendered color
setting already shows crowded value/action text. Configuration spans Controller,
G-Code Viewer, Pendant and conditional machine panels.

Use a category list or selector on compact displays, with a full-width detail
view and search. Put values beneath descriptions when necessary. Reuse a shared
mobile editor for numeric, text, option, color and macro settings. Bound option
lists by the available window height and scroll their content; Kivy's default
option popup computes height from the number of choices.

The C1 schema contains 93 entries and the CA1 schema 70, including section
titles. Actual exposed settings depend on the reported configuration. Keep the
existing deferred Apply/discard behavior and review changed values before
machine settings are applied.

Sources: [main.py](../carveracontroller/main.py), `MakeraConfigPanel`,
`DeferredSettingsPanel`, and `ConfigPopup`;
[custom_widgets.py](../carveracontroller/custom_widgets.py);
[controller settings](../carveracontroller/controller_config.json),
[C1 schema](../carveracontroller/config_c1.json),
[CA1 schema](../carveracontroller/config_ca1.json);
Kivy 2.3.1 `MenuSidebar` and `SettingOptions`.
Evidence: [settings](mobile-ux-audit-images/settings.png).

### UX-16: Diagnostics and device configuration need grouped detail screens

Priority: medium. Evidence: diagnostics and gamepad rendered; related source inspected.

Diagnostics presents many switches, sliders and state values in one dialog.
On a small screen, users must interpret both the abbreviated control name and
whether it is available. Gamepad bindings already has a scrollable list and a
separate Save/Cancel footer, but its 36dp rows and multiple controls per row
remain small.

Group diagnostics by function, place measured state beside the related control,
and explain restrictions. For bindings, use larger rows or a detail editor,
with an unmistakable waiting-for-input state and cancellation. Preserve the
existing practice of pausing the gamepad manager while configuring it.

Sources: [makera.kv](../carveracontroller/makera.kv), `DiagnosePopup`;
[pendant.py](../carveracontroller/addons/pendant/pendant.py), `GamepadBindingsPopup`.
Evidence: [gamepad bindings](mobile-ux-audit-images/gamepad-bindings.png).

### UX-17: Save, import and export behavior differs by platform and workflow

Priority: medium. Evidence: source; platform journeys untested.

The main iOS file-selection path uses a native picker. CMM explicitly disables
Load and Save as on iOS, while Copy as remains available. Generic local save
dialogs use a directory chooser and filename field. Android storage shortcuts
can open the system all-files permission screen. Mobile machine backup controls
are also disabled or omitted.

Make available destinations explicit and give a useful explanation or
alternative when an operation is unavailable. Investigate native document
import/export for reusable features, preserving permissions and confirming
completion. Keep Copy as as a useful option. Show unsaved state consistently
for CMM sessions, macro editing, facing presets and settings, and retain drafts
during temporary navigation.

Source restrictions establish current behavior; they do not prove that native
mobile export is impossible. Any Android permission-flow change needs its own
device validation after the other session's work is complete.

Sources: [main.py](../carveracontroller/main.py), file selection and machine
settings panels; [Utils.py](../carveracontroller/Utils.py), storage access;
[LocalFilePicker.py](../carveracontroller/ui/LocalFilePicker.py);
[CMMWorkbenchPopup.py](../carveracontroller/addons/cmm_workbench/ui/CMMWorkbenchPopup.py).

### UX-18: Readability and larger text need a shared policy

Priority: high. Evidence: source inventory and renders; device accessibility untested.

Of 175 explicit font-size declarations in the Kivy layouts, 127 use `dp`,
47 use `sp`, and one uses another expression. `dp` fonts do not follow Kivy's
user font-scale preference. Facing includes 9dp and 10dp text; status secondary
values use 11sp. The resolution-derived density can shrink these further.

Use a small, shared set of readable text sizes that respects font preferences.
Allow labels to wrap and containers to grow. Preserve the complete wording of
important choices and errors. Test larger text, long numbers, long filenames
and longer translations; no translated-language render or 150–200% font-scale
test was performed in this audit.

Confirm text contrast in enabled states and make state understandable with
words as well as color. Native screen-reader behavior and focus order were not
tested, and no project-specific accessibility bridge was found in the inspected
UI source. Treat TalkBack/VoiceOver names and navigation as an explicit
validation item rather than claiming support or failure from screenshots.

Sources: all layout files, particularly [makera.kv](../carveracontroller/makera.kv),
[facing](../carveracontroller/addons/facing/FacingWizardPopup.kv), and
[CMM](../carveracontroller/addons/cmm_workbench/ui/CMMWorkbenchPopup.kv).
Reference: [Android text scaling guidance](https://support.google.com/accessibility/android/answer/12159181).

### UX-19: Recovery and update screens need clearer states and readable detail

Priority: medium. Evidence: rendered and source.

Message, progress and reconnection dialogs generally use a half-width,
40%-height layout. Long paths, import warnings and compatibility explanations
can need more room than their non-scrollable labels provide. The generic
confirmation dialog already uses a scrollable body, offering a pattern to reuse.

Updates present separate Controller/Firmware tabs with checking, download and
update actions. Mobile backup is disabled in the firmware tab without an inline
explanation. The fixed firmware toolbar can also crowd its container.

Show a short status and next action, with expandable or scrollable detail.
Distinguish loading, waiting, cancelling, cancelled, failed and completed.
Keep progress and Cancel/Retry visible, and explain what cancelling affects.
For updates, name the target, current/new version, available backup route and
next step. Preserve compatibility checks rather than weakening them to simplify
the UI.

Sources: [makera.kv](../carveracontroller/makera.kv), `MessagePopup`,
`ProgressPopup`, `ReconnectionPopup`, `ConfirmPopup`, and `UpgradePopup`;
[main.py](../carveracontroller/main.py), compatibility and progress flows.

## Patterns worth preserving

- Confirmation text already scrolls and has a fixed action footer.
- WCS and Settings track changes; Settings supports deferred Apply and discard.
- Facing warns when generated G-code is stale and bounds preset-dialog height.
- Gamepad configuration uses a scrollable body, Save/Cancel, and pauses its manager.
- Forms in probing, facing and CMM already use scrolling in several places.
- CMM enlarges sketch hit areas and has a width-bounded jog overlay.
- The main iOS file-import path uses a native picker.
- Existing capability and firmware checks determine available operations.

Reuse these patterns as shared building blocks. A bounded dialog with a
scrollable body and a reachable action footer would improve several screens
without changing their machine operations.

## Recommended sequence

1. Fix overlapping consequential choices and overflowing job-setup dialogs.
   Address motion cancellation from the touch audit at the same time.
2. Establish shared readable sizing, bounded dialogs and adaptive navigation.
3. Adapt Control and the Files/Preview/MDI workflow for compact windows.
4. Adapt WCS, probing, CMM and facing around individual tasks and review steps.
5. Unify editing, errors, save state, recovery and import/export behavior.
6. Validate larger text, translations, capability combinations and real mobile
   workflows before submitting behavior changes.

## Validation matrix for implementation

Existing screenshot tests configure a desktop window at 1920 by 1080. They
help detect changes to that baseline but do not establish mobile layout or
Android behavior. This audit's local renders add layout evidence; they do not
replace those tests or real-device checks.

| Dimension | Cases to validate |
| --- | --- |
| Display and window | Actual Pi panel, small landscape phone, tablet, large desktop, resized/multi-window bounds where supported |
| Scaling | Android density, app UI override, default/150%/200% text, usable space above the keyboard |
| Content | Long translated labels, large signed coordinates, long paths/names, many files, many CMM features, lengthy error/update text |
| State | Disconnected, connecting, idle, active job, paused, alarm, waiting on communications, reconnecting, failure and completion |
| Machine capabilities | C1, CA1, optional rotary axis, ATC where actually present, firmware restrictions, conditional camera support |
| File-to-job workflow | Find/import, preview, upload/select, configure, review, start, monitor, pause/halt, recover and resume |
| Probing and CMM | Choose operation, edit parameters, position, review, start, halt, retain results, save/export and reopen |
| Editing | Inline invalid-value feedback, draft retention, correct commit/cancel behavior, keyboard dismissal and return |
| Platform | Android permission denial/return, native file flows, iOS export restrictions, background/resume and system bars |
| Accessibility | Readable enabled-state contrast, full labels, screen-reader names/focus order, color-independent state |

For each changed screen, require that every necessary setting and final action
is reachable, that important wording is fully readable, and that layout changes
preserve existing state and machine semantics. Changes affecting machine
behavior need controlled testing on a real C1 or CA1 with the affected feature.
Record the actual machine and effective configuration; a screenshot or build
does not validate motion.

## Supporting screenshots

All linked images are 800 by 480 local framebuffer renders using disconnected
or synthetic data. Density is 0.8 unless explicitly noted. They illustrate
layout evidence; they are not recordings of the user's Pi or of machine actions.

The unlock choices overlap at the default-equivalent scale:

![Unlock choices overlap](mobile-ux-audit-images/unlock.png)

Job-setup options extend above the visible dialog:

![Job setup options overflow](mobile-ux-audit-images/job-setup.png)

Facing initially presents help while required fields are below the viewport:

![Facing wizard initial layout](mobile-ux-audit-images/facing.png)

Other evidence:

- [Control at default-equivalent scale](mobile-ux-audit-images/control-default.png)
- [Control at density 1.0, with status/action overflow](mobile-ux-audit-images/control-larger-scale.png)
- [Icon-only navigation menu](mobile-ux-audit-images/navigation-menu.png)
- [Probe-selection choices](mobile-ux-audit-images/select-probe.png)
- [Auto-level layout](mobile-ux-audit-images/auto-level.png)
- [Probing parameters](mobile-ux-audit-images/probing.png)
- [CMM capture and construction](mobile-ux-audit-images/cmm.png)
- [Settings sidebar and value/action layout](mobile-ux-audit-images/settings.png)
- [Remote files](mobile-ux-audit-images/remote-files.png)
- [Local files](mobile-ux-audit-images/local-files.png)
- [Gamepad binding list and Save/Cancel footer](mobile-ux-audit-images/gamepad-bindings.png)

## Notes for later sessions

- Read this together with the [touch audit](android-touch-audit.md). Layout
  improvements alone will not correct its demonstrated input-event defects.
- Check the current checkout and preserve unrelated work. The audit does not
  authorize changing or interrupting another session's Pi activity.
- Source-only findings and untested platform behavior need targeted validation;
  do not describe them as reproduced device failures.
- Use actual available space, font preferences and capabilities when designing
  alternatives. Do not rely on shrinking the interface to make controls fit.
- Keep implementation narrowly tied to the chosen UX improvement and preserve
  existing compatibility and machine safeguards.

## Implementation verification (October 15, 2026)

The original renders above describe 2.2.0, before the Android touch work.
Current work builds on 3ef91ef. Android density, keyboard composition,
captured jog cancellation, file selection, viewer gestures and CMM sketch
zoom already have separate evidence in the touch audit.

The first landscape UX checkpoint replaces automatic outer scrolling with
explicit content viewports and fixed action rows for unlock, probe choice,
messages, reconnect and progress. Other forms retain their own viewports.
Local integration tests now replace physical transports, reconnect, discovery
and pendant access before constructing the application, and isolate probe
preferences as well as Kivy preferences. No Pi or mill was accessed.

Device acceptance for this work is pending the user's release of the device.
