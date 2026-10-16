# Development Progress Log

## 2026-10-16 — manual-reference mode removed; restore from any saved corner

- Removed the temporary manual-reference commissioning mode: USB `M665`,
  `wallSetManualReference`, the +/-10 mm (up to 80) envelope, the 2 mm/s firmware
  planner and stored-plot caps, the controller's 2 mm/s artwork cap/warning,
  the `reference: manual` status and `MANUAL_COMMISSIONING.md`. Four-corner user
  calibration is the only non-switch reference. Its envelope and existing
  firmware feed/acceleration limits are unchanged.
- Position restore after reset now works from any one saved corner (UI corner
  selector; API `corner` + `at_corner`, `at_top_left` still accepted), since the
  saved calibration holds all four. Requires unchanged paper; otherwise recalibrate.
- Python suite (47 tests) passes, including restore at bottom-right after a
  reboot. **Firmware not compiled or flashed**: no C++ toolchain on the editing
  machine; build (`pio run`) and run `test/esp32_logic.cpp` before flashing.

## 2026-10-14 — slicer-style Prepare and Print/monitor separation

- Split preparation from monitoring into separate header routes, alongside
  Calibration. Prepare owns image settings, toolpath preview and reviewed start;
  Print & monitor owns job history/status, upload progress and live controls.
- Starting opens monitoring immediately while the full file uploads. Preparing
  another image preserves the active monitored job and navigating back preserves
  the preparation draft. Queue selection monitors metadata without replacing
  artwork; an explicit Review action opens queued/completed jobs in Prepare.
- Added global Stop across all pages and retained calibration handoff into
  Prepare. Existing #workspace bookmarks remain supported as a Prepare alias.
- Web regression checks cover independent preparation during an active draw,
  correct monitor selection, reviewed start/upload handoff and safe navigation.
  Browser visual QA remains unavailable (no connected browser surfaces). Static
  UI files are served live; no backend restart, flash or motor command needed.

## 2026-10-14 — separate calibration and drawing pages

- Added hash-routed Calibration and Drawing workspace pages with persistent
  header navigation. Calibration forms move intact into their own page; artwork,
  preview, job controls, queue and live speeds stay in the workspace.
- Initial connected setup opens calibration if pen/paper/reference setup is
  incomplete; active/ready robots open the workspace. Explicit navigation is
  respected. Finishing the last setup step or restoring position hands off to
  the workspace; changing pages alone sends no robot commands or loses drafts.
- Added calibration-page emergency Stop, readiness/continue state, responsive
  navigation and hidden-canvas handling. No controller restart or flash needed.
- Web regression tests cover separation, safe hash/back navigation, active-job
  controls and complete/incomplete calibration handoff. Visual browser preview
  unavailable: no browser surfaces are enabled in this session.

## 2026-10-14 — upload complete plots for independent execution

- Verified existing 4 MiB layout: SPIFFS partition 1,408 KiB; the user's
  13,234-command drawing needs 211,744 bytes in the compact 16-byte format.
- Added authenticated chunked upload, offset/retry handling, CRC32 and complete
  record/geometry validation, temporary-file publication and explicit idempotent
  start. Per-plot cap 1 MiB with available-space/headroom checks.
- Device reads stored records into the existing planner/servo executor. Wi-Fi
  loss does not hold a running stored plot; streaming still holds. Explicit
  pause/resume/Stop and safety faults remain effective. Reboot keeps the file,
  never physical position or an automatically resumed run.
- Controller uploads fully before start and reconciles progress after reconnect
  without streaming more commands. Network sends now buffer partial writes and
  tolerate brief congestion; telemetry is coalesced before reliable replies.
- Firmware build and 18 focused stored-plot/speed/pen/paper tests passed, plus
  two streaming retry/reconnect regressions and sanitized binary-format/CRC
  tests. With explicit approval, flashed over USB at 115200 baud; hash verified.
- Controller restarted with the same private link. Live status confirms stored
  plot and speed APIs, 1 MiB plot cap, saved corners and 170°/60° pen endpoints;
  no fault or motion, physical position unknown after reset. Filesystem is not
  initialized yet (free=0); the first confirmed upload will initialize storage.
  Supervised physical upload/offline execution still needs commissioning after
  restoring the saved top-left reference. No automatic test drawing was sent.

## 2026-10-14 — live pen and stepper speed controls

- Added local Live speeds card, enabled before/during/paused drawings: stepper
  override 10–100% of prepared feed and servo speed 5–120°/s. Apply preserves
  geometry, review state, pen endpoints and drawing command IDs.
- Authenticated boot-bound out-of-band speed messages bypass the drawing FIFO.
  Timer intervals scale buffered/in-flight motion without exceeding the original
  profile; stepper override ramps at 100 percentage points/s. Calibration jogs
  share the override. Servo acceleration and arrival/settle waits remain active.
- Defaults reset on device boot; runtime settings do not write NVS. Longer
  supervised calibration deadlines accommodate minimum speed selections.
- Firmware compile, 13 focused speed/pen/paper tests and sanitized interval
  scaling tests passed. Local UI regression includes controls during a draw.
  Firmware deployment awaits user readiness; no automatic motion was sent.

## 2026-10-14 — coarse and direct pen adjustment

- Added ±10°/±30° alongside fine ±1°/±5° controls, plus direct whole-degree
  targets within 10–170°. Existing firmware gentle ramp remains unchanged.
- Four focused pen tests and web regression checks passed. Local controller
  updated without flashing, retaining captured endpoints and the private link.

## 2026-10-14 — user-calibrated pen in/out endpoints

- Added independent supervised pen calibration within the local calibration
  card: ±1°/±5° preview, capture/test in/out, save and cancel/lift. No XY homing
  is needed; paper capture and drawing remain mutually exclusive with tuning.
- New authenticated, deduplicated idle-only cal_pen/pen_config/pen_end commands;
  bounds 10–170°, distinct endpoints, either linkage direction supported.
- ESP32 saves endpoints together in one NVS value and loads before servo attach.
  Drawing, hold/Stop and calibration use those endpoints. Host keeps a record;
  changing angles invalidates prepared jobs without changing paper calibration.
- Includes the gentle servo ramp. With user approval, flashed over USB at
  115200 baud; application hash verified. Restarted the local controller with
  the same private link; pen_calibration_api=1, no fault/motion, saved paper
  calibration retained. Physical position must be restored explicitly.
- Firmware compile, 10 focused pen/paper tests, servo-ramp sanitizer test and
  existing web regression checks passed. No device pen preview was sent.

## 2026-10-14 — gentle pen actuation

- ESP32 PWM now follows an acceleration-limited, nonblocking ramp: 35°/s
  maximum and 100°/s² acceleration in both directions. Target writes remain
  ISR-safe; small PWM changes are applied only from the main task.
- Wireless pen commands and resume wait for the commanded ramp plus 300 ms
  settling before XY motion. Calibration begin and switch homing wait for
  pen-up completion. Stop/link service remains responsive during the ramp.
- Pen angles and motor jog/drawing speeds are unchanged. The standard 50°
  pen stroke takes about 1.7 seconds instead of an immediate target jump.

## 2026-10-14 — accept rotated and imperfect captured paper outlines

- Removed axis-aligned fitting and the 3 mm residual rejection. Infer the two
  belt offsets with rotation-invariant pairwise distances, then retain all four
  measured corners. Paper-size disagreement becomes an advisory warning.
- Map artwork and margins bilinearly into the captured quadrilateral, subdivide
  transformed segments and show the actual outline in the local preview.
- Keep distinct/non-crossing/convex and reachable-machine-region checks. Belt
  lengths are still estimated from paper size, motor spacing and pulse scale;
  accepting captures is not a guarantee of metric accuracy.
- Seven focused calibration tests pass, including rotated paper, imperfect
  captures, artwork placement and the exact captures from the rejected session.

## 2026-10-14 — calibration speed increased again

- Increased calibration jog ceiling from 10 to 20 mm/s and acceleration from
  20 to 40 mm/s². Retained 2 mm/s endpoints, 2000 pulses/s ceiling, 50 mm clicks
  and cooperative Stop/link-loss checks. Updated local UI and operator guide.

## 2026-10-14 — faster, longer calibration jogs

- One-click distances now include 10, 25 and 50 mm; controller, simulator and
  firmware accept up to 4000 pulses. Default remains 1 mm for fine positioning.
- Calibration ramps from 2 to 10 mm/s at 20 mm/s² and decelerates at the end;
  cooperative stop/link-loss checks remain active throughout each jog.
- Firmware build and the focused jog-boundary test passed; full suite omitted
  per user request. Updated operator guidance; no automatic test jog sent.

## 2026-10-14 — front-facing motor channel correction

- User observed left controls operating the physical right motor, and right
  retract paying out the physical left belt. Swapped STEP/DIR/EN channel groups:
  logical left = 18/19/23; logical right = 26/27/25. Switch inputs remain 32/33.
- Added per-axis direction inversion, left enabled/right unchanged, applied
  consistently to startup, calibration jogs, D0, planner direction and homing.
- Updated wiring/PCB pin maps. Earlier captures must be discarded and calibration
  restarted. Compile-only verification requested by user; no automatic jog sent.

## 2026-10-14 — switch-free user paper calibration

- Added web-controlled bounded belt jogs, ordered TL/TR/BR/BL capture, geometry
  fitting/validation and owner-only persistent paper calibration. Normal
  preset speeds apply after acceptance; independent device paper bounds remain.
- Added explicit top-left reference recovery after reset; never restore physical
  position automatically. Unfinished calibration aborts on pause/link loss.
- Firmware build, 34 Python tests, sanitized C++ bounds/geometry tests and
  JavaScript regression checks passed. Physical corner capture awaits user test.
- With user approval/readiness, flashed ESP32 successfully (upload hashes
  verified). Image SHA256:
  `8c048277cd286f0e490557b32f2bf52d47298f6de39c99b518eacea736a842ea`.
- Updated controller reconnected; live telemetry verified calibration_api=1,
  position unknown, pen commanded 90, no fault/motion and switch homing disabled.
  No calibration jog or XY move was sent automatically.
- See USER_CALIBRATION.md for geometry assumptions, workflow and recovery.

## 2026-10-13 — fixed server-side robot linking

- Removed the two requested introductory sentences and the browser address/key
  form, connect/disconnect controls and corresponding linking API endpoints.
- Robot host/port/pairing key now come from a private ignored `.env` (or startup
  environment overrides). Configuration is immutable for the process lifetime;
  no runtime discovery, browser override, or legacy credential fallback.
- Server automatically links/retries the configured robot, without homing,
  starting or resuming motion. Status remains visible without linking details.
- Populated local configuration from the existing connection, with mode 0600;
  kept the session UUID but removed credentials from the old runtime journal.
- All 29 Python tests and isolated JavaScript UI checks pass. Live page/API
  verified; robot unavailable at final check and retrying. No motion commanded.

## 2026-10-12 — Connected board flashed

- Identified the USB CP2102 board as ESP32-D0WD-V3 revision 3.1, with a 40 MHz crystal.
- Flashed esp32-polargraph to /dev/cu.usbserial-0001; all written flash data hashes verified.
- Observed the firmware boot banner, commissioning/drawing lock, and generated setup network Drawy-Setup-67b4fc over USB. Setup secrets were redacted from diagnostic output and were not saved in the repository.
- Automatic homing confirmation remains 0; no motor motion was commanded.
- USB M114 verified X0/Y0, pen-up angle 90, Position UNKNOWN, Stop CLEAR, and both unwired NC inputs reading 1. WIFI SETUP also responded correctly after boot.
- Fixed an inherited unnumbered USB-command checksum-removal buffer underflow before flashing.
- Firmware image SHA-256: 509b9f302f343f7455a8ab1694d2492b64b072a80e9b720893e810a2c0b6fd43.

## 2026-10-12 — Wireless controller and artwork workflow

- Added generated WPA2 setup-network credentials, an AP-only provisioning page, captive DNS, up to three saved networks in NVS, automatic fallback/retry, and mDNS discovery. Home-network passwords are entered at setup and are not compiled into the firmware.
- Added authenticated, bounded TCP JSON-lines control with boot/session IDs, sequence fingerprints, duplicate acknowledgements, capacity/status reports, heartbeats, and priority pause/resume/stop.
- Added a drain/pen-up/holding path for lost connections, retained same-boot queue/remainders, explicit resume, and boot-change lockout.
- Added a dependency-free Python service, browser controls, paper presets/placement/preview, SVG outline conversion, generated artwork, a job queue, and persistent progress/history.
- Added a standalone/integrated simulated robot and real TCP/HTTP integration tests for dropped acknowledgements, disconnect/reconnect, full buffers, stop, reboot, auth, bounds, and persistence.
- Verified the desktop UI in Firefox with the simulated robot: home, prepare harmonic artwork, preview, start, pause with pen up, resume, and stop requiring reset.
- Final verification: ESP32 firmware build passes (15.6% static RAM, 67.7% flash); all 16 Python tests pass; sanitized C++ geometry/homing/sequence-ledger checks pass.
- Physical provisioning, radio behavior, and actual motor/servo drawing checks remain commissioning work. No real hardware was operated or uploaded during this implementation.

## 2026-10-12 — ESP32-WROOM implementation

The owner confirmed an ESP32-WROOM with no wiring installed.

- Added and selected the pinned esp32-polargraph PlatformIO target.
- Replaced the incomplete board header with a verified WROOM GPIO allocation, active-low enable handling, and NC switch pull-ups.
- Added a 1 MHz ESP32 hardware-timer HAL, serial adapter, independent LEDC servo PWM, and EEPROM begin/commit support.
- Fixed startup motor engagement, null planner-block direction access, servo coordinate initialization, and millimetre-before-microstep rounding.
- Added independent bounded seek/backoff/slow-latch homing, switch debounce/release checks, unhomed motion lockout, serial M112 during waits, and a reset-required fault latch.
- Added measured-geometry checks, commissioning jogs, configurable automatic boot homing, and conservative motion caps.
- Corrected ESP32 arc direction, preflighted arc extrema/radius, and bounded segment counts before integer conversion.
- Firmware compiles. Sanitized host tests pass for geometry and homing faults. No real hardware was attached, uploaded, or claimed bench-tested.
- Added the wiring/setup guide and ignored-local-configuration example. Homing confirmation remains off until physical commissioning establishes directions and travel.

Next: wire the bench according to the guide, verify switches/motor directions/servo clearance, measure anchor/reference geometry, then enable confirmed homing and test recovery.

## 2026-10-12 — Documentation baseline

### Completed

- Inspected source tree, PlatformIO configuration, polargraph kinematics, planner/motor pipeline, parser, EEPROM, servo path, and homing routines.
- Created the project brief, source audit, safety-first implementation plan, and this log.
- Modified documentation only; no firmware, build configuration, or hardware configuration changed.

### Findings

- 20T GT2 + 200 steps/rev + 16× microsteps calculates to 80 microsteps/mm.
- ESP32 support is incomplete: no PlatformIO environment or ESP32 HAL, placeholder switch pins, and AVR-HAL inclusion.
- Existing driver support is TMC2130, not TMC2209 UART. Begin TMC2209 as STEP/DIR.
- Existing homing does not meet power-loss/manual-displacement recovery without redesign.
- Exact ESP32 board and geometry are unknown, so no GPIO allocation was made.

### Risks

| Risk | Mitigation |
| --- | --- |
| Shallow frame stack-up | Measure actual hardware/ventilation |
| Unfinalized belt route | Prototype corner/counterweight path |
| Holding torque mistaken for running torque | Dynamic load test |
| Servo cable drag | Route/support and quantify |
| Switch fault ambiguity | NC wiring + precheck/timeout/fault |
| Legacy source age | Minimal hardware test before planner port |

### Next action

Complete Phase 0 mechanical survey and choose the exact ESP32 board. Then implement and bench-test ESP32 foundation before planner integration or motor operation on the finished frame.

# 2026-10-13 — bounded manual-reference commissioning

- At user's explicit request, added optional manual extent S (1..80 mm,
  default 10). Expanded-boundary/invalid-extent sanitized tests and firmware
  build passed; flashed image SHA256
  `141479fea3fcf36d34b6f1f32ae9887dbcd7e952716ceaf1446dc92760de35c0`.
- Established same measured reference with S80 and commanded 76.2 mm square
  right/down at F2. Settled M114 checked after every side; all MANUAL/CLEAR,
  final X306.75 Y-225.98. Drivers remain engaged; physical result unverified.

- Subsequently flashed successfully with verified upload hashes. Established
  `M665 W644.525 L381 R406.4 C1`: reported X306.75 Y-225.98, MANUAL/CLEAR.
- User authorized loaded test: commanded a 5 mm square at 1 mm/s, checking
  settled M114 status after each side. Returned to X306.75 Y-225.98 with
  MANUAL/CLEAR status. Drivers left engaged. Physical shape awaits user feedback.

- Added USB-only `M665 W<spacing> L<left> R<right> C1` to establish an
  explicitly measured temporary position without pretending switches were used.
- RAM-only geometry, distinct MANUAL status, +/-10 mm travel envelope, 2 mm/s
  cap, save prohibition, invalidation/restoration, and reset-before-homing guard.
- Firmware build and sanitized geometry/envelope checks passed. Controller suite:
  all 16 tests passed with local socket permission (sandbox denied test binds).
- Not flashed or exercised on loaded hardware yet: support/recheck gondola and
  verify physical belt payout directions before attempting a drawing.
- See MANUAL_COMMISSIONING.md for limitations and the user's measured values.

# 2026-10-13 — local image upload and plotting presets

- Added PNG/JPG/WebP upload alongside SVG, browser-local image decoding/white
  alpha compositing, and bounded grayscale input for Python-side conversion.
- Shaded serpentine hatching for photos and thresholded silhouette contours
  (including holes) for logos; full image frame/whitespace preserved.
- Fast/Balanced/Detailed presets control resolution, physical line density,
  outline simplification, stroke budget and default feed. Preview/time/metadata
  stored with jobs. Density adapts to large paper; manual mode's 2 mm/s cap is
  reflected in estimates. Settings changes invalidate review/preview selection.
- Added pixel/body/work/concurrency limits, helpful blank/complex image errors,
  and pen-lift requirement warnings. No new dependencies, cloud calls or ESP32
  changes. No physical motion sent for this feature.
- Python conversion/TCP/HTTP tests and isolated JS upload/preset/stale-preview
  tests pass. Real Firefox loaded new controls; file-picker end-to-end QA was
  interrupted by concurrent user browser activity and was not completed.
- Started the updated local-network controller; original process had exited.
