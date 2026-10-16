# Manual four-corner homing and paper calibration

Open **Calibration** in the header for pen setup, paper-corner capture and
position recovery. **Prepare** contains artwork import, conversion settings,
toolpath preview and the explicit upload/start confirmation. **Print & monitor**
contains upload/drawing progress, job queue, robot controls and live speeds.
After the final calibration step is saved (or saved position is restored), the
app opens Prepare automatically. Starting a job opens monitoring immediately.
Preparing another image does not change the active job. You can switch
pages without discarding drafts or sending any motion commands; starting a job
still requires a valid physical reference and explicit review.

This workflow needs no limit switches. The computer stores the four captured
corners and derived paper/belt reference in the ignored, owner-only file
`controller/data/paper_calibration.json`. It survives service restarts and
power loss until successfully replaced by a new calibration.

**Saved calibration is not proof of physical position after power loss.** The
ESP32 always boots position-unknown. After reset, motor release, belt slip or
manual movement, explicitly re-establish the saved top-left reference, or
recalibrate all corners. Never recover from stored step counts alone.

## First calibration

### Pen in / out (independent of paper corners)

Use **Pen positions** in the calibration card before calibrating paper. Confirm
linkage clearance, then begin. Move by ±1°, ±5°, ±10° or ±30°, or enter a direct
10–170° target. All moves retain the gentle servo ramp. Adjust until the pen is
lifted clear, and capture **pen in**. Adjust until the tip just touches the paper,
then capture **pen out**. Test both strokes and save. The servo ramps gently;
never use the endpoint to force extra pressure or push against a mechanical stop.

Either angular direction can mean pen out. Endpoints must be distinct and within
10–170°; these electrical limits are not proof your linkage can reach every angle.
Saving lifts the pen and writes both endpoints atomically to ESP32 NVS, plus a
host record in `controller/data/pen_calibration.json`. They survive normal power
cycles and firmware uploads that preserve NVS. Factory flash/NVS erasure removes
them. Paper corners are not changed. Re-prepare queued artwork after changing
endpoints so it uses the new angles. Cancel lifts to the previous saved pen-in.

Pen adjustment requires no XY homing, but is mutually exclusive with paper
capture and drawing. Link loss discards the adjustment draft and lifts to the
previous pen-in setting. At boot the servo has no position feedback, so support
the gondola during the initial pen-in command. This is position calibration,
not force/pressure sensing.

### Paper corners

1. Install and tension the belts. Verify that positive/payout on each motor
   lengthens its gondola-side belt; fix reversed directions before capture.
   Calibrate the pen lift first so 90° actually clears the paper. Keep hands
   away from pulleys, counterweights retained, and a power switch accessible.
2. Place the paper flat; **rotation is supported**. The fit uses the selected
   paper's dimensions to estimate belt offsets, with a common point-like gondola
   reference. Always align the same projected pen-tip point, not different
   edges of the gondola. Separated belt attachments/sag can introduce error.
3. Open **Manual paper calibration**. Enter motor shaft spacing in mm and the
   actual paper preset. This machine's previously measured spacing is
   25 3/8 in = **644.525 mm**; remeasure if the frame/motors changed.
4. Check the supervision/pen-clearance confirmation and click **Begin / restart
   calibration**. This engages the motors, commands pen-up, invalidates the
   previous live position and starts fresh relative pulse counters. It does not
   move XY or erase a previously saved paper calibration.
5. Use left/right retract/payout to place the reference at **top-left**. Start
   with 0.25 or 1 mm jogs; each click is bounded, and concurrent requests are
   rejected rather than queued. Maximum click: 50 mm and 4000 pulses. Jogs ramp
   up to 20 mm/s; check clearance before using the larger distances. There is
   no continuous jog or automatic search. Capture top-left.
6. Jog/capture **top-right**, **bottom-right**, then **bottom-left**. Keep the
   same paper, belt tension, pen reference and powered motor state throughout.
   Do not drag the gondola by hand: that bypasses the recorded pulse counts.
7. Click **Validate & save corners**. The computer uses the known paper size,
   motor spacing and steps/mm to infer both absolute belt-length offsets and
   paper XY placement using rotation-invariant distances. It accepts the actual
   four-corner outline, not an ideal axis-aligned rectangle. Paper-size mismatch
   is advisory, not a 3 mm rejection. Degenerate, crossed/unreachable captures
   and points outside machine limits still cannot establish a usable reference.
   Absolute belt lengths remain an estimate based on the selected paper size,
   spacing and pulley scale; acceptance does not certify drawing accuracy.
8. On acceptance, paper placement is filled/locked from the saved calibration,
   the device reports `reference: user`, and normal speed presets are enabled.
   The old temporary +/-80 mm envelope and 2 mm/s drawing cap no longer apply.
   Artwork is mapped bilinearly into the captured quadrilateral. Firmware
   limits drawing to its axis-aligned envelope plus a 3 mm model
   tolerance, 30 mm/s maximum and existing acceleration limits. Keep positive
   drawing margins; tolerance space is not extra guaranteed paper.

The physical travel limits remain the user's responsibility while jogging:
without switches or a prior reference, software cannot know how close the
gondola/counterweights are to a collision. Pause/link loss aborts an in-progress
calibration; Stop disables motors and latches a reset-required fault. Begin
again after an interrupted capture session. Stop/power removal can release a
suspended load; keep it mechanically retained.

## Subsequent boots / position recovery

Keep the paper and mechanics unchanged. If needed, use Begin plus bounded jogs
to return to the **same saved top-left reference point**, without capturing new
corners. Check the explicit top-left-position confirmation and click **Restore
position at top-left**. This sets the known belt reference without an XY move,
retains the saved corners and restores normal drawing speeds. If already
physically positioned there, no jog session is required.

The service never restores position, homes or resumes motion automatically.
A same-boot network reconnect may retain a known reference; resuming a paused
job remains explicit. A device reboot interrupts the old job; restore/re-home
and restart explicitly. Changed motor scale requires full recalibration, and
prepared jobs tied to an older calibration must be prepared again.

## Live speed controls

The **Live speeds** card works before and during drawing, including while a job
is paused. Choose values and click **Apply speeds**; no artwork conversion or
job restart is needed. Stepper override is 10–100% of the prepared drawing feed:
100% restores that feed, while lower values slow the same trajectory. To choose
a higher base speed before drawing, change the artwork's drawing feed and
prepare it again. The override never exceeds the planned speed, acceleration
profile or the temporary manual-reference cap. It also scales calibration jogs;
switch homing retains its commissioned fixed speed.

Pen speed is 5–120°/s; acceleration remains limited to reduce gondola sway.
Drawing waits for the pen to arrive and settle even at the slowest setting.
Stepper changes ramp over at most about a second and take effect on already
buffered motion. Speed messages are authenticated, boot-bound, out-of-band
controls; they do not consume drawing command IDs, move the robot by themselves,
clear a pause, or restart a job. Stop remains independent and responsive.

These live values reset to 100% / 35°/s after board restart. Saved pen endpoints
and paper corners are unaffected. Estimated drawing time is still based on the
prepared feed, not subsequent live overrides.

## Protocol and implementation

Authenticated, sequence-numbered commands use the existing dedup ledger:

- `cal_begin` with `confirm: true`: idle-only, clear reference, pen up, reset
  relative belt counts; explicit start can clear an idle paused state.
- `cal_jog` with `axis: 0|1`, signed integer `steps`: requires active calibration,
  1–4000 pulses, at most 20 mm/s and 2000 pulses/s, with 40 mm/s² ramps
  starting/ending at 2 mm/s; counts only actual emitted pulses.
- `sync`: settle before reading/capturing `jog_steps`.
- `cal_apply` with `confirm`, `cal_id` UUID, `width`, `l`, `r`, `xmin`, `ymin`,
  `xmax`, `ymax`: validated idle-only reference/envelope, no XY movement.

Status advertises `calibration_api: 1`, `calibrating`, `jog_steps`,
`steps_per_mm`, `calibration_id`, `reference`, and calibrated `draw_bounds`.
The legacy `homed` field means position-established, not necessarily a switch
cycle. Firmware configuration and user bounds are RAM-only; EEPROM switch
calibration is not overwritten. Normal host storage is the source of saved
paper calibration and re-applies it only after explicit reference confirmation.

**Future gondola-top switches:** the old independent counterweight homing
routine is not appropriate for that arrangement. Leave switch homing disabled
until a coordinated docking routine and known mechanical reference are designed.
