# Development Progress Log

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
